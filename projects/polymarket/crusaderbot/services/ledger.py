"""Sub-account ledger service — append-only credit/debit + balance read.

All writes go through `_LEDGER_LOCK` so balance reads in the same process
observe a consistent total. The DB itself is the source of truth across
processes; the lock only protects against intra-process double-credit
between the watcher's idempotency check and the INSERT.

Public surface:
    ensure_sub_account(pool, user_id) -> sub_account_id (UUID)
    get_balance(pool, user_id) -> Decimal
    credit(pool, sub_account_id, amount, ref_id, type="deposit") -> entry_id
    debit(pool, sub_account_id, amount, ref_id, type) -> entry_id   [scaffold]
    get_entries(pool, sub_account_id, limit=50) -> list[dict]
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Optional
from uuid import UUID

import asyncpg
import structlog

log = structlog.get_logger(__name__)

_LEDGER_LOCK = asyncio.Lock()

ENTRY_TYPE_DEPOSIT = "deposit"
ENTRY_TYPE_WITHDRAW = "withdraw"
ENTRY_TYPE_TRADE_DEBIT = "trade_debit"
ENTRY_TYPE_TRADE_CREDIT = "trade_credit"
ENTRY_TYPE_FEE = "fee"


async def ensure_sub_account(pool: asyncpg.Pool, user_id: UUID) -> UUID:
    """Return the user's sub_account_id, creating it on first call.

    1:1 sub-account per user for MVP — UNIQUE(user_id) at the schema level.
    Uses INSERT ... ON CONFLICT DO NOTHING + fetch to stay race-safe.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO sub_accounts (user_id) VALUES ($1) "
            "ON CONFLICT (user_id) DO NOTHING RETURNING id",
            user_id,
        )
        if row is not None:
            sub_account_id: UUID = row["id"]
            log.info("ledger.sub_account_created",
                     user_id=str(user_id),
                     sub_account_id=str(sub_account_id))
            return sub_account_id
        existing = await conn.fetchval(
            "SELECT id FROM sub_accounts WHERE user_id=$1",
            user_id,
        )
    if existing is None:
        raise RuntimeError(
            f"sub_account upsert returned no row and lookup found nothing "
            f"for user_id={user_id}"
        )
    return existing


async def get_balance(
    pool: asyncpg.Pool,
    user_id: UUID,
    *,
    conn: Optional[asyncpg.Connection] = None,
) -> Decimal:
    """Return current balance = SUM(amount_usdc) over the user's ledger.

    Returns Decimal('0') if no sub-account yet exists or no entries yet.
    Credits are positive amounts, debits are negative — we sum directly.

    When `conn` is supplied, the caller's transaction is reused so a
    post-credit balance read inside an open transaction observes the
    just-inserted entry.
    """
    if conn is not None:
        total = await conn.fetchval(
            "SELECT COALESCE(SUM(le.amount_usdc), 0) "
            "FROM ledger_entries le "
            "JOIN sub_accounts sa ON sa.id = le.sub_account_id "
            "WHERE sa.user_id = $1",
            user_id,
        )
    else:
        async with pool.acquire() as acquired:
            total = await acquired.fetchval(
                "SELECT COALESCE(SUM(le.amount_usdc), 0) "
                "FROM ledger_entries le "
                "JOIN sub_accounts sa ON sa.id = le.sub_account_id "
                "WHERE sa.user_id = $1",
                user_id,
            )
    return Decimal(total) if total is not None else Decimal("0")


async def credit(
    pool: asyncpg.Pool,
    sub_account_id: UUID,
    amount: Decimal,
    ref_id: Optional[UUID],
    type: str = ENTRY_TYPE_DEPOSIT,
    *,
    conn: Optional[asyncpg.Connection] = None,
) -> UUID:
    """Append a positive ledger entry. `amount` MUST be > 0.

    When `conn` is supplied the insert runs on the caller's connection so
    it can be composed into a larger transaction (deposit watcher uses
    this to keep deposit insert + ledger credit + tier bump atomic). The
    intra-process `_LEDGER_LOCK` is bypassed in that path because the
    enclosing transaction already holds row-level guarantees.
    """
    if amount <= 0:
        raise ValueError(f"credit amount must be positive, got {amount}")
    if conn is not None:
        entry_id: UUID = await conn.fetchval(
            "INSERT INTO ledger_entries "
            "(sub_account_id, type, amount_usdc, ref_id) "
            "VALUES ($1, $2, $3, $4) RETURNING id",
            sub_account_id, type, amount, ref_id,
        )
    else:
        async with _LEDGER_LOCK:
            async with pool.acquire() as acquired:
                entry_id = await acquired.fetchval(
                    "INSERT INTO ledger_entries "
                    "(sub_account_id, type, amount_usdc, ref_id) "
                    "VALUES ($1, $2, $3, $4) RETURNING id",
                    sub_account_id, type, amount, ref_id,
                )
    log.info(
        "ledger.credit",
        sub_account_id=str(sub_account_id),
        type=type,
        amount=str(amount),
        ref_id=str(ref_id) if ref_id else None,
        entry_id=str(entry_id),
    )
    return entry_id


async def debit(
    pool: asyncpg.Pool,
    sub_account_id: UUID,
    amount: Decimal,
    ref_id: Optional[UUID],
    type: str,
) -> UUID:
    """Append a negative ledger entry. `amount` is given as a positive number
    and stored as -amount. Scaffold only — no caller in R4."""
    if amount <= 0:
        raise ValueError(f"debit amount must be positive, got {amount}")
    async with _LEDGER_LOCK:
        async with pool.acquire() as conn:
            entry_id: UUID = await conn.fetchval(
                "INSERT INTO ledger_entries "
                "(sub_account_id, type, amount_usdc, ref_id) "
                "VALUES ($1, $2, $3, $4) RETURNING id",
                sub_account_id, type, -amount, ref_id,
            )
    log.info(
        "ledger.debit",
        sub_account_id=str(sub_account_id),
        type=type,
        amount=str(amount),
        ref_id=str(ref_id) if ref_id else None,
        entry_id=str(entry_id),
    )
    return entry_id


async def get_entries(
    pool: asyncpg.Pool,
    sub_account_id: UUID,
    limit: int = 50,
) -> list[dict]:
    """Return up to `limit` most recent entries for a sub-account, newest first."""
    if limit <= 0:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, sub_account_id, type, amount_usdc, ref_id, ts "
            "FROM ledger_entries WHERE sub_account_id=$1 "
            "ORDER BY ts DESC LIMIT $2",
            sub_account_id, limit,
        )
    return [dict(r) for r in rows]
