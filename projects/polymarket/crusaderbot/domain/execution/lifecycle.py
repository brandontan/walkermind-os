"""Order lifecycle management — fills, cancellations, expiries.

Phase 4C: a single APScheduler-driven async loop polls every in-flight
``mode='live'`` order against the broker (or simulates a fill in
paper mode) and dispatches on terminal status:

  * ``filled``    -> update orders + write per-fill rows + notify user
  * ``cancelled`` -> update orders + roll position back + notify user
  * ``expired``   -> same handling as cancellation
  * ``stale``     -> after ORDER_POLL_MAX_ATTEMPTS, page operator

Activation:
  * ``USE_REAL_CLOB=True``  -> query the real broker via ClobAdapter
  * ``USE_REAL_CLOB=False`` -> paper-mode mock fill after 1 poll cycle
                               so dry-run orders don't sit forever.

The manager never bypasses ``ENABLE_LIVE_TRADING``; it only reads
existing orders rows. New live orders are created in
``domain.execution.live.execute`` which retains the full guard chain.
"""
from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any, Awaitable, Callable, Optional
from uuid import UUID

from ... import audit as audit_module
from ... import notifications as notifications_module
from ...config import Settings, get_settings
from ...database import get_pool
from ...integrations.clob import (
    ClobAuthError,
    ClobClientProtocol,
    ClobConfigError,
    get_clob_client,
)
from ...wallet import ledger

logger = logging.getLogger(__name__)


# Status values tracked on the orders row. Kept in sync with
# domain/execution/live.py and migrations/015_order_lifecycle.sql.
STATUS_OPEN = ("submitted", "pending")
STATUS_FILLED = "filled"
STATUS_CANCELLED = "cancelled"
STATUS_EXPIRED = "expired"
STATUS_STALE = "stale"


