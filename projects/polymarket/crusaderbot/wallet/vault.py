"""Encrypted private-key storage helpers (DB-backed via wallets table)."""
from __future__ import annotations

import logging
from uuid import UUID

from ..config import get_settings
from ..database import get_pool
from .generator import decrypt_pk, derive_address, encrypt_pk

logger = logging.getLogger(__name__)


async def next_hd_index() -> int:
    """Atomically reserve and return the next HD index (1+)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "UPDATE hd_index_counter SET next_index = next_index + 1 "
                "RETURNING next_index - 1 AS reserved"
            )
    return int(row["reserved"])


async def create_wallet_for_user(user_id: UUID) -> tuple[str, int]:
    """Derive a fresh HD address, encrypt + store, return (address, hd_index)."""
    settings = get_settings()
    idx = await next_hd_index()
    address, pk = derive_address(settings.WALLET_HD_SEED, idx)
    encrypted = encrypt_pk(pk, settings.WALLET_ENCRYPTION_KEY)
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO wallets (user_id, deposit_address, hd_index, encrypted_key) "
            "VALUES ($1, $2, $3, $4) ON CONFLICT (user_id) DO NOTHING",
            user_id, address, idx, encrypted,
        )
        row = await conn.fetchrow(
            "SELECT deposit_address, hd_index FROM wallets WHERE user_id = $1",
            user_id,
        )
    return row["deposit_address"], int(row["hd_index"])


async def get_wallet(user_id: UUID) -> dict | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT deposit_address, hd_index, balance_usdc FROM wallets "
            "WHERE user_id = $1",
            user_id,
        )
        return dict(row) if row else None


async def get_decrypted_pk(user_id: UUID) -> str | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT encrypted_key FROM wallets WHERE user_id = $1", user_id,
        )
    if not row:
        return None
    settings = get_settings()
    return decrypt_pk(row["encrypted_key"], settings.WALLET_ENCRYPTION_KEY)


def master_wallet() -> tuple[str, str]:
    """Master/hot-pool wallet: HD index 0 unless explicitly overridden in env."""
    settings = get_settings()
    if settings.MASTER_WALLET_ADDRESS and settings.MASTER_WALLET_PRIVATE_KEY:
        pk = settings.MASTER_WALLET_PRIVATE_KEY
        if not pk.startswith("0x"):
            pk = "0x" + pk
        return settings.MASTER_WALLET_ADDRESS, pk
    return derive_address(settings.WALLET_HD_SEED, 0)
