"""User CRUD helpers used across handlers + scheduler."""
from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from .database import get_pool

logger = logging.getLogger(__name__)


async def upsert_user(telegram_user_id: int, username: str | None) -> dict:
    pool = get_pool()
    _is_new_user = False
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT * FROM users WHERE telegram_user_id=$1", telegram_user_id,
            )
            if row is None:
                row = await conn.fetchrow(
                    "INSERT INTO users (telegram_user_id, username, access_tier) "
                    "VALUES ($1, $2, 2) RETURNING *",
                    telegram_user_id, username,
                )
                await conn.execute(
                    "INSERT INTO user_settings (user_id) VALUES ($1) "
                    "ON CONFLICT (user_id) DO NOTHING",
                    row["id"],
                )
                _is_new_user = True
            else:
                if row["access_tier"] < 2:
                    await conn.execute(
                        "UPDATE users SET access_tier=2 WHERE id=$1", row["id"],
                    )
                if username and username != row["username"]:
                    await conn.execute(
                        "UPDATE users SET username=$1 WHERE id=$2",
                        username, row["id"],
                    )
                row = await conn.fetchrow(
                    "SELECT * FROM users WHERE id=$1", row["id"],
                )
    # Must run AFTER transaction commits — vault.py uses its own connection.
    # ON CONFLICT DO NOTHING in create_wallet_for_user makes this safe on retries.
    if _is_new_user:
        from .wallet.vault import create_wallet_for_user
        try:
            await create_wallet_for_user(row["id"])
        except Exception:
            logger.exception(
                "wallet creation failed for new user user_id=%s", row["id"]
            )
        try:
            await seed_paper_capital(row["id"])
        except Exception:
            logger.exception(
                "paper seed failed for new user user_id=%s", row["id"]
            )
    return dict(row)


async def seed_paper_capital(user_id: UUID) -> bool:
    """Atomically credit $1,000 paper USDC if wallet exists at zero balance
    AND no prior seed-ledger entry exists. Idempotent — safe to retry.

    Returns True if a credit happened, False if no-op (already seeded or
    wallet missing).
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            bal = await conn.fetchval(
                "SELECT balance_usdc FROM wallets WHERE user_id=$1 FOR UPDATE",
                user_id,
            )
            if bal is None:
                return False  # wallet not yet created; caller can retry
            if float(bal) != 0:
                return False  # already has funds — never overwrite
            already = await conn.fetchval(
                "SELECT 1 FROM ledger WHERE user_id=$1 AND type='deposit' "
                "AND note='Paper wallet — initial $1,000 credit' LIMIT 1",
                user_id,
            )
            if already:
                return False
            await conn.execute(
                "UPDATE wallets SET balance_usdc=1000 "
                "WHERE user_id=$1 AND balance_usdc=0",
                user_id,
            )
            await conn.execute(
                "INSERT INTO ledger (user_id, type, amount_usdc, note) "
                "VALUES ($1, 'deposit', 1000, "
                "'Paper wallet — initial $1,000 credit')",
                user_id,
            )
            return True


async def get_user_by_telegram_id(telegram_user_id: int) -> Optional[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM users WHERE telegram_user_id=$1", telegram_user_id,
        )
        return dict(row) if row else None


async def get_user_by_id(user_id: UUID) -> Optional[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE id=$1", user_id)
        return dict(row) if row else None


async def get_user_by_username(username: str) -> Optional[dict]:
    if username.startswith("@"):
        username = username[1:]
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM users WHERE LOWER(username)=LOWER($1)", username,
        )
        return dict(row) if row else None


async def set_tier(user_id: UUID, tier: int) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET access_tier=GREATEST(access_tier, $2) WHERE id=$1",
            user_id, tier,
        )


async def force_set_tier(user_id: UUID, tier: int) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET access_tier=$2 WHERE id=$1", user_id, tier,
        )


async def set_auto_trade(user_id: UUID, on: bool) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET auto_trade_on=$2 WHERE id=$1", user_id, on,
        )


async def set_paused(user_id: UUID, paused: bool) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET paused=$2 WHERE id=$1", user_id, paused,
        )


async def set_locked(user_id: UUID, locked: bool) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET locked=$2 WHERE id=$1", user_id, locked,
        )


async def get_settings_for(user_id: UUID) -> dict:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM user_settings WHERE user_id=$1", user_id,
        )
        if row is None:
            await conn.execute(
                "INSERT INTO user_settings (user_id) VALUES ($1)", user_id,
            )
            row = await conn.fetchrow(
                "SELECT * FROM user_settings WHERE user_id=$1", user_id,
            )
    return dict(row)


async def set_onboarding_complete(user_id: UUID, complete: bool = True) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET onboarding_complete=$2 WHERE id=$1", user_id, complete,
        )


async def update_settings(user_id: UUID, **fields) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k}=${i+2}" for i, k in enumerate(fields.keys()))
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            f"UPDATE user_settings SET {cols}, updated_at=NOW() WHERE user_id=$1",
            user_id, *fields.values(),
        )
