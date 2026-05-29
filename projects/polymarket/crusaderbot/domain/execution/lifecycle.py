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

import datetime
import json
from decimal import Decimal
from typing import Any, Awaitable, Callable, Optional
from uuid import UUID

import structlog

from ... import audit as audit_module
from ... import notifications as notifications_module
from ...config import Settings, get_settings
from ...database import get_pool
from ...integrations.clob import (
    ClobAuthError,
    ClobClientProtocol,
    ClobConfigError,
    MarketDataClient,
    get_clob_client,
)
from ...wallet import ledger

log = structlog.get_logger(__name__)


# Status values tracked on the orders row. Kept in sync with
# domain/execution/live.py and migrations/015_order_lifecycle.sql.
STATUS_OPEN = ("submitted", "pending", "partial_filled")
STATUS_PARTIAL_FILLED = "partial_filled"
STATUS_FILLED = "filled"
STATUS_CANCELLED = "cancelled"
STATUS_EXPIRED = "expired"
STATUS_STALE = "stale"

# Seconds after submission before retrying at wider offset, then cancelling.
SLIPPAGE_RETRY_SECONDS = 30
SLIPPAGE_CANCEL_SECONDS = 60

# Polymarket's order detail returns ``size_matched`` (and other share
# counts) as fixed-math with 6 decimals — i.e. 125 shares is reported
# as the integer 125000000. Treating the raw value as a share count
# would over-state filled notional by 10^6×; we divide here so the
# refund / position-resize math gets actual shares. Codex P1 review.
BROKER_SIZE_DECIMALS = 6
BROKER_SIZE_FACTOR = 10 ** BROKER_SIZE_DECIMALS


