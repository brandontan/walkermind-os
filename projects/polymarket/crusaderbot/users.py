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
                row = await conn.fetchrow(
                    "INSERT INTO users (telegram_user_id, username) "
                    "VALUES ($1, $2) RETURNING *",
                    telegram_user_id, username,
                )
                # Default settings row
                await conn.execute(
                    "INSERT INTO user_settings (user_id) VALUES ($1) "
                    "ON CONFLICT (user_id) DO NOTHING",
                    row["id"],
                )
            elif username and username != row["username"]:
                await conn.execute(
                    "UPDATE users SET username=$1 WHERE id=$2",
                    username, row["id"],
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
