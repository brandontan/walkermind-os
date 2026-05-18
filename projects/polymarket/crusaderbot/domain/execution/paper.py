"""Paper execution engine — fully atomic open / close in a single DB transaction."""
from __future__ import annotations

import logging
from decimal import Decimal
from uuid import UUID

from ... import audit, notifications
from ...database import get_pool
from ...services.trade_notifications import TradeNotifier
from ...wallet import ledger

_notifier = TradeNotifier()

logger = logging.getLogger(__name__)


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
                                       tp_pct, sl_pct, mode, status)
                VALUES ($1,$2,$3,$4,$5,$6,$6,$7,$8,'paper','open')
                RETURNING id
                """,
                user_id, market_id, order_id, side,
                size_usdc, price, tp_pct, sl_pct,
            )
            position_id = pos_row["id"]
            await ledger.debit_in_conn(
                conn, user_id, size_usdc, ledger.T_TRADE_OPEN,
                ref_id=position_id, note=f"paper open {side} {market_id}",
            )

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
    )
    return {"order_id": order_id, "position_id": position_id, "mode": "paper"}


async def close_position(*, position: dict, exit_price: float,
                         exit_reason: str) -> dict:
    pool = get_pool()
    size = Decimal(str(position["size_usdc"]))
    entry = float(position["entry_price"])
    side = position["side"]
    if side == "yes":
        ret_pct = (exit_price - entry) / max(entry, 1e-6)
    else:
        comp_entry = 1 - entry
        comp_exit = 1 - exit_price
        ret_pct = (comp_exit - comp_entry) / max(comp_entry, 1e-6)
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
    await audit.write(actor_role="bot", action="paper_close",
                      user_id=position["user_id"],
                      payload={"position_id": str(position["id"]),
                               "exit_price": exit_price,
                               "exit_reason": exit_reason,
                               "pnl_usdc": str(pnl)})
    return {"pnl_usdc": pnl, "exit_price": exit_price, "exit_reason": exit_reason}