class OrderLifecycleManager:
    """Polls live orders and dispatches terminal-state side effects."""

    # Paper-mode shortcut: after this many polls, the manager pretends
    # the broker responded with FILLED and runs the on-fill side effects
    # so paper-runs of the lifecycle path stay reachable in CI.
    PAPER_FILL_AFTER_ATTEMPTS = 1

    def __init__(
        self,
        *,
        settings: Optional[Settings] = None,
        pool: Any = None,
        clob_factory: Optional[Callable[[Settings], ClobClientProtocol]] = None,
        notify_user: Optional[Callable[[int, str], Awaitable[bool]]] = None,
        notify_operator: Optional[Callable[[str], Awaitable[None]]] = None,
        audit_write: Optional[
            Callable[..., Awaitable[None]]
        ] = None,
    ) -> None:
        self._settings = settings
        self._pool_override = pool
        self._clob_factory = clob_factory or get_clob_client
        self._notify_user = notify_user or notifications_module.send
        self._notify_operator = (
            notify_operator or notifications_module.notify_operator
        )
        self._audit_write = audit_write or audit_module.write

    # ----- public surface ---------------------------------------------

    async def poll_once(self) -> dict:
        """Run one polling sweep across every in-flight live order.

        Returns a small dict suitable for logging / job-tracker tracing.
        Never raises — per-order failures are logged and counted but do
        not abort the sweep, otherwise a single broker hiccup would stop
        every other order from progressing.
        """
        s = self._settings or get_settings()
        pool = self._pool_override or get_pool()
        max_attempts = int(s.ORDER_POLL_MAX_ATTEMPTS)

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, user_id, market_id, side, size_usdc, price,
                       polymarket_order_id, status, poll_attempts, mode,
                       fill_size, fill_price
                  FROM orders
                 WHERE mode = 'live'
                   AND status = ANY($1::text[])
                """,
                list(STATUS_OPEN),
            )
        outcome = {
            "polled": 0, "filled": 0, "cancelled": 0,
            "expired": 0, "stale": 0, "open": 0, "errors": 0,
        }
        if not rows:
            return outcome

        client: Optional[ClobClientProtocol] = None
        if s.USE_REAL_CLOB:
            try:
                client = self._clob_factory(s)
            except (ClobConfigError, ClobAuthError) as exc:
                logger.error("lifecycle poll: CLOB client unavailable: %s", exc)
                outcome["errors"] = len(rows)
                return outcome

        try:
            for row in rows:
                outcome["polled"] += 1
                order = dict(row)
                try:
                    resolution = await self._resolve_one(
                        order=order,
                        settings=s,
                        client=client,
                        max_attempts=max_attempts,
                    )
                except Exception as exc:  # noqa: BLE001
                    outcome["errors"] += 1
                    logger.error(
                        "lifecycle poll: order %s resolve failed: %s",
                        order["id"], exc, exc_info=True,
                    )
                    continue
                outcome[resolution] = outcome.get(resolution, 0) + 1
        finally:
            if client is not None:
                try:
                    await client.aclose()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("lifecycle poll: client.aclose failed: %s", exc)

        return outcome

    # ----- per-order resolution ---------------------------------------

    async def _resolve_one(
        self,
        *,
        order: dict,
        settings: Settings,
        client: Optional[ClobClientProtocol],
        max_attempts: int,
    ) -> str:
        """Resolve a single order; returns the bucket name used by
        ``poll_once`` for outcome accounting.
        """
        new_attempts = int(order["poll_attempts"]) + 1

        # --- paper-mode mock fill -------------------------------------
        # USE_REAL_CLOB=False: synthesise a fill so dry-run orders don't
        # accumulate. Real DB write paths still run so tests of
        # _on_fill / _record_fills exercise the same code as live.
        if not settings.USE_REAL_CLOB:
            if new_attempts >= self.PAPER_FILL_AFTER_ATTEMPTS:
                fill_price = float(order["price"])
                fill_size = float(order["size_usdc"]) / max(fill_price, 0.0001)
                synthetic_fill = {
                    "fill_id": f"paper-{order['id']}",
                    "price": fill_price,
                    "size": fill_size,
                    "side": order["side"],
                }
                await self._on_fill(
                    order=order, fill_price=fill_price, fill_size=fill_size,
                    fills=[synthetic_fill], attempts=new_attempts,
                )
                return "filled"
            await self._touch(order["id"], new_attempts)
            return "open"

        # --- live-broker resolution -----------------------------------
        if client is None:
            await self._touch(order["id"], new_attempts)
            return "open"

        broker_id = order.get("polymarket_order_id") or ""
        if not broker_id:
            # Order never made it past submit; treat as stale once the
            # poll budget is spent so it does not loop forever.
            if new_attempts >= max_attempts:
                await self._mark_stale(order=order, attempts=new_attempts,
                                       reason="missing polymarket_order_id")
                return "stale"
            await self._touch(order["id"], new_attempts)
            return "open"

        broker = await client.get_order(broker_id)
        status = _broker_status(broker)

        if status == "filled":
            fills = await client.get_fills(broker_id)
            fill_price, fill_size = _aggregate_fills(fills, fallback=order)
            await self._on_fill(
                order=order, fill_price=fill_price, fill_size=fill_size,
                fills=fills, attempts=new_attempts,
            )
            return "filled"
        # Cancel + expiry MUST reconcile broker fills before refunding.
        # A GTC partial-fill that the broker later cancels reaches us via
        # status='cancelled'; without fetching get_fills here the refund
        # math falls back to NULL fill columns and credits the full
        # size_usdc while the user keeps the matched shares. Codex P1.
        if status in {"cancelled", "expired"}:
            fills = await client.get_fills(broker_id)
            handler = self._on_cancel if status == "cancelled" else self._on_expiry
            await handler(order=order, attempts=new_attempts, fills=fills)
            return status

        if new_attempts >= max_attempts:
            await self._mark_stale(
                order=order, attempts=new_attempts,
                reason=f"max poll attempts reached (broker_status={status})",
            )
            return "stale"
        await self._touch(order["id"], new_attempts)
        return "open"

    # ----- side effects -----------------------------------------------

    async def _on_fill(
        self,
        *,
        order: dict,
        fill_price: float,
        fill_size: float,
        fills: list[dict],
        attempts: int,
    ) -> None:
        pool = self._pool_override or get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                updated = await conn.fetchval(
                    """
                    UPDATE orders
                       SET status = $2,
                           fill_price = $3,
                           fill_size = $4,
                           filled_at = NOW(),
                           poll_attempts = $5,
                           last_polled_at = NOW()
                     WHERE id = $1
                       AND status = ANY($6::text[])
                     RETURNING id
                    """,
                    order["id"], STATUS_FILLED,
                    fill_price, fill_size, attempts, list(STATUS_OPEN),
                )
                if updated is None:
                    # Already terminal — another poll cycle won the race.
                    logger.info(
                        "lifecycle on_fill: order %s already terminal, skipping",
                        order["id"],
                    )
                    return
                await self._record_fills_in_conn(
                    conn=conn, order_id=order["id"], side=order["side"],
                    fills=fills,
                )
                # Refresh the open position's current_price so dashboards
                # reflect the executed price; an UPDATE on the foreign
                # order_id is harmless if no position row exists yet.
                await conn.execute(
                    """
                    UPDATE positions
                       SET current_price = $2
                     WHERE order_id = $1
                       AND status = 'open'
                    """,
                    order["id"], fill_price,
                )

        await self._safe_audit(
            actor_role="bot", action="order_filled",
            user_id=order["user_id"],
            payload={
                "order_id": str(order["id"]),
                "market_id": order["market_id"],
                "side": order["side"],
                "fill_price": float(fill_price),
                "fill_size": float(fill_size),
                "fills": _safe_fills(fills),
            },
        )

        await self._safe_notify_user(
            user_id=order["user_id"],
            text=(
                "✅ *Order filled*\n"
                f"Market `{order['market_id']}`\n"
                f"*{str(order['side']).upper()}* {fill_size:.4f} @ {fill_price:.3f}"
            ),
        )

    async def _on_cancel(
        self, *, order: dict, attempts: int,
        fills: Optional[list[dict]] = None,
    ) -> None:
        await self._terminal_close(
            order=order, attempts=attempts, fills=fills or [],
            new_status=STATUS_CANCELLED, ts_column="cancelled_at",
            audit_action="order_cancelled",
            user_text=(
                "❌ *Order cancelled*\n"
                f"Market `{order['market_id']}`\n"
                f"*{str(order['side']).upper()}* size ${float(order['size_usdc']):.2f}"
            ),
        )

    async def _on_expiry(
        self, *, order: dict, attempts: int,
        fills: Optional[list[dict]] = None,
    ) -> None:
        await self._terminal_close(
            order=order, attempts=attempts, fills=fills or [],
            new_status=STATUS_EXPIRED, ts_column="expired_at",
            audit_action="order_expired",
            user_text=(
                "⌛️ *Order expired*\n"
                f"Market `{order['market_id']}`\n"
                f"*{str(order['side']).upper()}* size ${float(order['size_usdc']):.2f}"
            ),
        )

    async def _terminal_close(
        self,
        *,
        order: dict,
        attempts: int,
        fills: list[dict],
        new_status: str,
        ts_column: str,
        audit_action: str,
        user_text: str,
    ) -> None:
        pool = self._pool_override or get_pool()
        # Build the SQL dynamically so the same helper covers cancel/expiry
        # without duplicating two near-identical UPDATE statements. The
        # ts_column is interpolated from a fixed allowlist (the two
        # call sites in this file), never from user input.
        if ts_column not in ("cancelled_at", "expired_at"):
            raise ValueError(f"unsupported ts_column: {ts_column}")

        # Reconcile broker fills BEFORE updating the position. A GTC
        # partial-fill that the broker later cancels reaches us with
        # status='cancelled' and a non-empty fills list; the user
        # actually owns ``filled_notional`` worth of shares and is
        # only owed a refund on the unfilled remainder. If we ignored
        # the fills here we would either refund too much (full
        # size_usdc → user keeps shares + USDC) or roll the position
        # back to 'cancelled' (losing the share position entirely).
        avg_price, total_size_shares = _aggregate_fills(fills, fallback={})
        filled_notional = (
            Decimal(str(avg_price)) * Decimal(str(total_size_shares))
            if avg_price and total_size_shares else Decimal("0")
        )
        size_usdc = Decimal(str(order["size_usdc"]))
        # Clamp so a broker-reported overfill never produces a negative
        # refund or an inflated filled_notional.
        if filled_notional > size_usdc:
            filled_notional = size_usdc
        refund = size_usdc - filled_notional

        sql = f"""
            UPDATE orders
               SET status = $2,
                   {ts_column} = NOW(),
                   poll_attempts = $3,
                   last_polled_at = NOW(),
                   fill_price = COALESCE($5, fill_price),
                   fill_size = COALESCE($6, fill_size)
             WHERE id = $1
               AND status = ANY($4::text[])
             RETURNING id
        """
        partial_fill = filled_notional > 0
        async with pool.acquire() as conn:
            async with conn.transaction():
                updated = await conn.fetchval(
                    sql, order["id"], new_status, attempts,
                    list(STATUS_OPEN),
                    float(avg_price) if partial_fill else None,
                    float(total_size_shares) if partial_fill else None,
                )
                if updated is None:
                    logger.info(
                        "lifecycle %s: order %s already terminal",
                        audit_action, order["id"],
                    )
                    return

                # Position handling diverges by fill state:
                #   * partial fill -> resize position down to filled_notional
                #     and keep status='open' so the user retains the
                #     matched shares; refund the unfilled remainder.
                #   * no fills    -> roll position back to 'cancelled';
                #     refund full size_usdc.
                if partial_fill:
                    pos = await conn.fetchrow(
                        """
                        UPDATE positions
                           SET size_usdc = $2,
                               entry_price = $3,
                               current_price = $3
                         WHERE order_id = $1
                           AND status = 'open'
                         RETURNING id, user_id, size_usdc
                        """,
                        order["id"], filled_notional, float(avg_price),
                    )
                    if pos is not None:
                        await self._record_fills_in_conn(
                            conn=conn, order_id=order["id"],
                            side=order["side"], fills=fills,
                        )
                else:
                    pos = await conn.fetchrow(
                        """
                        UPDATE positions
                           SET status = 'cancelled', closed_at = NOW(),
                               exit_reason = $2
                         WHERE order_id = $1
                           AND status = 'open'
                         RETURNING id, user_id, size_usdc
                        """,
                        order["id"], new_status,
                    )

                # Refund unfilled USDC only when a position actually
                # rolled back / resized. 'pending' orders never debited
                # the ledger so they never get a spurious credit.
                if pos is not None and refund > 0:
                    await ledger.credit_in_conn(
                        conn, pos["user_id"], refund, ledger.T_ADJUSTMENT,
                        ref_id=pos["id"],
                        note=(
                            f"{audit_action} refund "
                            f"order={order['id']} unfilled=${refund}"
                        ),
                    )

        await self._safe_audit(
            actor_role="bot", action=audit_action,
            user_id=order["user_id"],
            payload={
                "order_id": str(order["id"]),
                "market_id": order["market_id"],
                "attempts": attempts,
                "filled_notional": float(filled_notional),
                "refund": float(refund),
                "fills": _safe_fills(fills),
            },
        )
        # Surface partial-fill refunds in the user message so a user
        # who sees a "cancelled" alert but holds matched shares is not
        # confused by a smaller-than-expected USDC credit.
        if partial_fill and refund > 0:
            user_text = (
                f"{user_text}\n"
                f"Filled `${float(filled_notional):.2f}` / "
                f"refunded `${float(refund):.2f}`"
            )
        elif partial_fill and refund == 0:
            user_text = f"{user_text}\nFully matched before cancel; no refund."
        await self._safe_notify_user(user_id=order["user_id"], text=user_text)

    async def _mark_stale(
        self, *, order: dict, attempts: int, reason: str,
    ) -> None:
        pool = self._pool_override or get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE orders
                   SET status = $2,
                       poll_attempts = $3,
                       last_polled_at = NOW(),
                       error_msg = COALESCE(error_msg, $4)
                 WHERE id = $1
                """,
                order["id"], STATUS_STALE, attempts, reason[:500],
            )
        await self._safe_audit(
            actor_role="bot", action="order_stale",
            user_id=order["user_id"],
            payload={
                "order_id": str(order["id"]),
                "market_id": order["market_id"],
                "attempts": attempts, "reason": reason,
            },
        )
        try:
            await self._notify_operator(
                "⚠️ *STALE ORDER*\n"
                f"order_id=`{order['id']}` user=`{order['user_id']}`\n"
                f"market=`{order['market_id']}` attempts=`{attempts}`\n"
                f"reason: `{reason}`\n"
                "Reconcile via Polymarket dashboard."
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("lifecycle stale notify failed: %s", exc)

    async def _touch(self, order_id: UUID, attempts: int) -> None:
        pool = self._pool_override or get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE orders
                   SET poll_attempts = $2,
                       last_polled_at = NOW()
                 WHERE id = $1
                """,
                order_id, attempts,
            )

    async def _record_fills_in_conn(
        self,
        *,
        conn: Any,
        order_id: UUID,
        side: str,
        fills: list[dict],
    ) -> None:
        """Write per-fill rows; safe to re-run via ON CONFLICT (fill_id)."""
        for fill in fills:
            fill_id = str(
                fill.get("fill_id")
                or fill.get("id")
                or fill.get("trade_id")
                or ""
            )
            if not fill_id:
                continue
            try:
                price = float(fill.get("price", 0) or 0)
                size = float(fill.get("size", 0) or 0)
            except (TypeError, ValueError):
                logger.warning(
                    "lifecycle: dropping fill with non-numeric price/size: %s",
                    fill,
                )
                continue
            await conn.execute(
                """
                INSERT INTO fills (order_id, fill_id, price, size, side, raw)
                VALUES ($1,$2,$3,$4,$5,$6)
                ON CONFLICT (fill_id) DO NOTHING
                """,
                order_id, fill_id, price, size,
                str(fill.get("side") or side).lower(),
                json.dumps(fill, default=str),
            )

    # ----- safe wrappers ----------------------------------------------

    async def _safe_audit(self, **kwargs: Any) -> None:
        try:
            await self._audit_write(**kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.error("lifecycle audit write failed: %s", exc)

    async def _safe_notify_user(self, *, user_id: UUID, text: str) -> None:
        pool = self._pool_override or get_pool()
        async with pool.acquire() as conn:
            tg_id = await conn.fetchval(
                "SELECT telegram_user_id FROM users WHERE id=$1", user_id,
            )
        if not tg_id:
            return
        try:
            await self._notify_user(int(tg_id), text)
        except Exception as exc:  # noqa: BLE001
            logger.error("lifecycle user notify failed: %s", exc)


# ---------------------------------------------------------------------------
# Module-level helpers + scheduler entry point
# ---------------------------------------------------------------------------


_default_manager: Optional[OrderLifecycleManager] = None


def get_default_manager() -> OrderLifecycleManager:
    global _default_manager
    if _default_manager is None:
        _default_manager = OrderLifecycleManager()
    return _default_manager


async def poll_once() -> dict:
    """Module-level shim used as the APScheduler job target."""
    return await get_default_manager().poll_once()


def _broker_status(broker_payload: dict) -> str:
    """Normalise broker status strings into the four buckets the
    lifecycle manager dispatches on.

    Polymarket has surfaced ``status``, ``state``, and ``orderStatus``
    across versions; we accept all three to avoid silently stalling on
    schema drift. The real CLOB also returns enum-style strings such
    as ``ORDER_STATUS_MATCHED`` / ``ORDER_STATUS_CANCELED`` /
    ``ORDER_STATUS_EXPIRED``; we strip the ``order_status_`` prefix
    so those land in the same buckets as the lower-case short forms.
    """
    raw = (
        broker_payload.get("status")
        or broker_payload.get("state")
        or broker_payload.get("orderStatus")
        or ""
    )
    raw = str(raw).strip().lower()
    if raw.startswith("order_status_"):
        raw = raw[len("order_status_"):]
    if raw in {"matched", "filled", "closed", "complete", "completed"}:
        return "filled"
    if raw in {"cancelled", "canceled"}:
        return "cancelled"
    if raw in {"expired"}:
        return "expired"
    return "open"


def _aggregate_fills(
    fills: list[dict], *, fallback: dict,
) -> tuple[float, float]:
    """Return (avg_price, total_size) over a fill list.

    Falls back to the order's submitted price/notional when the broker
    returns no fills — keeps downstream UPDATE statements satisfiable
    even on terse broker responses.
    """
    if not fills:
        price = float(fallback.get("price", 0) or 0)
        size = (
            float(fallback.get("size_usdc", 0) or 0) / max(price, 0.0001)
            if price else 0.0
        )
        return price, size
    total_size = 0.0
    weighted_price = 0.0
    for fill in fills:
        try:
            p = float(fill.get("price", 0) or 0)
            s = float(fill.get("size", 0) or 0)
        except (TypeError, ValueError):
            continue
        weighted_price += p * s
        total_size += s
    if total_size <= 0:
        return float(fills[0].get("price", 0) or 0), 0.0
    return weighted_price / total_size, total_size


def _safe_fills(fills: list[dict]) -> list[dict]:
    """Trim noisy keys from broker fills before they hit audit.log."""
    out: list[dict] = []
    for fill in fills[:25]:  # cap to keep audit payloads bounded
        out.append({
            "fill_id": fill.get("fill_id") or fill.get("id") or fill.get("trade_id"),
            "price": fill.get("price"),
            "size": fill.get("size"),
            "side": fill.get("side"),
        })
    return out
