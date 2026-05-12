"""asyncpg pool + migration runner + kill-switch helper."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import asyncpg

from .config import get_settings

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None
# Class name of the most recent ping() failure, or None when the last
# probe succeeded. Surfaced via last_ping_error() so /health can include
# the asyncpg exception class in the operator-facing reason string.
_last_ping_error: Optional[str] = None

# Supavisor (Supabase) pooler DSNs route every transaction through a
# multiplexed pgbouncer-style proxy. asyncpg's server-side prepared
# statement cache cannot survive multiplexed connections, surfacing as
# `prepared statement "__asyncpg_stmt_*__" does not exist` /
# DuplicatePreparedStatementError / ProtocolViolationError under load.
# We always pass statement_cache_size=0 so the pool is safe under any
# pooler topology. The host check below is diagnostic only — startup is
# never blocked. See https://github.com/MagicStack/asyncpg/issues/339.
_POOLER_HOST_HINT = "pooler.supabase.com"


def _log_connection_type(dsn: str) -> None:
    """Log whether DATABASE_URL points at a Supabase pooler or direct connection.

    Logs WARNING when host contains 'pooler.supabase.com' (any port).
    Logs INFO when host is a Supabase direct host (contains 'supabase'
    but not the pooler hint). Silent noop for non-Supabase hosts and
    hostless/malformed DSNs — connection topology cannot be determined
    from the host alone for arbitrary proxies (Fly PgBouncer, RDS, etc.).
    """
    try:
        parsed = urlparse(dsn)
    except Exception:  # noqa: BLE001 — diagnostics must never crash boot
        return
    host = (parsed.hostname or "").lower()
    if not host:
        return
    if _POOLER_HOST_HINT in host:
        logger.warning(
            "DATABASE_URL points at Supabase connection pooler "
            "(host=%s); statement_cache_size=0 applied to prevent "
            "asyncpg prepared-statement errors under multiplexed connections.",
            host,
        )
    elif "supabase" in host:
        logger.info(
            "DATABASE_URL uses direct Supabase connection (host=%s).",
            host,
        )


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Warm-ping every new pool connection on creation.

    Surfaces broken connections (e.g. Supabase idle-timeout recycled backends)
    at pool-init time rather than mid-request, so the pool health check in
    /health and job_runs write paths never hit a silently dead connection.
    asyncpg calls this coroutine once per new physical backend connection.
    """
    await conn.execute("SELECT 1")


async def init_pool() -> asyncpg.Pool:
    global _pool
    if _pool is not None:
        return _pool
    settings = get_settings()
    _log_connection_type(settings.DATABASE_URL)
    # statement_cache_size=0 disables asyncpg's per-connection
    # server-side prepared statement cache. Required when DATABASE_URL
    # points at a transaction-pooled proxy (Supabase Supavisor, Fly
    # PgBouncer, etc.): cached statement names are scoped to the backend
    # the statement was prepared on and do not follow a transaction
    # across multiplexed backends, surfacing as
    # `prepared statement "__asyncpg_stmt_*__" does not exist` /
    # DuplicatePreparedStatementError / ProtocolViolationError under
    # load. See https://github.com/MagicStack/asyncpg/issues/339.
    #
    # server_settings.application_name labels every connection in
    # pg_stat_activity so an operator running
    # `SELECT * FROM pg_stat_activity WHERE application_name=$1` on the
    # Supabase SQL editor (or Postgres directly) can immediately tell
    # which sessions belong to this bot, distinct from psql / Studio /
    # other workloads sharing the same project.
    _pool = await asyncpg.create_pool(
        dsn=settings.DATABASE_URL,
        min_size=1,
        max_size=settings.DB_POOL_MAX,
        command_timeout=30,
        statement_cache_size=0,
        init=_init_connection,
        server_settings={"application_name": "crusaderbot"},
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
    """Run all SQL migrations. MUST be idempotent — safe to call on every restart."""
    pool = await init_pool()
    migrations_dir = Path(__file__).parent / "migrations"
    files = sorted(migrations_dir.glob("*.sql"))
    if not files:
        logger.warning("No migration files found in %s", migrations_dir)
        return
    try:
        async with pool.acquire() as conn:
            for f in files:
                sql = f.read_text(encoding="utf-8")
                logger.info("Running migration %s", f.name)
                try:
                    await conn.execute(sql)
                except Exception as exc:
                    logger.error(
                        "Migration failed: %s — %s", f.name, exc, exc_info=True
                    )
                    raise
    except Exception as exc:
        logger.error("run_migrations failed: %s", exc, exc_info=True)
        raise
    logger.info("Migrations complete (%d files)", len(files))


async def ping() -> bool:
    """Probe the asyncpg pool with ``SELECT 1``.

    On failure the exception class name is captured in
    ``_last_ping_error`` so ``last_ping_error()`` callers (notably the
    health endpoint) can surface it in the operator alert string. The
    full exception is also forwarded to Sentry via ``exc_info=True``
    so triage sees the structured exception rather than just the
    formatted message.
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
