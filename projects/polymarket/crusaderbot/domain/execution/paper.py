"""Paper execution engine — fully atomic open / close in a single DB transaction."""
from __future__ import annotations

import json
import logging
import structlog
from decimal import Decimal
from uuid import UUID

from ... import audit, notifications
from ...database import get_pool
from ...services import portfolio_snapshots
from ...services.trade_notifications import TradeNotifier
from ...wallet import ledger

_notifier = TradeNotifier()

logger = logging.getLogger(__name__)
log = structlog.get_logger(__name__)


async def execute(
    *,
    user_id: UUID,
    telegram_user_id: int,
    market_id: str,
    market_question: str | None,
    side: str,
    size_usdc: Decimal,
    price: float,
    idempotency_key: str,
    strategy_type: str,
    tp_pct: float | None,
    sl_pct: float | None,
    active_preset: str | None = None,
    strategy_metadata: dict | None = None,
) -> dict:
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO orders (user_id, market_id, side, size_usdc, price,
                                    mode, status, idempotency_key, strategy_type)
                VALUES ($1,$2,$3,$4,$5,'paper','filled',$6,$7)
                ON CONFLICT (idempotency_key) DO NOTHING
                RETURNING id
                """,
                user_id, market_id, side, size_usdc, price,
                idempotency_key, strategy_type,
            )
            if row is None:
                logger.info("paper.execute idempotent skip key=%s", idempotency_key)
                return {"status": "duplicate", "mode": "paper"}
            order_id = row["id"]
            pos_row = await conn.fetchrow(
                """
                INSERT INTO positions (user_id, market_id, order_id, side,
                                       size_usdc, entry_price, current_price,
                                       tp_pct, sl_pct, mode, status, strategy_type,
                                       market_question, active_preset,
                                       strategy_metadata)
                VALUES ($1,$2,$3,$4,$5,$6,$6,$7,$8,'paper','open',$9,$10,$11,
                        $12::jsonb)
                RETURNING id
                """,
                user_id, market_id, order_id, side,
                size_usdc, price, tp_pct, sl_pct, strategy_type,
                market_question, active_preset,
                json.dumps(strategy_metadata) if strategy_metadata else None,
            )
            position_id = pos_row["id"]
            await ledger.debit_in_conn(
                conn, user_id, size_usdc, ledger.T_TRADE_OPEN,
                ref_id=position_id, note=f"paper open {side} {market_id}",
            )

    log.info("paper_trade_open", user_id=str(user_id), market_id=market_id, rule=strategy_type, side=side, size_usdc=str(size_usdc), price=price)
    await audit.write(actor_role="bot", action="paper_open", user_id=user_id,
                      payload={
                          "order_id": str(order_id),
                          "position_id": str(position_id),
                          "market_id": market_id,
                          "side": side,
                          "size_usdc": str(size_usdc),
                          "price": price,
                          "strategy": strategy_type,
                      })

    # Entry-side mode-isolation guard (#1820, symmetric with the #1810 exit
    # guard). A paper position can be created for a user whose authoritative
    # mode is LIVE — most commonly when a live order is rejected pre-submit for
    # being below LIVE_MIN_ORDER_SHARES and the router falls back to paper. In
    # that state a "TRADE OPENED" notification (Telegram + web alert) plus the
    # downstream position.opened SSE event would surface an active trade the
    # user's LIVE WebTrader portfolio CANNOT see (it filters WHERE mode='live'),
    # so Telegram and WebTrader disagree on runtime truth. Resolve the committed
    # authoritative mode; on contamination, suppress the user-facing entry
    # notification + the open event and record a diagnostic. The paper position
    # itself is unchanged — it remains correct paper-mode accounting and shows
    # in paper mode; it just must not masquerade as an active live trade.
    open_event_suppressed = False
    try:
        from ..activation.live_mode import (
            get_active_trading_mode,
            paper_event_contaminates_live,
        )
        active_mode = await get_active_trading_mode(user_id)
        open_event_suppressed = paper_event_contaminates_live(
            event_mode="paper", active_mode=active_mode,
        )
    except Exception as exc:
        # Fail OPEN to existing behaviour: a transient mode-read failure must
        # never silently swallow a legitimate paper user's entry notification.
        log.warning("paper.execute active-mode read failed — emitting entry",
                    user_id=str(user_id), err=str(exc))
        active_mode = "paper"
        open_event_suppressed = False

    if open_event_suppressed:
        log.warning(
            "paper.execute: suppressing paper entry notification for now-LIVE "
            "user (paper fallback not visible in live portfolio)",
            worker="paper_engine", user_id=str(user_id),
            position_id=str(position_id), active_mode=active_mode,
            size_usdc=str(size_usdc),
        )
        await audit.write(
            actor_role="bot", action="paper_entry_suppressed_post_live",
            user_id=user_id,
            payload={"position_id": str(position_id),
                     "order_id": str(order_id),
                     "market_id": market_id,
                     "size_usdc": str(size_usdc),
                     "active_mode": active_mode},
        )
    else:
        await _notifier.notify_entry(
            telegram_user_id=telegram_user_id,
            market_id=market_id,
            market_question=market_question,
            side=side,
            size_usdc=size_usdc,
            price=price,
            tp_pct=tp_pct,
            sl_pct=sl_pct,
            mode="paper",
            strategy_type=strategy_type,
            position_id=str(position_id),
        )
    return {"order_id": order_id, "position_id": position_id, "mode": "paper",
            "open_event_suppressed": open_event_suppressed}


async def close_position(*, position: dict, exit_price: float,
                         exit_reason: str) -> dict:
    pool = get_pool()
    size = Decimal(str(position["size_usdc"]))
    entry = float(position["entry_price"])
    side = position["side"]
    # Side-own price frame: entry_price and exit_price are the position's OWN
    # outcome-token price, so the return on the bought token is (exit - entry)/entry
    # for BOTH sides (matches exit_watcher._return_pct). YES unchanged; corrected
    # NO frame — WARP/ROOT/no-side-pnl-frame.
    ret_pct = (exit_price - entry) / max(entry, 1e-6)
    pnl = size * Decimal(str(ret_pct))
    proceeds = size + pnl

    async with pool.acquire() as conn:
        async with conn.transaction():
            updated = await conn.fetchval(
                """
                UPDATE positions
                   SET status='closed', exit_reason=$2, current_price=$3,
                       pnl_usdc=$4, closed_at=NOW()
                 WHERE id=$1 AND status='open' AND user_id=$5
                 RETURNING id
                """,
                position["id"], exit_reason, exit_price, pnl, position["user_id"],
            )
            if updated is None:
                logger.info("paper.close skip (already closed) id=%s",
                            position["id"])
                return {"pnl_usdc": Decimal("0"), "exit_price": exit_price,
                        "exit_reason": "already_closed"}
            await ledger.credit_in_conn(
                conn, position["user_id"], proceeds, ledger.T_TRADE_CLOSE,
                ref_id=position["id"], note=f"paper close {exit_reason}",
            )
    log.info("paper_trade_close", user_id=str(position["user_id"]), market_id=position.get("market_id"), rule=position.get("strategy_type"), position_id=str(position["id"]), exit_reason=exit_reason, pnl=str(pnl))
    await audit.write(actor_role="bot", action="paper_close",
                      user_id=position["user_id"],
                      payload={"position_id": str(position["id"]),
                               "exit_price": exit_price,
                               "exit_reason": exit_reason,
                               "pnl_usdc": str(pnl)})
    # Fire a portfolio_snapshots row so the cb_portfolio NOTIFY trigger
    # pushes the new equity/PnL to WebTrader SSE listeners. Best-effort —
    # the writer swallows its own errors so a snapshot outage cannot
    # corrupt the realised-close return contract.
    await portfolio_snapshots.write_snapshot(position["user_id"])
    return {"pnl_usdc": pnl, "exit_price": exit_price, "exit_reason": exit_reason}
