"""Wallet persistence boundary — DB-backed deposit address registry."""
from __future__ import annotations

from typing import Optional
from uuid import UUID

import asyncpg
import structlog

log = structlog.get_logger(__name__)


async def get_next_hd_index(pool: asyncpg.Pool) -> int:
    """Return the next free HD index (monotonic, starts at 0).

    Note: this read+insert sequence is not atomic; the DB UNIQUE(hd_index)
    constraint catches racing inserters. R2 caller does not retry — safe
    under the low concurrency expected at this lane.
    """
    async with pool.acquire() as conn:
        result = await conn.fetchval(
            "SELECT COALESCE(MAX(hd_index), -1) + 1 FROM wallets"
        )
    return int(result)


async def store_wallet(
    pool: asyncpg.Pool,
    user_id: UUID,
    address: str,
    hd_index: int,
    encrypted_key: str,
) -> None:
    """Persist a new wallet record. UNIQUE(deposit_address) and UNIQUE(hd_index)
    + PRIMARY KEY(user_id) are enforced at the schema level.
    """
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO wallets (user_id, deposit_address, hd_index, encrypted_key) "
            "VALUES ($1, $2, $3, $4)",
            user_id, address, hd_index, encrypted_key,
        )
    log.info("wallet.stored", user_id=str(user_id), hd_index=hd_index)


async def get_wallet(
    pool: asyncpg.Pool,
    user_id: UUID,
) -> Optional[dict]:
    """Return wallet row for user, or None if not yet provisioned.

    `encrypted_key` is included for downstream signing flows; callers MUST NEVER
    log it or surface it to users.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id, deposit_address, hd_index, encrypted_key, "
            "balance_usdc, created_at FROM wallets WHERE user_id=$1",
            user_id,
        )
    return dict(row) if row else None