class OrderLifecycleManager:
    """Polls live orders and dispatches terminal-state side effects."""

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
            # INTENTIONAL: operator-scoped, all-user access — system poller processes every
            # in-flight live order. Per-order mutations always re-verify user_id from the row.
            rows = await conn.fetch(
                """
                SELECT id, user_id, market_id, side, size_usdc, price,
                       polymarket_order_id, status, poll_attempts, mode,
                       fill_size, fill_price,
                       created_at, slippage_retry_count, filled_amount
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
                log.error("lifecycle poll: CLOB client unavailable", err=str(exc))
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
                    log.exception(
                        "lifecycle poll: order resolve failed",
                        order_id=str(order["id"]), err=str(exc),
                    )
                    continue
                outcome[resolution] = outcome.get(resolution, 0) + 1
        finally:
            if client is not None:
                try:
                    await client.aclose()
                except Exception as exc:  # noqa: BLE001
                    log.warning("lifecycle poll: client.aclose failed", err=str(exc))

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

        # --- paper-mode safety bail ------------------------------------
        # If USE_REAL_CLOB is False, we MUST NOT synthesise a fill.
        # mode='live' rows are only created by live.execute() when
        # USE_REAL_CLOB was True at order-creation time; if an operator
        # has since disabled the toggle while orders remain open at the
        # broker, falsely "filling" them in DB would update positions /
        # fills / wallets without any real broker confirmation.
        # Operator-driven reconciliation handles this state — we just
        # touch the row so observability stays current. Codex P1 review.
        if not settings.USE_REAL_CLOB:
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
        # Derive fills aggregate from the broker order detail itself.
        # /data/order/{id} returns ``size_matched`` (filled shares) +
        # ``price`` (limit). For GTC limit orders all matches happen
        # at the limit price, so a single aggregate row is enough for
        # refund math and position resize without an extra
        # /data/trades round trip on the (Codex-flagged) unsupported
        # ``taker_order_id`` filter.
        fills = _broker_fills(broker, order)

        if status == "filled":
            fill_price, fill_size = _aggregate_fills(fills, fallback=order)
            await self._on_fill(
                order=order, fill_price=fill_price, fill_size=fill_size,
                fills=fills, attempts=new_attempts,
            )
            return "filled"
        # Cancel + expiry MUST reconcile broker fills before refunding.
        # A GTC partial-fill that the broker later cancels reaches us
        # via status='cancelled' with size_matched > 0; without that
        # reconciliation the refund math credits the full size_usdc
        # while the user keeps the matched shares. Codex P1 (twice).
        if status in {"cancelled", "expired"}:
            handler = self._on_cancel if status == "cancelled" else self._on_expiry
            await handler(order=order, attempts=new_attempts, fills=fills)
            return status

        # Detect partial fill — broker still open but size_matched > 0.
        # Only transition and notify if filled_notional increased by > $0.01
        # since the last cycle to suppress duplicate Telegram alerts on
        # long-lived GTC orders that sit partially filled across many polls.
        if fills:
            avg_price, total_size = _aggregate_fills(fills, fallback={})
            if total_size > 0:
                filled_notional = Decimal(str(avg_price)) * Decimal(str(total_size))
                existing_filled = Decimal(str(order.get("filled_amount") or 0))
                if filled_notional > Decimal("0") and (
                    filled_notional - existing_filled > Decimal("0.01")
                ):
                    size_usdc = Decimal(str(order["size_usdc"]))
                    await self._on_partial_fill(
                        order=order,
                        filled_notional=filled_notional,
                        size_usdc=size_usdc,
                        attempts=new_attempts,
                    )
                    return "partial_filled"

        # Aggressive-limit timeout: if the order has been open without any fill
        # for SLIPPAGE_RETRY_SECONDS, re-submit at a wider offset. If still open
        # after SLIPPAGE_CANCEL_SECONDS, cancel and notify the user.
        # Only applies to submitted/pending orders (not partial fills) with a live client.
        if client is not None and order["status"] != STATUS_PARTIAL_FILLED:
            created_at = order.get("created_at")
            if created_at is not None:
                now_utc = datetime.datetime.now(datetime.timezone.utc)
                # asyncpg returns timezone-aware datetimes; ensure comparison is safe.
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=datetime.timezone.utc)
                elapsed = (now_utc - created_at).total_seconds()
                retry_count = int(order.get("slippage_retry_count") or 0)
                if retry_count >= 1 and elapsed > SLIPPAGE_CANCEL_SECONDS:
                    await self._on_slippage_cancel(
                        order=order, attempts=new_attempts, client=client,
                    )
                    return "cancelled"
                if retry_count == 0 and elapsed > SLIPPAGE_RETRY_SECONDS:
                    await self._on_slippage_retry(
                        order=order, attempts=new_attempts, client=client,
                    )
                    return "open"

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
        size_usdc = Decimal(str(order["size_usdc"]))
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
                           last_polled_at = NOW(),
                           filled_amount = $7,
                           remaining_amount = 0
                     WHERE id = $1
                       AND status = ANY($6::text[])
                     RETURNING id
                    """,
                    order["id"], STATUS_FILLED,
                    fill_price, fill_size, attempts, list(STATUS_OPEN),
                    float(size_usdc),
                )
                if updated is None:
                    # Already terminal — another poll cycle won the race.
                    log.info(
                        "lifecycle on_fill: order already terminal, skipping",
                        order_id=str(order["id"]),
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

        submitted_price = float(order.get("price") or 0)
        slippage_delta = round(fill_price - submitted_price, 6) if submitted_price else None
        await self._safe_audit(
            actor_role="bot", action="order_filled",
            user_id=order["user_id"],
            payload={
                "order_id": str(order["id"]),
                "market_id": order["market_id"],
                "side": order["side"],
                "fill_price": float(fill_price),
                "fill_size": float(fill_size),
                "submitted_price": submitted_price,
                "slippage_delta": slippage_delta,
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

    async def _on_partial_fill(
        self,
        *,
        order: dict,
        filled_notional: Decimal,
        size_usdc: Decimal,
        attempts: int,
    ) -> None:
        """Record a partial fill on an open GTC order.

        Transitions order status to ``partial_filled`` and updates
        ``filled_amount`` / ``remaining_amount``. The polling loop
        continues to process this order because STATUS_OPEN includes
        ``partial_filled``. On full fill or cancel the normal
        ``_on_fill`` / ``_terminal_close`` paths take over.
        """
        remaining = max(size_usdc - filled_notional, Decimal("0"))
        pool = self._pool_override or get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE orders
                   SET status           = $2,
                       filled_amount    = $3,
                       remaining_amount = $4,
                       poll_attempts    = $5,
                       last_polled_at   = NOW()
                 WHERE id = $1
                   AND status = ANY($6::text[])
                """,
                order["id"], STATUS_PARTIAL_FILLED,
                float(filled_notional), float(remaining), attempts,
                list(STATUS_OPEN),
            )
        await self._safe_audit(
            actor_role="bot", action="order_partial_filled",
            user_id=order["user_id"],
            payload={
                "order_id": str(order["id"]),
                "market_id": order["market_id"],
                "filled_amount": float(filled_notional),
                "remaining_amount": float(remaining),
                "size_usdc": float(size_usdc),
            },
        )
        await self._safe_notify_user(
            user_id=order["user_id"],
            text=(
                "⚠️ <b>Order Partially Filled</b>\n"
                f"Filled <code>${float(filled_notional):.2f}</code> of "
                f"<code>${float(size_usdc):.2f}</code>\n"
                f"Market <code>{order['market_id']}</code>\n"
                f"Remaining: <code>${float(remaining):.2f}</code> open"
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
                   fill_size = COALESCE($6, fill_size),
                   filled_amount = COALESCE($7, filled_amount),
                   remaining_amount = $8
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
                    float(filled_notional) if partial_fill else None,
                    0.0,
                )
                if updated is None:
                    log.info(
                        "lifecycle: order already terminal",
                        audit_action=audit_action, order_id=str(order["id"]),
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

    async def _on_slippage_retry(
        self,
        *,
        order: dict,
        attempts: int,
        client: ClobClientProtocol,
    ) -> None:
        """Cancel unfilled CLOB order and re-submit at +1 tick wider offset.

        Called when a submitted GTC order has been open for > SLIPPAGE_RETRY_SECONDS
        without any fill. Cancels the stale CLOB order, shifts the limit price
        one tick in the aggressive direction, and re-submits. Sets
        slippage_retry_count=1 so the next timeout triggers _on_slippage_cancel.
        """
        s = self._settings or get_settings()
        pool = self._pool_override or get_pool()
        if not s.ENABLE_LIVE_TRADING:
            # Skip broker calls. Still advance counter so order progresses to stale.
            await pool.execute(
                "UPDATE orders SET slippage_retry_count=1, poll_attempts=poll_attempts+1,"
                " last_polled_at=NOW() WHERE id=$1",
                order["id"],
            )
            log.info(
                "lifecycle slippage_retry deferred: gate inactive, counter advanced",
                order_id=str(order["id"]),
            )
            return
        broker_id = str(order.get("polymarket_order_id") or "")
        if broker_id:
            try:
                await client.cancel_order(broker_id)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "lifecycle slippage_retry: cancel failed",
                    order_id=str(order["id"]), broker=broker_id, err=str(exc),
                )

        # Widen by one extra tick in the aggressive direction.
        # token_id must be resolved first so we can fetch the real tick_size.
        original_price = float(order.get("price") or 0)
        side = str(order.get("side") or "yes").lower()
        async with pool.acquire() as conn:
            mkt = await conn.fetchrow(
                "SELECT yes_token_id, no_token_id FROM markets WHERE id=$1",
                order["market_id"],
            )
        if mkt is None:
            log.error(
                "lifecycle slippage_retry: market not found — cannot re-submit",
                market_id=order["market_id"], order_id=str(order["id"]),
            )
            return

        token_id = (
            mkt["yes_token_id"] if side in {"yes", "buy"} else mkt["no_token_id"]
        )
        if not token_id:
            log.error(
                "lifecycle slippage_retry: missing token_id",
                order_id=str(order["id"]), side=side,
            )
            return

        _tick_size: str = "0.01"
        _neg_risk: bool = False
        try:
            async with MarketDataClient() as _mdc:
                _tick_size = await _mdc.get_tick_size(token_id) or "0.01"
                _neg_risk = await _mdc.get_neg_risk(token_id)
        except Exception as _exc:
            log.warning(
                "lifecycle slippage_retry: CLOB tick_size/neg_risk fetch failed — using defaults",
                order_id=str(order["id"]), token_id=token_id, err=str(_exc),
            )

        tick_size_f = float(_tick_size)
        if side in {"yes", "buy"}:
            new_limit = round(min(0.99, original_price + tick_size_f), 4)
        else:
            new_limit = round(max(0.01, original_price - tick_size_f), 4)
        shares = float(order["size_usdc"]) / max(new_limit, 0.0001)

        new_broker_id = ""
        try:
            result = await client.post_order(
                token_id=token_id,
                side="BUY" if side in {"yes", "buy"} else "SELL",
                price=new_limit,
                size=shares,
                order_type="GTC",
                tick_size=_tick_size,
                neg_risk=_neg_risk,
            )
            new_broker_id = (
                result.get("orderID") or result.get("order_id") or result.get("id") or ""
            )
        except Exception as exc:  # noqa: BLE001
            log.error(
                "lifecycle slippage_retry: re-submit failed",
                order_id=str(order["id"]), err=str(exc),
            )
            return

        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE orders
                   SET polymarket_order_id = $2,
                       price               = $3,
                       slippage_retry_count = 1,
                       poll_attempts        = $4,
                       last_polled_at       = NOW()
                 WHERE id = $1
                """,
                order["id"], str(new_broker_id), new_limit, attempts,
            )
        await self._safe_audit(
            actor_role="bot", action="order_slippage_retry",
            user_id=order["user_id"],
            payload={
                "order_id": str(order["id"]),
                "market_id": order["market_id"],
                "original_price": original_price,
                "new_limit_price": new_limit,
                "old_broker_id": broker_id,
                "new_broker_id": new_broker_id,
            },
        )
        log.info(
            "lifecycle slippage_retry: order re-submitted",
            order_id=str(order["id"]), new_limit=new_limit,
            was=original_price, broker=new_broker_id,
        )

    async def _on_slippage_cancel(
        self,
        *,
        order: dict,
        attempts: int,
        client: ClobClientProtocol,
    ) -> None:
        """Cancel a GTC order that has not filled after SLIPPAGE_CANCEL_SECONDS.

        Called after one retry at wider offset still did not produce a fill.
        Cancels the live CLOB order and routes through _terminal_close so the
        user gets a standard cancellation notification with any partial-fill
        refund math applied.
        """
        broker_id = str(order.get("polymarket_order_id") or "")
        if broker_id:
            try:
                await client.cancel_order(broker_id)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "lifecycle slippage_cancel: cancel failed",
                    order_id=str(order["id"]), broker=broker_id, err=str(exc),
                )

        await self._safe_audit(
            actor_role="bot", action="order_slippage_timeout_cancel",
            user_id=order["user_id"],
            payload={
                "order_id": str(order["id"]),
                "market_id": order["market_id"],
                "broker_id": broker_id,
                "reason": "no fill after slippage retry window",
            },
        )
        await self._on_cancel(order=order, attempts=attempts, fills=[])

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
            log.error("lifecycle stale notify failed", err=str(exc))

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
        """Write per-fill rows; safe to re-run via ON CONFLICT (fill_id).

        When the supplied fills are all synthetic ``agg-`` aggregates
        produced by ``_broker_fills`` (the order_update / polling
        terminal paths), compare the incoming aggregate size against
        the sum of per-trade rows already on disk:

          * per-trade total >= aggregate total — WS captured every
            settled share already, the aggregate is redundant, skip
            the insert (one-row-per-broker-fill contract; Codex P2).
          * per-trade total <  aggregate total — WS missed some trade
            frames (disconnect/parser drop/broker gap); insert the
            aggregate so the fills table eventually agrees with
            ``orders.fill_size``. Reporting must dedup the overlap;
            without this branch the missed shares would be undercounted
            (Codex P2 round 8 on PR #915).
          * no per-trade rows — polling-only path; insert as before.
        """
        if (
            fills
            and all(
                str(f.get("fill_id", "") or "").startswith("agg-")
                for f in fills
            )
        ):
            existing_total = await conn.fetchval(
                "SELECT COALESCE(SUM(size), 0) FROM fills "
                "WHERE order_id = $1 AND fill_id NOT LIKE 'agg-%'",
                order_id,
            )
            existing_total = float(existing_total or 0)
            incoming_total = sum(
                float(f.get("size", 0) or 0) for f in fills
            )
            # Tiny epsilon absorbs float-roundtrip noise from
            # NUMERIC(18,6) columns. Real reconciliation gaps are
            # always whole-share discrepancies, well outside this band.
            EPSILON = 1e-6
            if existing_total + EPSILON >= incoming_total:
                log.debug(
                    "lifecycle: skipping aggregate fills insert; per-trade sum covers incoming aggregate",
                    per_trade_sum=existing_total, incoming=incoming_total,
                    order_id=str(order_id),
                )
                return

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
                log.warning(
                    "lifecycle: dropping fill with non-numeric price/size",
                    fill=fill,
                )
                continue
            # ON CONFLICT DO UPDATE so synthetic ``agg-*`` rows
            # tracking a growing broker aggregate (open UPDATE frames
            # with size_matched climbing toward original_size) reflect
            # the LATEST matched amount rather than the first one we
            # observed. Per-trade fill_ids are unique per match so the
            # UPSERT is a no-op for duplicate trade frames; agg rows
            # benefit from the size/price refresh. Codex P1 round 10.
            await conn.execute(
                """
                INSERT INTO fills (order_id, fill_id, price, size, side, raw)
                VALUES ($1,$2,$3,$4,$5,$6)
                ON CONFLICT (fill_id) DO UPDATE SET
                    size = EXCLUDED.size,
                    price = EXCLUDED.price
                """,
                order_id, fill_id, price, size,
                str(fill.get("side") or side).lower(),
                json.dumps(fill, default=str),
            )

    # ----- safe wrappers ----------------------------------------------

    # ----- WebSocket event handlers (Phase 4D) -------------------------
    # These are the single points the ``ClobWebSocketClient`` calls into.
    # They look up the in-flight order row by broker id, then reuse the
    # exact same ``_on_fill`` / ``_on_cancel`` / ``_on_expiry`` /
    # ``_touch`` paths the polling loop uses. Dedup with polling is
    # provided by two existing constraints:
    #   * ``UPDATE orders ... WHERE status = ANY(STATUS_OPEN) RETURNING id``
    #     — the second writer (poll OR ws) sees ``None`` and bails.
    #   * ``INSERT INTO fills ... ON CONFLICT (fill_id) DO NOTHING`` —
    #     the second writer's per-fill row is silently dropped.
    # No new dedup table or in-memory set is needed.

    async def handle_ws_fill(self, event: dict) -> None:
        """Record one CONFIRMED ``user_fill`` event without terminalising.

        ``event`` is the normalised dict ``ws_handler.parse_message``
        produces: ``{kind, broker_order_id, fill_id, price, size,
        side, raw}``. The handler is intentionally records-only:

          * INSERT INTO ``fills`` (idempotent via the unique fill_id
            constraint).
          * UPDATE ``positions.current_price`` so dashboards reflect
            the latest mark.

        It does NOT mark the order as filled. Polymarket's user channel
        emits one ``trade`` frame per match — a multi-trade GTC fill
        produces N events that each represent a partial settlement, so
        terminalising on the first one would lose every subsequent
        ``fills`` row (the second writer would race-lose against
        ``UPDATE orders ... RETURNING id``). Order termination comes
        from ``handle_ws_order_update(status=filled)`` or the polling
        fallback once the broker reports the order fully matched.
        Codex P1 round 1 / WARP🔹CMD ratification on PR #915.

        User notifications + audit are also intentionally deferred to
        the terminal path so a partial fill does not produce a
        misleading "Order filled" Telegram message.
        """
        broker_id = event.get("broker_order_id")
        fill_id = event.get("fill_id")
        if not broker_id or not fill_id:
            log.debug(
                "lifecycle ws_fill: dropping event missing ids", payload=event,
            )
            return

        order_row = await self._lookup_order_by_broker_id(broker_id)
        if order_row is None:
            log.info(
                "lifecycle ws_fill: no local order matches broker_id",
                broker_id=broker_id,
            )
            return
        if order_row["status"] not in STATUS_OPEN:
            log.debug(
                "lifecycle ws_fill: order already terminal",
                order_id=str(order_row["id"]), status=order_row["status"],
            )
            return

        try:
            price = float(event["price"])
            size = float(event["size"])
        except (TypeError, ValueError, KeyError) as exc:
            log.warning(
                "lifecycle ws_fill: dropping non-numeric event",
                payload=event, err=str(exc),
            )
            return
        side = str(event.get("side") or order_row["side"]).lower()
        fills_payload = [{
            "fill_id": str(fill_id),
            "price": price,
            "size": size,
            "side": side,
            "raw": event.get("raw"),
        }]

        pool = self._pool_override or get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await self._record_fills_in_conn(
                    conn=conn, order_id=order_row["id"],
                    side=order_row["side"], fills=fills_payload,
                )
                # Refresh the open position's mark price so the
                # dashboard moves with each WS fill even before
                # terminal close. Harmless when no position row
                # exists yet (UPDATE matches zero rows).
                await conn.execute(
                    """
                    UPDATE positions
                       SET current_price = $2
                     WHERE order_id = $1
                       AND status = 'open'
                    """,
                    order_row["id"], price,
                )

    async def handle_ws_order_update(self, event: dict) -> None:
        """Apply one ``user_order`` status transition event.

        Dispatches on the normalised status: ``filled`` reuses the
        broker-payload fills aggregate via ``_broker_fills``;
        ``cancelled`` / ``expired`` route through the existing
        ``_terminal_close`` helper so partial-fill refund math stays
        in one place.
        """
        broker_id = event.get("broker_order_id")
        status = event.get("status")
        if not broker_id or not status:
            return

        order_row = await self._lookup_order_by_broker_id(broker_id)
        if order_row is None:
            return
        if order_row["status"] not in STATUS_OPEN:
            return

        order = dict(order_row)
        attempts = int(order.get("poll_attempts") or 0) + 1
        # Build a synthetic broker payload so ``_broker_fills`` can
        # reuse its size_matched / price interpretation rules. For a
        # status-only update with no size_matched the helper returns
        # an empty list and the cancel/expiry refund path correctly
        # treats it as zero-fill. For a filled status update we forward
        # the size_matched + price from the WS frame.
        size_matched = event.get("size_matched")
        broker_payload = {
            "status": status,
            "size_matched": (
                size_matched * 10 ** 6 if size_matched is not None else 0
            ),
            "price": event.get("price") or order.get("price"),
        }
        fills = _broker_fills(broker_payload, order)

        if status == "filled":
            fill_price, fill_size = _aggregate_fills(fills, fallback=order)
            await self._on_fill(
                order=order, fill_price=fill_price, fill_size=fill_size,
                fills=fills, attempts=attempts,
            )
            return
        if status in {"cancelled", "expired"}:
            # Cancel/expiry refund math depends on the matched-shares
            # aggregate. The broker's user_order frame may omit
            # size_matched (the operator-cancel path commonly does),
            # in which case _broker_fills returned []. Hydrating from
            # the per-trade rows handle_ws_fill already wrote ensures
            # _terminal_close refunds only the UNFILLED remainder
            # rather than the full notional. Without this, a WS-fill
            # for $40 followed by a WS-cancel-with-no-size_matched on
            # a $100 order would refund the full $100 even though the
            # user already owns the $40 of matched shares. Codex P1
            # review on PR #915.
            if not fills:
                fills = await self._load_existing_fills(order["id"])
            handler = (
                self._on_cancel if status == "cancelled"
                else self._on_expiry
            )
            await handler(order=order, attempts=attempts, fills=fills)
            return
        # status == "open" (partial UPDATE or informational frame).
        # When the broker UPDATE carries size_matched > 0 (a partial
        # match), persist the aggregate now so a later cancellation
        # that omits size_matched can hydrate the matched shares from
        # the DB via _load_existing_fills. Without this, the cancel
        # path would refund the full order notional even though shares
        # were already matched. Subsequent UPDATEs with grown
        # size_matched UPSERT the agg row to the latest amount via
        # _record_fills_in_conn's ON CONFLICT DO UPDATE clause.
        # Codex P1 round 10 on PR #915.
        if fills:
            pool = self._pool_override or get_pool()
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await self._record_fills_in_conn(
                        conn=conn, order_id=order["id"],
                        side=order["side"], fills=fills,
                    )

    async def _load_existing_fills(self, order_id: UUID) -> list[dict]:
        """Pull existing ``fills`` rows used for hydration on cancel/expiry.

        Returns whichever of the per-trade-row set or the synthetic
        ``agg-*`` aggregate covers a LARGER matched-shares total.
        Tie-breaks (per-trade SUM == agg size) go to per-trade for
        granularity. The size comparison matters because:

          * per-trade SUM == agg total — WS captured every settled
            share. Per-trade rows are the most granular record so
            prefer them.
          * per-trade SUM <  agg total — WS missed some trade frames
            (disconnect / parser drop / broker gap). The agg row's
            size is the broker's authoritative aggregate; using the
            per-trade SUM would refund the user for shares they
            actually own. Codex P1 round 11 on PR #915.
          * no per-trade rows — return agg if any (round 10 path).
          * no rows at all — return ``[]`` so ``_terminal_close``
            treats it as zero-fill and refunds the full notional.
        """
        pool = self._pool_override or get_pool()
        async with pool.acquire() as conn:
            per_trade = await conn.fetch(
                "SELECT fill_id, price, size, side FROM fills "
                "WHERE order_id = $1 AND fill_id NOT LIKE 'agg-%'",
                order_id,
            )
            agg = await conn.fetch(
                "SELECT fill_id, price, size, side FROM fills "
                "WHERE order_id = $1 AND fill_id LIKE 'agg-%'",
                order_id,
            )
        per_trade_total = sum(float(r["size"] or 0) for r in per_trade)
        agg_total = sum(float(r["size"] or 0) for r in agg)
        # 1e-6 epsilon absorbs NUMERIC roundtrip noise on equal sums.
        if per_trade and per_trade_total + 1e-6 >= agg_total:
            return [dict(r) for r in per_trade]
        if agg:
            return [dict(r) for r in agg]
        return [dict(r) for r in per_trade]

    async def _lookup_order_by_broker_id(
        self, broker_order_id: str,
    ) -> Optional[Any]:
        """Resolve ``orders.polymarket_order_id`` -> the full order row.

        Returns ``None`` for unknown broker ids (fills on orders placed
        outside the bot) or rows already in a terminal state. The
        SELECT mirrors ``poll_once`` so dispatchers consume the same
        column shape.
        """
        pool = self._pool_override or get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, user_id, market_id, side, size_usdc, price,
                       polymarket_order_id, status, poll_attempts, mode,
                       fill_size, fill_price
                  FROM orders
                 WHERE polymarket_order_id = $1
                   AND mode = 'live'
                """,
                broker_order_id,
            )
        return row

    async def _safe_audit(self, **kwargs: Any) -> None:
        try:
            await self._audit_write(**kwargs)
        except Exception as exc:  # noqa: BLE001
            log.error("lifecycle audit write failed", err=str(exc))

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
            log.error("lifecycle user notify failed", err=str(exc))


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


async def dispatch_ws_fill(event: dict) -> None:
    """Module-level shim used as the WebSocket client's fill callback."""
    await get_default_manager().handle_ws_fill(event)


async def dispatch_ws_order_update(event: dict) -> None:
    """Module-level shim used as the WebSocket client's order callback."""
    await get_default_manager().handle_ws_order_update(event)


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
    # Prefix-match so terminal-cancel variants such as
    # ``ORDER_STATUS_CANCELED_MARKET_RESOLVED`` (a real Polymarket enum
    # documented at /api-reference/trade/get-single-order-by-id) route
    # to the cancel path instead of falling through to ``open`` and
    # eventually being marked stale. Codex P1 review.
    if raw.startswith("cancel"):
        return "cancelled"
    if raw == "expired":
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


def _broker_fills(broker_payload: dict, order: dict) -> list[dict]:
    """Build a fills aggregate from the broker order detail.

    Polymarket's ``/data/order/{id}`` returns ``size_matched`` (filled
    shares) and ``price`` (limit price). For GTC limit orders all
    matches land at the limit price, so a single synthetic aggregate
    row is functionally equivalent to enumerating per-trade fills for
    the refund / resize math the lifecycle needs — and avoids the
    ``/data/trades`` endpoint whose ``taker_order_id`` filter is not
    supported by the CLOB (Codex P1 review).

    Returns an empty list when ``size_matched`` is zero or missing.
    """
    raw_size = (
        broker_payload.get("size_matched")
        or broker_payload.get("sizeMatched")
        or broker_payload.get("filled_size")
        or 0
    )
    try:
        # Polymarket ``size_matched`` is fixed-math with 6 decimals
        # (per docs.polymarket.com /api-reference/trade/get-single-
        # order-by-id). Convert to actual shares before refund math.
        matched_size = float(raw_size or 0) / BROKER_SIZE_FACTOR
    except (TypeError, ValueError):
        matched_size = 0.0
    if matched_size <= 0:
        return []
    raw_price = (
        broker_payload.get("price")
        or broker_payload.get("match_price")
        or order.get("price")
        or 0
    )
    try:
        matched_price = float(raw_price or 0)
    except (TypeError, ValueError):
        matched_price = float(order.get("price", 0) or 0)
    broker_id = (
        broker_payload.get("id")
        or broker_payload.get("orderID")
        or broker_payload.get("order_id")
        or order.get("polymarket_order_id")
        or ""
    )
    return [{
        "fill_id": f"agg-{broker_id}",
        "price": matched_price,
        "size": matched_size,
        "side": order["side"],
    }]


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
