"""asyncpg pool + migration runner + kill-switch helper."""
from __future__ import annotations

import asyncio
import hashlib
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


def _warn_if_supavisor_transaction_pool(dsn: str) -> None:
    """Detect and log whether DATABASE_URL points at a Supabase pooler or direct connection.

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


# Boot-resilience knobs (WARP/root-db-boot-resilience). The 2026-06-07 incident:
# the app booted, the DB warm-ping/connect stalled against Supabase/Supavisor,
# and the event loop wedged — /health froze reporting database TimeoutError and
# never recovered without a manual machine restart. These bound the boot-time
# connect so a transient stall fails fast and retries instead of hanging.
_INIT_PING_TIMEOUT: float = 5.0          # per-new-connection warm SELECT 1 budget
_POOL_CONNECT_ATTEMPTS: int = 5          # create_pool tries before giving up
_POOL_CONNECT_BASE_DELAY: float = 1.0    # exp-backoff base between attempts (s)
_POOL_CONNECT_MAX_DELAY: float = 16.0    # exp-backoff cap (s)


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Warm-ping every new pool connection on creation.

    Surfaces broken connections (e.g. Supabase idle-timeout recycled backends)
    at pool-init time rather than mid-request, so the pool health check in
    /health and job_runs write paths never hit a silently dead connection.
    asyncpg calls this coroutine once per new physical backend connection.

    Bounded by an explicit timeout: a hung/recycled Supabase backend whose
    ``SELECT 1`` never returns must fail FAST so asyncpg discards that backend
    and opens a fresh one, rather than wedging the acquiring coroutine (the
    boot-time stall that froze /health on 2026-06-07).
    """
    await asyncio.wait_for(conn.execute("SELECT 1"), timeout=_INIT_PING_TIMEOUT)


async def init_pool() -> asyncpg.Pool:
    global _pool
    if _pool is not None:
        return _pool
    settings = get_settings()
    _warn_if_supavisor_transaction_pool(settings.DATABASE_URL)
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
    # other workloads sharing the project.
    # Bounded connect-retry with exponential backoff: a transient Supabase /
    # Supavisor connect stall at boot must retry rather than yield a half-dead
    # pool or hang the lifespan. Only connectivity-class errors are retried;
    # after the budget is exhausted we re-raise (no silent failure) so the
    # process exits and Fly restarts it cleanly instead of running DB-blind.
    last_exc: BaseException | None = None
    for attempt in range(1, _POOL_CONNECT_ATTEMPTS + 1):
        try:
            _pool = await asyncpg.create_pool(
                dsn=settings.DATABASE_URL,
                min_size=2,
                max_size=settings.DB_POOL_MAX,
                max_inactive_connection_lifetime=300.0,
                command_timeout=30,
                statement_cache_size=0,
                timeout=10,
                init=_init_connection,
                server_settings={"application_name": "crusaderbot"},
            )
            logger.info(
                "asyncpg pool initialised (max=%s, attempt=%s/%s)",
                settings.DB_POOL_MAX, attempt, _POOL_CONNECT_ATTEMPTS,
            )
            return _pool
        except (OSError, asyncio.TimeoutError, asyncpg.PostgresError) as exc:
            last_exc = exc
            if attempt >= _POOL_CONNECT_ATTEMPTS:
                break
            delay = min(
                _POOL_CONNECT_BASE_DELAY * (2 ** (attempt - 1)),
                _POOL_CONNECT_MAX_DELAY,
            )
            logger.warning(
                "asyncpg pool init attempt %s/%s failed (%s: %s) — retrying in %.1fs",
                attempt, _POOL_CONNECT_ATTEMPTS, type(exc).__name__, exc, delay,
            )
            await asyncio.sleep(delay)
    logger.error(
        "asyncpg pool init FAILED after %s attempts — re-raising for clean restart",
        _POOL_CONNECT_ATTEMPTS,
    )
    assert last_exc is not None
    raise last_exc


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Database pool not initialised — call init_pool() first.")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# Migration tracking. Before WARP-80's RCA the runner had NO tracker and re-ran
# EVERY migrations/*.sql on every boot, relying purely on per-file idempotency,
# and a single failure aborted the whole batch — which is how migration 086 was
# silently skipped and (worse) crash-looped the boot. The tracker records each
# applied file (filename + content checksum) so the runner only applies NEW files
# and an operator can SEE from the DB what ran (the table CMD looked for and did
# not find). Created in-code (CREATE TABLE IF NOT EXISTS) rather than as a .sql
# migration so it bootstraps before any migration is consulted.
_SCHEMA_MIGRATIONS_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename   TEXT PRIMARY KEY,
    checksum   TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

