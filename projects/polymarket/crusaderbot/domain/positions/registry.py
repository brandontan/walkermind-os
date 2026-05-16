"""Position registry — the only sanctioned read/write surface for position
state used by the exit watcher and the close pipeline.

Contract (R12c):
  * applied_tp_pct / applied_sl_pct are SNAPSHOTS taken at entry and are
    immutable after INSERT. There is no public function in this module that
    accepts an ``applied_*`` argument on update — the DB trigger added in
    migration 005 enforces the same rule at the storage layer so a buggy
    code path elsewhere cannot quietly mutate the snapshot.
  * User edits to user_settings.tp_pct / user_settings.sl_pct must NEVER
    propagate to open positions. The registry is the boundary that makes
    that promise: callers that load a position go through ``list_open_for_exit``
    and read ``applied_tp_pct`` / ``applied_sl_pct`` directly.
  * ``force_close_intent`` is a per-position marker set by the Telegram
    emergency flow. The watcher consumes it on the next tick.
  * ``close_failure_count`` tracks consecutive close failures. The exit
    watcher increments it via ``record_close_failure`` after a CLOB error +
    one retry, and resets it on any successful close.
"""
from __future__ import annotations

import enum
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional, Union
from uuid import UUID

from ...database import get_pool

logger = logging.getLogger(__name__)


class ExitReason(str, enum.Enum):
    """Allowed values for ``positions.exit_reason``.

    The string form is what is persisted; the enum exists so the watcher and
    alert paths share a single source of truth and the ``str`` subclass keeps
    the value usable directly in SQL parameter binds without ``.value``.
    """

    MANUAL = "manual"
    TP_HIT = "tp_hit"
    SL_HIT = "sl_hit"
    STRATEGY_EXIT = "strategy_exit"
    RESOLUTION = "resolution"
    FORCE_CLOSE = "force_close"
    CLOSE_FAILED = "close_failed"
    MARKET_EXPIRED = "market_expired"


# Reasons emitted by the exit watcher (resolution settles via the redeem
# pipeline, manual close runs from the dashboard handler — those reasons are
# valid persisted values but never produced by the watcher itself).
WATCHER_EXIT_REASONS: frozenset[str] = frozenset({
    ExitReason.TP_HIT.value,
    ExitReason.SL_HIT.value,
    ExitReason.STRATEGY_EXIT.value,
    ExitReason.FORCE_CLOSE.value,
    ExitReason.MARKET_EXPIRED.value,
})


@dataclass(frozen=True)
class OpenPositionForExit:
    """Read-only snapshot of an open position the exit watcher needs.

    Frozen so a stale dict mutation in one watcher tick can never bleed into
    the next tick. The watcher receives a fresh batch from
    ``list_open_for_exit`` on every iteration.
    """

    id: UUID
    user_id: UUID
    telegram_user_id: int
    market_id: str
    market_question: Optional[str]
    side: str
    entry_price: float
    size_usdc: float
    mode: str
    status: str
    applied_tp_pct: Optional[float]
    applied_sl_pct: Optional[float]
    force_close_intent: bool
    close_failure_count: int
    yes_price: Optional[float]
    no_price: Optional[float]
    market_resolved: bool

    def to_router_dict(self) -> dict[str, Any]:
        """Build the payload shape ``router.close`` expects.

        Router code accepts a plain dict (it predates this dataclass) so we
        translate at the boundary rather than refactor the router.
        """
        return {
            "id": self.id,
            "user_id": self.user_id,
            "market_id": self.market_id,
            "side": self.side,
            "entry_price": self.entry_price,
            "size_usdc": self.size_usdc,
            "mode": self.mode,
            "status": self.status,
        }

    def current_price(self) -> float:
        """Current market price for this position's side, falling back to
        ``entry_price`` when the market book has not yet synced. Falling back
        to entry intentionally yields ret_pct == 0 so neither TP nor SL trip
        on stale data — the watcher waits for the next market sync instead.
        """
        if self.side == "yes" and self.yes_price is not None:
            return float(self.yes_price)
        if self.side == "no" and self.no_price is not None:
            return float(self.no_price)
        return float(self.entry_price)


