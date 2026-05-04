"""User identity service — Telegram-keyed upsert + audit-logged tier transitions."""
from __future__ import annotations

import json
from typing import Optional
from uuid import UUID

import asyncpg
import structlog

log = structlog.get_logger(__name__)


async def get_or_create_user(
    pool: asyncpg.Pool,
    telegram_user_id: int,
    username: Optional[str] = None,
) -> dict:
    """Upsert a user keyed on telegram_user_id. Returns full user row as dict.

    On INSERT: defaults are access_tier=1, auto_trade_on=FALSE.
    On CONFLICT: refreshes username if a non-NULL value is provided; preserves
    every other column including access_tier, auto_trade_on, referrer_id.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "INSERT INTO users (telegram_user_id, username) VALUES ($1, $2) "
                "ON CONFLICT (telegram_user_id) DO UPDATE "
                "SET username = COALESCE(EXCLUDED.username, users.username) "
                "RETURNING id, telegram_user_id, username, access_tier, "
                "auto_trade_on, referrer_id, created_at",
                telegram_user_id, username,
            )
    return dict(row)


async def get_user_by_telegram_id(
    pool: asyncpg.Pool,
    telegram_user_id: int,
) -> Optional[dict]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, telegram_user_id, username, access_tier, auto_trade_on, "
            "referrer_id, created_at FROM users WHERE telegram_user_id=$1",
            telegram_user_id,
        )
    return dict(row) if row else None


async def bump_tier(
    pool: asyncpg.Pool,
    user_id: UUID,
    new_tier: int,
    actor_role: str = "system",
    *,
    conn: Optional[asyncpg.Connection] = None,
) -> None:
    """Atomically update access_tier and write an audit.log entry.

    Uses SELECT ... FOR UPDATE to lock the row; both UPDATE and audit INSERT
    happen in the same transaction. Raises ValueError if user not found.

    When `conn` is supplied the operation runs on the caller's connection
    and inherits its open transaction — the deposit watcher uses this to
    keep deposit insert + ledger credit + tier bump in one atomic unit so
    a partial failure cannot leave the user credited but un-promoted (or
    vice versa).
    """
    if conn is not None:
        old_tier = await conn.fetchval(
            "SELECT access_tier FROM users WHERE id=$1 FOR UPDATE",
            user_id,
        )
        if old_tier is None:
            raise ValueError(f"user not found: {user_id}")
        await conn.execute(
            "UPDATE users SET access_tier=$1 WHERE id=$2",
            new_tier, user_id,
        )
        await conn.execute(
            "INSERT INTO audit.log (user_id, actor_role, action, payload) "
            "VALUES ($1, $2, $3, $4::jsonb)",
            user_id, actor_role, "user.tier_changed",
            json.dumps({"old_tier": old_tier, "new_tier": new_tier}),
        )
    else:
        async with pool.acquire() as acquired:
            async with acquired.transaction():
                old_tier = await acquired.fetchval(
                    "SELECT access_tier FROM users WHERE id=$1 FOR UPDATE",
                    user_id,
                )
                if old_tier is None:
                    raise ValueError(f"user not found: {user_id}")
                await acquired.execute(
                    "UPDATE users SET access_tier=$1 WHERE id=$2",
                    new_tier, user_id,
                )
                await acquired.execute(
                    "INSERT INTO audit.log (user_id, actor_role, action, payload) "
                    "VALUES ($1, $2, $3, $4::jsonb)",
                    user_id, actor_role, "user.tier_changed",
                    json.dumps({"old_tier": old_tier, "new_tier": new_tier}),
                )
    log.info(
        "user.tier_bumped",
        user_id=str(user_id),
        old_tier=old_tier,
        new_tier=new_tier,
        actor_role=actor_role,
    )
