"""Async PostgreSQL pool wrapper for CrusaderBot."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import asyncpg
import structlog

from .config import settings

log = structlog.get_logger(__name__)


def _normalize_dsn(url: str) -> str:
    """asyncpg driver expects postgresql:// not postgresql+asyncpg://."""
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


class Database:
    def __init__(self) -> None:
        self._pool: Optional[asyncpg.Pool] = None

    async def connect(self) -> None:
        if self._pool is not None:
            return
        self._pool = await asyncpg.create_pool(
            dsn=_normalize_dsn(settings.DATABASE_URL),
            min_size=1,
            max_size=settings.DB_POOL_MAX,
        )
        log.info("database.connected", pool_max=settings.DB_POOL_MAX)

    async def disconnect(self) -> None:
        if self._pool is None:
            return
        await self._pool.close()
        self._pool = None
        log.info("database.disconnected")

    async def ping(self) -> bool:
        if self._pool is None:
            return False
        try:
            async with self._pool.acquire() as conn:
                result = await conn.fetchval("SELECT 1")
            return result == 1
        except Exception as exc:
            log.warning("database.ping_failed", error=str(exc))
            return False

    async def run_migrations(self) -> None:
        if self._pool is None:
            raise RuntimeError("database.run_migrations called before connect()")
        migrations_path = Path(__file__).parent / "migrations" / "001_init.sql"
        if not migrations_path.exists():
            raise FileNotFoundError(f"migrations file missing: {migrations_path}")
        async with self._pool.acquire() as conn:
            already = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name='users')"
            )
            if already:
                log.info("database.migrations_skipped", reason="schema already initialized")
                return
            sql = migrations_path.read_text(encoding="utf-8")
            async with conn.transaction():
                await conn.execute(sql)
        log.info("database.migrations_applied", file=str(migrations_path))

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("database not connected")
        return self._pool


db = Database()
