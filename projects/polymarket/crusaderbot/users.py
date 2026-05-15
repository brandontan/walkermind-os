"""User CRUD helpers used across handlers + scheduler."""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from .database import get_pool


async def upsert_user(telegram_user_id: int, username: str | None) -> dict:
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT * FROM users WHERE telegram_user_id=$1", telegram_user_id,
            )
            if row is None:
                # New user — create with access_tier=2 (active by default, no allowlist)
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
                # Ensure wallet row exists (Concierge will seed the $1,000 balance)
                await conn.execute(
                    "INSERT INTO wallets (user_id) VALUES ($1) "
                    "ON CONFLICT (user_id) DO NOTHING",
                    row["id"],
                )
            else:
                # Existing user — silently upgrade legacy tier-1 users to tier-2
                if row["access_tier"] < 2:
                    await conn.execute(
                        "UPDATE users SET access_tier=2 WHERE id=$1", row["id"],
                    )
                if username and username != row["username"]:
                    await conn.execute(
                        "UPDATE users SET username=$1 WHERE id=$2",
                        username, row["id"],
                    )
                # Re-fetch to pick up any updates
                row = await conn.fetchrow(
                    "SELECT * FROM users WHERE id=$1", row["id"],
                )
    return dict(row)


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