async def list_open_for_exit() -> list[OpenPositionForExit]:
    """Fetch every open position joined with its market + telegram user.

    Resolved markets are EXCLUDED — they settle through the redemption
    pipeline (terminal value 1 / 0 USDC per share), not through a CLOB
    re-quote. The watcher never tries to close them.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT p.id, p.user_id, p.market_id, p.side,
                   p.entry_price, p.size_usdc, p.mode, p.status,
                   p.applied_tp_pct, p.applied_sl_pct,
                   p.force_close_intent, p.close_failure_count,
                   m.question AS market_question,
                   m.yes_price, m.no_price, m.resolved AS market_resolved,
                   u.telegram_user_id
              FROM positions p
              JOIN markets m ON m.id = p.market_id
              JOIN users u ON u.id = p.user_id
             WHERE p.status = 'open'
               AND m.resolved = FALSE
            """
        )
    return [
        OpenPositionForExit(
            id=r["id"],
            user_id=r["user_id"],
            telegram_user_id=int(r["telegram_user_id"]),
            market_id=r["market_id"],
            market_question=r["market_question"],
            side=r["side"],
            entry_price=float(r["entry_price"]),
            size_usdc=float(r["size_usdc"]),
            mode=r["mode"],
            status=r["status"],
            applied_tp_pct=(float(r["applied_tp_pct"])
                            if r["applied_tp_pct"] is not None else None),
            applied_sl_pct=(float(r["applied_sl_pct"])
                            if r["applied_sl_pct"] is not None else None),
            force_close_intent=bool(r["force_close_intent"]),
            close_failure_count=int(r["close_failure_count"] or 0),
            yes_price=(float(r["yes_price"])
                       if r["yes_price"] is not None else None),
            no_price=(float(r["no_price"])
                      if r["no_price"] is not None else None),
            market_resolved=bool(r["market_resolved"]),
        )
        for r in rows
    ]


async def list_open_on_resolved_markets() -> list[OpenPositionForExit]:
    """Open positions whose market has been marked resolved in the local DB.

    ``list_open_for_exit`` excludes these (``AND m.resolved = FALSE``), so they
    never reach the TP/SL evaluation loop. Without this query they permanently
    occupy concurrent-trade slots because Gamma returns no live price for a
    resolved market. The exit watcher calls this in Phase B to close them
    as MARKET_EXPIRED and credit the wallet.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT p.id, p.user_id, p.market_id, p.side,
                   p.entry_price, p.size_usdc, p.mode, p.status,
                   p.applied_tp_pct, p.applied_sl_pct,
                   p.force_close_intent, p.close_failure_count,
                   m.question AS market_question,
                   m.yes_price, m.no_price, m.resolved AS market_resolved,
                   u.telegram_user_id
              FROM positions p
              JOIN markets m ON m.id = p.market_id
              JOIN users u ON u.id = p.user_id
             WHERE p.status = 'open'
               AND m.resolved = TRUE
            """
        )
    return [
        OpenPositionForExit(
            id=r["id"],
            user_id=r["user_id"],
            telegram_user_id=int(r["telegram_user_id"]),
            market_id=r["market_id"],
            market_question=r["market_question"],
            side=r["side"],
            entry_price=float(r["entry_price"]),
            size_usdc=float(r["size_usdc"]),
            mode=r["mode"],
            status=r["status"],
            applied_tp_pct=(float(r["applied_tp_pct"])
                            if r["applied_tp_pct"] is not None else None),
            applied_sl_pct=(float(r["applied_sl_pct"])
                            if r["applied_sl_pct"] is not None else None),
            force_close_intent=bool(r["force_close_intent"]),
            close_failure_count=int(r["close_failure_count"] or 0),
            yes_price=(float(r["yes_price"])
                       if r["yes_price"] is not None else None),
            no_price=(float(r["no_price"])
                      if r["no_price"] is not None else None),
            market_resolved=bool(r["market_resolved"]),
        )
        for r in rows
    ]