# Session-level advisory-lock key serializing concurrent migration runs. The
# lifespan calls run_migrations on EVERY app machine at boot, so a rolling /
# immediate deploy (or a scale-up) can boot replicas concurrently — without this
# they would race on the same pending files (UniqueViolation / duplicate apply).
# A session-scoped lock makes the others wait, then see a fully-populated tracker
# and skip-all; it auto-releases if the holder's connection dies.
_MIGRATION_ADVISORY_LOCK_KEY = 789234101


def _discover_migrations(migrations_dir: Path) -> list[Path]:
    """All ``*.sql`` files in ``migrations_dir``, sorted by filename.

    Sorted-by-name is the application order (the 0NN_ prefix encodes sequence);
    this is unchanged from the historical runner so order never shifts.
    """
    return sorted(migrations_dir.glob("*.sql"))


def _migration_checksum(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


async def _load_applied_migrations(conn) -> dict[str, str]:
    """Return ``{filename: checksum}`` already recorded in ``schema_migrations``."""
    rows = await conn.fetch("SELECT filename, checksum FROM schema_migrations")
    return {str(r["filename"]): str(r["checksum"]) for r in rows}


async def _apply_pending_migrations(
    conn, files: list[Path], applied: dict[str, str]
) -> tuple[list[str], list[str]]:
    """Apply every file not yet in ``applied``; record each on success.

    Returns ``(newly_applied, checksum_mismatches)``. Already-applied files are
    skipped (a checksum drift is WARNED, never silently re-run — migrations are
    append-only by convention). A genuine SQL error is logged WITH the offending
    filename and re-raised (fail-loud) so the deploy ``release_command`` fails the
    deploy rather than the app crash-looping. Each migration autocommits (no outer
    transaction — matches the historical runner so statements that cannot run in a
    transaction, e.g. enum ``ADD VALUE``, keep working); files applied before a
    failure stay recorded so the next run resumes instead of restarting.
    """
    newly: list[str] = []
    mismatches: list[str] = []
    for f in files:
        sql = f.read_text(encoding="utf-8")
        checksum = _migration_checksum(sql)
        if f.name in applied:
            if applied[f.name] != checksum:
                logger.warning(
                    "Migration %s checksum changed since it was applied "
                    "(recorded %s, now %s) — NOT re-run; migrations must be "
                    "append-only. Add a new migration to alter schema.",
                    f.name, applied[f.name][:12], checksum[:12],
                )
                mismatches.append(f.name)
            continue
        logger.info("Applying migration %s", f.name)
        try:
            await conn.execute(sql)
        except Exception as exc:
            logger.error("Migration failed: %s — %s", f.name, exc, exc_info=True)
            raise
        await conn.execute(
            "INSERT INTO schema_migrations (filename, checksum) VALUES ($1, $2) "
            "ON CONFLICT (filename) DO UPDATE SET checksum = EXCLUDED.checksum, "
            "applied_at = NOW()",
            f.name, checksum,
        )
        newly.append(f.name)
    return newly, mismatches


async def run_migrations(
    *, migrations_dir: Path | None = None, pool: asyncpg.Pool | None = None
) -> list[str]:
    """Apply pending SQL migrations, tracked in ``schema_migrations``. Idempotent.

    Returns the filenames applied THIS run (empty when the DB is already current).
    Re-raises on a migration error (fail-loud) so the deploy ``release_command``
    surfaces it. A session-level advisory lock serializes concurrent runs across
    replicas. ``migrations_dir`` / ``pool`` are injectable for tests.
    """
    pool = pool or await init_pool()
    md = migrations_dir or MIGRATIONS_DIR
    files = _discover_migrations(md)
    if not files:
        logger.warning("No migration files found in %s", md)
        return []
    try:
        async with pool.acquire() as conn:
            # Serialize concurrent migration runs (rolling/immediate deploys boot
            # replicas in parallel); others block here then skip-all once the
            # tracker is populated. Released in finally + on connection close.
            await conn.execute("SELECT pg_advisory_lock($1)", _MIGRATION_ADVISORY_LOCK_KEY)
            try:
                await conn.execute(_SCHEMA_MIGRATIONS_DDL)
                applied = await _load_applied_migrations(conn)
                newly, mismatches = await _apply_pending_migrations(conn, files, applied)
            finally:
                await conn.execute("SELECT pg_advisory_unlock($1)", _MIGRATION_ADVISORY_LOCK_KEY)
    except Exception as exc:
        logger.error("run_migrations failed: %s", exc, exc_info=True)
        raise
    logger.info(
        "Migrations complete: %d applied this run, %d already present, %d total%s",
        len(newly), len(files) - len(newly), len(files),
        f", {len(mismatches)} checksum mismatch(es)" if mismatches else "",
    )
    return newly


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
        async with pool.acquire(timeout=4.5) as conn:
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
