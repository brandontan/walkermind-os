"""Fee calculation service — gated behind FEE_COLLECTION_ENABLED.

Fee logic is fully implemented but will not run unless
settings.FEE_COLLECTION_ENABLED is True. This guard must never
be bypassed without explicit WARP🔹CMD authorization.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional
from uuid import UUID

import structlog

from ...config import get_settings
from ...database import get_pool

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


async def get_fee_pct() -> Decimal:
    """Read fee_pct from fee_config table. Falls back to 0.10 if row missing."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT fee_pct FROM fee_config WHERE id=1")
        return Decimal(str(row["fee_pct"])) if row else Decimal("0.10")


async def calculate_and_record_fee(
    *,
    user_id: UUID,
    trade_id: Optional[UUID],
    gross_pnl: Decimal,
) -> Optional[dict]:
    """Calculate fee and record to fees table.

    Returns fee record dict, or None when FEE_COLLECTION_ENABLED is False.
    """
    settings = get_settings()
    if not settings.FEE_COLLECTION_ENABLED:
        return None

    fee_pct = await get_fee_pct()
    fee_amount = gross_pnl * fee_pct
    net_pnl = gross_pnl - fee_amount

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO fees (user_id, trade_id, gross_pnl, fee_amount, net_pnl)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING *
            """,
            user_id, trade_id, gross_pnl, fee_amount, net_pnl,
        )

    logger.info(
        "fee.recorded user_id=%s trade_id=%s gross_pnl=%s fee=%s net=%s",
        user_id, trade_id, gross_pnl, fee_amount, net_pnl,
    )
    return dict(row)