async def close_as_expired(
    position_id: UUID,
    user_id: UUID,
    size_usdc: float,
) -> bool:
    """Atomically close an open position because its market is no longer live.

    Three-statement transaction:
      1. UPDATE positions → status='closed', exit_reason='market_expired',
         pnl_usdc=0.0, closed_at=NOW()  (WHERE status='open' guards idempotency)
      2. UPDATE wallets   → balance_usdc += size_usdc  (return original stake)
      3. INSERT ledger    → type='trade_close', amount=size_usdc

    Returns True iff the position was transitioned. Returns False when the
    position is no longer 'open' (already closed by another path), making
    this safe to call multiple times across consecutive watcher ticks.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            updated = await conn.fetchval(
                """
                UPDATE positions
                   SET status = 'closed',
                       exit_reason = $2,
                       pnl_usdc = 0.0,
                       closed_at = NOW()
                 WHERE id = $1 AND status = 'open' AND user_id = $3
                 RETURNING id
                """,
                position_id, ExitReason.MARKET_EXPIRED.value, user_id,
            )
            if updated is None:
                return False
            size = Decimal(str(size_usdc))
            await conn.execute(
                "UPDATE wallets "
                "   SET balance_usdc = balance_usdc + $1 "
                " WHERE user_id = $2",
                size, user_id,
            )
            await conn.execute(
                "INSERT INTO ledger (user_id, type, amount_usdc, ref_id, note) "
                "VALUES ($1, 'trade_close', $2, $3, 'market expired — capital returned')",
                user_id, size, position_id,
            )
    return True


async def mark_force_close_intent_for_user(user_id: UUID) -> int:
    """Set ``force_close_intent = TRUE`` on every open position for a user.

    Returns the number of rows actually flipped (idempotent — already-set
    rows are not double-counted). Used by the Telegram emergency
    pause+close-all flow.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        marked = await conn.fetchval(
            "WITH upd AS ( "
            "  UPDATE positions SET force_close_intent = TRUE "
            "   WHERE user_id = $1 AND status = 'open' "
            "     AND force_close_intent = FALSE "
            "   RETURNING 1 "
            ") SELECT COUNT(*) FROM upd",
            user_id,
        )
    return int(marked or 0)


async def update_current_price(
    position_id: UUID,
    price: float,
    user_id: UUID,
    pnl_usdc: Optional[float] = None,
) -> None:
    """Refresh ``current_price`` (and optionally ``pnl_usdc``) on a held position.

    The watcher calls this every tick on positions that did not breach TP or
    SL, so the dashboard reflects mark-to-market without waiting for a close.
    ``pnl_usdc`` is the unrealised P&L computed from the live price; passing
    None leaves the existing column value intact (backward-compatible with any
    caller that does not supply it).
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        if pnl_usdc is not None:
            await conn.execute(
                "UPDATE positions "
                "   SET current_price = $1, pnl_usdc = $2 "
                " WHERE id = $3 AND user_id = $4",
                price, pnl_usdc, position_id, user_id,
            )
        else:
            await conn.execute(
                "UPDATE positions SET current_price = $1 "
                "WHERE id = $2 AND user_id = $3",
                price, position_id, user_id,
            )


async def record_close_failure(position_id: UUID, user_id: UUID) -> int:
    """Increment ``close_failure_count`` and return the new value.

    Called after a CLOB submit error + the single in-tick retry both fail.
    The watcher uses the returned counter to decide when to flip the
    position into a terminal CLOSE_FAILED state and page the operator.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        new_count = await conn.fetchval(
            "UPDATE positions "
            "   SET close_failure_count = close_failure_count + 1 "
            " WHERE id = $1 AND user_id = $2 "
            " RETURNING close_failure_count",
            position_id, user_id,
        )
    return int(new_count or 0)


async def reset_close_failure(position_id: UUID, user_id: UUID) -> None:
    """Zero ``close_failure_count`` after a successful close attempt."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE positions SET close_failure_count = 0 WHERE id = $1 AND user_id = $2",
            position_id, user_id,
        )


async def finalize_close_failed(position_id: UUID, user_id: UUID, error_msg: str) -> bool:
    """Flip a position to ``status = 'close_failed'`` and stamp exit_reason.

    Used when consecutive close failures cross the operator-alert threshold
    AND the operator has explicitly opted into terminal-state finalization.
    The watcher itself does NOT auto-finalize — the position stays 'open'
    and continues to retry on subsequent ticks unless the operator runs the
    admin command that calls this. This keeps a transient broker outage
    from poisoning open exposure.

    Returns True iff the row transitioned (idempotent — already-finalized
    positions return False).
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        updated = await conn.fetchval(
            """
            UPDATE positions
               SET status = 'close_failed',
                   exit_reason = $2,
                   closed_at = NOW()
             WHERE id = $1 AND status = 'open' AND user_id = $3
             RETURNING id
            """,
            position_id, ExitReason.CLOSE_FAILED.value, user_id,
        )
    if updated is None:
        return False
    logger.error("position %s finalized as close_failed: %s",
                 position_id, error_msg[:300])
    return True
