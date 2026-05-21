"""User identity service — Telegram-keyed upsert + audit-logged role transitions."""
from __future__ import annotations

import json
from typing import Optional
from uuid import UUID

import asyncpg
import structlog

log = structlog.get_logger(__name__)


VALID_ROLES: frozenset[str] = frozenset({"admin", "user"})


async def get_or_create_user(
    pool: asyncpg.Pool,
    telegram_user_id: int,
    username: Optional[str] = None,
) -> dict:
    """Upsert a user keyed on telegram_user_id. Returns full user row as dict.

    On INSERT: defaults are access_tier=4, role='user', auto_trade_on=FALSE.
    access_tier is set to 4 explicitly so the legacy column never blocks
    inserts while it still exists; the role column is the access source of
    truth (see migration 045_add_role_column.sql).
    On CONFLICT: refreshes username if a non-NULL value is provided; preserves
    every other column including access_tier, role, auto_trade_on, referrer_id.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "INSERT INTO users (telegram_user_id, username, access_tier, role) "
                "VALUES ($1, $2, 4, 'user') "
                "ON CONFLICT (telegram_user_id) DO UPDATE "
                "SET username = COALESCE(EXCLUDED.username, users.username) "
                "RETURNING id, telegram_user_id, username, access_tier, role, "
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
            "SELECT id, telegram_user_id, username, access_tier, role, auto_trade_on, "
            "referrer_id, created_at FROM users WHERE telegram_user_id=$1",
            telegram_user_id,
        )
    return dict(row) if row else None


async def update_role(
    pool: asyncpg.Pool,
    user_id: UUID,
    new_role: str,
    actor_role: str = "system",
    *,
    conn: Optional[asyncpg.Connection] = None,
) -> None:
    """Atomically update users.role and write an audit.log entry.

    new_role must be 'admin' or 'user'. Raises ValueError on unknown role
    or when user is not found.

    When `conn` is supplied the operation runs on the caller's connection
    and inherits its open transaction so the caller can keep role change +
    related writes in one atomic unit.
    """
    if new_role not in VALID_ROLES:
        raise ValueError(
            f"update_role: invalid role {new_role!r}. Valid: {sorted(VALID_ROLES)}"
        )

    if conn is not None:
        old_role = await conn.fetchval(
            "SELECT role FROM users WHERE id=$1 FOR UPDATE",
            user_id,
        )
        if old_role is None:
            raise ValueError(f"user not found: {user_id}")
        await conn.execute(
            "UPDATE users SET role=$1 WHERE id=$2",
            new_role, user_id,
        )
        await conn.execute(
            "INSERT INTO audit.log (user_id, actor_role, action, payload) "
            "VALUES ($1, $2, $3, $4::jsonb)",
            user_id, actor_role, "user.role_changed",
            json.dumps({"old_role": old_role, "new_role": new_role}),
        )
    else:
        async with pool.acquire() as acquired:
            async with acquired.transaction():
                old_role = await acquired.fetchval(
                    "SELECT role FROM users WHERE id=$1 FOR UPDATE",
                    user_id,
                )
                if old_role is None:
                    raise ValueError(f"user not found: {user_id}")
                await acquired.execute(
                    "UPDATE users SET role=$1 WHERE id=$2",
                    new_role, user_id,
                )
                await acquired.execute(
                    "INSERT INTO audit.log (user_id, actor_role, action, payload) "
                    "VALUES ($1, $2, $3, $4::jsonb)",
                    user_id, actor_role, "user.role_changed",
                    json.dumps({"old_role": old_role, "new_role": new_role}),
                )
    log.info(
        "user.role_changed",
        user_id=str(user_id),
        old_role=old_role,
        new_role=new_role,
        actor_role=actor_role,
    )
