"""CRUD repository for copy_trade_tasks (Phase 5F)."""
from __future__ import annotations

import logging
from decimal import Decimal
from uuid import UUID

from ...database import get_pool
from .models import CopyTradeTask

logger = logging.getLogger(__name__)

_SELECT = """
    SELECT id, user_id, wallet_address, task_name, status,
           copy_mode, copy_amount, copy_pct,
           tp_pct, sl_pct, max_daily_spend, slippage_pct,
           min_trade_size, reverse_copy, created_at, updated_at
      FROM copy_trade_tasks
"""

_ALLOWED_FIELDS = frozenset({
    "task_name", "copy_mode", "copy_amount", "copy_pct",
    "tp_pct", "sl_pct", "max_daily_spend", "slippage_pct",
    "min_trade_size", "reverse_copy",
})


def _row_to_task(row: object) -> CopyTradeTask:
    return CopyTradeTask(
        id=row["id"],
        user_id=row["user_id"],
        wallet_address=row["wallet_address"],
        task_name=row["task_name"],
        status=row["status"],
        copy_mode=row["copy_mode"],
        copy_amount=row["copy_amount"],
        copy_pct=row["copy_pct"],
        tp_pct=row["tp_pct"],
        sl_pct=row["sl_pct"],
        max_daily_spend=row["max_daily_spend"],
        slippage_pct=row["slippage_pct"],
        min_trade_size=row["min_trade_size"],
        reverse_copy=row["reverse_copy"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def create_task(
    *,
    user_id: UUID,
    wallet_address: str,
    task_name: str,
    copy_mode: str,
    copy_amount: Decimal,
    copy_pct: Decimal | None = None,
    tp_pct: Decimal = Decimal("0.20"),
    sl_pct: Decimal = Decimal("0.10"),
    max_daily_spend: Decimal = Decimal("100.00"),
    slippage_pct: Decimal = Decimal("0.05"),
    min_trade_size: Decimal = Decimal("0.50"),
    reverse_copy: bool = False,
) -> CopyTradeTask:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO copy_trade_tasks
                (user_id, wallet_address, task_name, status,
                 copy_mode, copy_amount, copy_pct,
                 tp_pct, sl_pct, max_daily_spend, slippage_pct,
                 min_trade_size, reverse_copy)
            VALUES ($1, $2, $3, 'active', $4, $5, $6, $7, $8, $9, $10, $11, $12)
            RETURNING id, user_id, wallet_address, task_name, status,
                      copy_mode, copy_amount, copy_pct,
                      tp_pct, sl_pct, max_daily_spend, slippage_pct,
                      min_trade_size, reverse_copy, created_at, updated_at
            """,
            user_id, wallet_address, task_name, copy_mode,
            copy_amount, copy_pct, tp_pct, sl_pct,
            max_daily_spend, slippage_pct, min_trade_size, reverse_copy,
        )
    return _row_to_task(row)


async def get_task(task_id: UUID, user_id: UUID) -> CopyTradeTask | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            _SELECT + " WHERE id = $1 AND user_id = $2",
            task_id, user_id,
        )
    return _row_to_task(row) if row else None


async def update_task(
    task_id: UUID, user_id: UUID, **fields: object,
) -> CopyTradeTask | None:
    unknown = set(fields) - _ALLOWED_FIELDS
    if unknown:
        raise ValueError(f"Unknown fields: {unknown}")
    if not fields:
        return await get_task(task_id, user_id)
    set_clauses = ", ".join(
        f"{col} = ${i + 3}" for i, col in enumerate(fields)
    )
    values = list(fields.values())
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            UPDATE copy_trade_tasks
               SET {set_clauses}, updated_at = NOW()
             WHERE id = $1 AND user_id = $2
            RETURNING id, user_id, wallet_address, task_name, status,
                      copy_mode, copy_amount, copy_pct,
                      tp_pct, sl_pct, max_daily_spend, slippage_pct,
                      min_trade_size, reverse_copy, created_at, updated_at
            """,
            task_id, user_id, *values,
        )
    return _row_to_task(row) if row else None


async def list_active_tasks() -> list[CopyTradeTask]:
    """Return all copy_trade_tasks where status = 'active', across all users."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(_SELECT + " WHERE status = 'active'")
    return [_row_to_task(r) for r in rows]


async def delete_task(task_id: UUID, user_id: UUID) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "DELETE FROM copy_trade_tasks WHERE id = $1 AND user_id = $2 RETURNING id",
            task_id, user_id,
        )
    return row is not None


async def toggle_pause(task_id: UUID, user_id: UUID) -> str | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE copy_trade_tasks
               SET status = CASE WHEN status = 'paused' THEN 'active' ELSE 'paused' END,
                   updated_at = NOW()
             WHERE id = $1 AND user_id = $2
            RETURNING status
            """,
            task_id, user_id,
        )
    return row["status"] if row else None


async def task_pnl_summary(task_id: UUID, user_id: UUID) -> dict[str, float | int]:
    """Aggregate realized + unrealized P&L for one copy task.

    Copy orders persist with ``orders.idempotency_key =
    'copy_{task_id}_{leader_trade_id}'`` (see services/copy_trade/monitor.py)
    and ``positions`` join ``orders`` via ``positions.order_id``. Scoped by
    ``user_id`` so the aggregate can never bleed across tenants. Read-only,
    single round trip, no transaction.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
              COUNT(*) FILTER (WHERE p.status = 'open')   AS open_count,
              COUNT(*) FILTER (WHERE p.status = 'closed') AS closed_count,
              COALESCE(SUM(p.pnl_usdc)
                       FILTER (WHERE p.status = 'closed'), 0) AS realized_pnl,
              COALESCE(SUM(
                CASE WHEN p.status = 'open'
                          AND p.current_price IS NOT NULL
                          AND p.entry_price > 0
                     THEN (p.current_price - p.entry_price)
                          / p.entry_price * p.size_usdc
                     ELSE 0 END
              ), 0) AS unrealized_pnl,
              COALESCE(SUM(p.size_usdc), 0) AS total_invested,
              COUNT(*) FILTER (
                WHERE p.status = 'closed' AND p.pnl_usdc > 0) AS win_count,
              COUNT(*) FILTER (
                WHERE p.status = 'closed' AND p.pnl_usdc < 0) AS loss_count
              FROM positions p
              JOIN orders o ON o.id = p.order_id
             WHERE o.user_id = $1
               AND o.idempotency_key LIKE $2 ESCAPE '\\'
            """,
            user_id, "copy\\_" + str(task_id) + "\\_%",
        )
    realized = float(row["realized_pnl"])
    unrealized = float(row["unrealized_pnl"])
    return {
        "open_count": int(row["open_count"]),
        "closed_count": int(row["closed_count"]),
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
        "total_pnl": realized + unrealized,
        "total_invested": float(row["total_invested"]),
        "win_count": int(row["win_count"]),
        "loss_count": int(row["loss_count"]),
    }
