"""Internal USDC accounting — every credit/debit lands in the ledger table.

`*_in_conn` variants accept an existing connection so callers can keep the
ledger update atomic with related state changes (e.g. open/close a position).
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional
from uuid import UUID

import asyncpg

from ..database import get_pool

logger = logging.getLogger(__name__)

# Allowed ledger types
T_DEPOSIT = "deposit"
T_TRADE_OPEN = "trade_open"
T_TRADE_CLOSE = "trade_close"
T_REDEEM = "redeem"
T_FEE = "fee"
T_WITHDRAW = "withdraw"
T_ADJUSTMENT = "adjustment"


async def credit(user_id: UUID, amount: Decimal | float, type_: str,
                 ref_id: Optional[UUID] = None, note: str | None = None) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await credit_in_conn(conn, user_id, amount, type_, ref_id, note)


async def debit(user_id: UUID, amount: Decimal | float, type_: str,
                ref_id: Optional[UUID] = None, note: str | None = None) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await debit_in_conn(conn, user_id, amount, type_, ref_id, note)


async def credit_in_conn(conn: asyncpg.Connection, user_id: UUID,
                         amount: Decimal | float, type_: str,
                         ref_id: Optional[UUID] = None,
                         note: str | None = None) -> None:
    await _post_in_conn(conn, user_id, Decimal(str(amount)), type_, ref_id, note)


async def debit_in_conn(conn: asyncpg.Connection, user_id: UUID,
                        amount: Decimal | float, type_: str,
                        ref_id: Optional[UUID] = None,
                        note: str | None = None) -> None:
    await _post_in_conn(conn, user_id, -Decimal(str(amount)), type_, ref_id, note)


async def _post_in_conn(conn: asyncpg.Connection, user_id: UUID,
                        signed_amount: Decimal, type_: str,
                        ref_id: Optional[UUID], note: str | None) -> None:
    await conn.execute(
        "INSERT INTO ledger (user_id, type, amount_usdc, ref_id, note) "
        "VALUES ($1, $2, $3, $4, $5)",
        user_id, type_, signed_amount, ref_id, note,
    )
    await conn.execute(
        "UPDATE wallets SET balance_usdc = balance_usdc + $1 "
        "WHERE user_id = $2",
        signed_amount, user_id,
    )


async def get_balance(user_id: UUID) -> Decimal:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT balance_usdc FROM wallets WHERE user_id = $1", user_id,
        )
    return Decimal(row["balance_usdc"]) if row else Decimal("0")


async def daily_pnl(user_id: UUID) -> Decimal:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT COALESCE(SUM(amount_usdc), 0) AS pnl
            FROM ledger
            WHERE user_id = $1
              AND type IN ('trade_close', 'redeem', 'fee')
              AND created_at >= date_trunc('day', NOW())
            """,
            user_id,
        )
    return Decimal(row["pnl"]) if row else Decimal("0")
