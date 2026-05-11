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
