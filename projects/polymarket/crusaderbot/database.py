"""asyncpg pool + migration runner + kill-switch helper."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import asyncpg

from .config import get_settings

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None
# Class name of the most recent ping() failure, or None when the last
# probe succeeded. Surfaced via last_ping_error() so /health can include
# the asyncpg exception class in the operator-facing reason string.
_last_ping_error: Optional[str] = None


async def init_pool() -> asyncpg.Pool:
    global _pool
    if _pool is not None:
        return _pool
    settings = get_settings()
    # statement_cache_size=0 disables asyncpg's server-side prepared
    # statement cache. Required when DATABASE_URL points at a PgBouncer
    # in transaction-pooling mode (Fly Postgres default): cached
    # statement names do not survive connection multiplexing and surface
    # as `prepared statement "__asyncpg_stmt_*__" does not exist` /
    # DuplicatePreparedStatementError / ProtocolViolationError under
    # load. See https://github.com/MagicStack/asyncpg/issues/339.
    _pool = await asyncpg.create_pool(
        dsn=settings.DATABASE_URL,
        min_size=1,
        max_size=settings.DB_POOL_MAX,
        command_timeout=30,
        statement_cache_size=0,
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
    """Probe the asyncpg pool with ``SELECT 1``.

    On failure the exception class name is captured in
    ``_last_ping_error`` so ``last_ping_error()`` callers (notably the
    health endpoint) can surface it in the operator alert string. The
    full exception is also forwarded to Sentry via ``exc_info=True``.
    """
    global _last_ping_error
    try:
        pool = await init_pool()
        async with pool.acquire() as conn:
            ok = await conn.fetchval("SELECT 1") == 1
        if ok:
            _last_ping_error = None
        return ok
    except Exception as exc:
        _last_ping_error = type(exc).__name__
        logger.error("DB ping failed: %s", exc, exc_info=True)
        return False


def last_ping_error() -> Optional[str]:
    """Return the class name of the most recent ``ping()`` exception.

    ``None`` whenever the last probe succeeded (or no probe has run
    yet). The health endpoint reads this synchronously after a False
    return so the asyncpg exception class lands in the Telegram alert
    text without operators needing to grep Sentry.
    """
    return _last_ping_error


async def is_kill_switch_active() -> bool:
    """Compatibility wrapper around the R12f kill-switch domain module.

    R12f introduced ``system_settings.kill_switch_active`` as the single
    source of truth (cached 30s on the hot path). Existing callers
    (``api/admin.py``, the legacy admin inline-keyboard callback) keep
    working through this wrapper without bypassing the cache or the
    history table.
    """
    from .domain.ops.kill_switch import is_active as _is_active

    return await _is_active()


async def set_kill_switch(active: bool, reason: str | None, changed_by) -> None:
    """Compatibility wrapper that routes through ops.kill_switch.set_active.

    The legacy ``kill_switch`` table is no longer authoritative — flips
    persist to ``system_settings`` and a row is appended to
    ``kill_switch_history``. ``changed_by`` is preserved as the actor id
    when it is an int-like (Telegram user id); otherwise it is dropped.
    """
    from .domain.ops.kill_switch import set_active

    actor_id: int | None = None
    if isinstance(changed_by, int):
        actor_id = changed_by

    await set_active(
        action="pause" if active else "resume",
        actor_id=actor_id,
        reason=reason,
    )
