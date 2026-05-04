"""asyncpg pool + migration runner + kill-switch helper."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import asyncpg

from .config import get_settings

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None


async def init_pool() -> asyncpg.Pool:
    global _pool
    if _pool is not None:
        return _pool
    settings = get_settings()
    _pool = await asyncpg.create_pool(
        dsn=settings.DATABASE_URL,
        min_size=1,
        max_size=settings.DB_POOL_MAX,
        command_timeout=30,
    )
    logger.info("asyncpg pool initialised (max=%s)", settings.DB_POOL_MAX)
    return _pool


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Database pool not initialised — call init_pool() first.")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def run_migrations() -> None:
    pool = await init_pool()
    migrations_dir = Path(__file__).parent / "migrations"
    files = sorted(migrations_dir.glob("*.sql"))
    if not files:
        logger.warning("No migration files found in %s", migrations_dir)
        return
    async with pool.acquire() as conn:
        for f in files:
            sql = f.read_text(encoding="utf-8")
            logger.info("Running migration %s", f.name)
            await conn.execute(sql)
    logger.info("Migrations complete (%d files)", len(files))


async def ping() -> bool:
    try:
        pool = await init_pool()
        async with pool.acquire() as conn:
            return await conn.fetchval("SELECT 1") == 1
    except Exception as exc:
        logger.error("DB ping failed: %s", exc)
        return False


async def is_kill_switch_active() -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT active FROM kill_switch ORDER BY id DESC LIMIT 1"
        )
        return bool(row and row["active"])


async def set_kill_switch(active: bool, reason: str | None, changed_by) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO kill_switch (active, reason, changed_by) VALUES ($1, $2, $3)",
            active, reason, changed_by,
        )
