"""Operational-table retention — keep the DB from growing without bound.

WARP•R00T hardening (follow-up to the WARP-82 disk-full read-only P0). WARP-82
killed the high-volume realtime *bloat* writers and dropped their tables; this job
closes the remaining gap: the ordinary operational time-series tables
(``system_alerts``, ``scan_runs``, ``portfolio_snapshots``, ``execution_queue``,
``idempotency_keys``) have NO TTL and accrue forever (e.g. portfolio_snapshots
~1.8k rows/day). ``disk_monitor`` only *alerts* on the 500 MB cap — it never frees
space. This job prunes rows beyond a generous per-table retention window so the DB
self-limits, long before the disk guard ever fires.

Design (matches ``jobs/disk_monitor.py``):
  * Pure asyncio (never threading — AGENTS.md invariant).
  * Fail-soft per table: one table erroring is logged + sent to Sentry and
    swallowed; the remaining tables still prune; the scheduler is never crashed.
  * Bounded batched DELETE (``ctid`` slices, ``_BATCH`` rows) so a large backlog
    cannot hold a long table lock.
  * Idempotent: re-running only deletes what is now beyond the window.

Deliberately NOT pruned here:
  * ``audit.log`` — compliance audit trail (separate, owner-governed retention).
  * ``positions`` / ``orders`` / ``ledger`` / ``fills`` / ``fees`` / ``markets`` /
    ``factor_vectors`` — core trading + FK-entangled + the EV research dataset.
Windows are config-driven (env-overridable); ``DB_RETENTION_ENABLED`` gates it.
"""
from __future__ import annotations

import logging
from typing import Any

from ..config import get_settings
from ..database import get_pool

logger = logging.getLogger(__name__)

JOB_ID = "db_retention"

# Max rows deleted per statement, so a big backlog never holds a long lock.
_BATCH: int = 5000
# Safety ceiling on batch iterations per table per run (5000 * 200 = 1M rows/run).
_MAX_ITERS: int = 200


async def _prune(conn: Any, table: str, where: str, *params: Any) -> int:
    """Batched DELETE of rows matching ``where``; returns total rows deleted.

    ``table`` / ``where`` are module-internal constants (never caller/DB input) so
    the f-string interpolation carries no injection surface; row values are bound
    via ``$n`` parameters. Deletes in ``_BATCH`` slices via ``ctid`` to bound lock
    duration on large tables.
    """
    total = 0
    sql = (
        f"DELETE FROM {table} WHERE ctid = ANY(ARRAY("
        f"SELECT ctid FROM {table} WHERE {where} LIMIT {_BATCH}))"
    )
    for _ in range(_MAX_ITERS):
        status = await conn.execute(sql, *params)
        # asyncpg returns e.g. "DELETE 4321"; parse the affected-row count.
        try:
            deleted = int(status.split()[-1])
        except (ValueError, IndexError):
            deleted = 0
        total += deleted
        if deleted < _BATCH:
            break
    else:
        # Hit the per-run iteration ceiling — a backlog remains; surface it (not
        # silent) so the next daily run / an operator knows to expect more.
        logger.warning(
            "db_retention: hit %d-iteration ceiling for %s (%d rows pruned this "
            "run; backlog remains for the next run)", _MAX_ITERS, table, total,
        )
    return total


# (table, where-clause, params). ``where`` uses $1 for the retention-day count
# where applicable; ``params`` is bound positionally (empty for idempotency_keys,
# which keys off its own expires_at). Returning a params tuple keeps _prune robust
# for any future table needing zero, one, or more bind params.
def _specs(s: Any) -> list[tuple[str, str, tuple[Any, ...]]]:
    return [
        # Expired dedup keys — expiry is their whole contract; always safe.
        ("idempotency_keys", "expires_at < NOW()", ()),
        ("system_alerts",
         "created_at < NOW() - ($1 * INTERVAL '1 day')",
         (s.DB_RETENTION_SYSTEM_ALERTS_DAYS,)),
        ("scan_runs",
         "started_at < NOW() - ($1 * INTERVAL '1 day')",
         (s.DB_RETENTION_SCAN_RUNS_DAYS,)),
        ("portfolio_snapshots",
         "snapshot_at < NOW() - ($1 * INTERVAL '1 day')",
         (s.DB_RETENTION_PORTFOLIO_SNAPSHOTS_DAYS,)),
        # Only already-executed queue rows (executed_at set) — never in-flight items.
        ("execution_queue",
         "executed_at IS NOT NULL AND queued_at < NOW() - ($1 * INTERVAL '1 day')",
         (s.DB_RETENTION_EXECUTION_QUEUE_DAYS,)),
    ]


async def run_job(*, pool: Any | None = None) -> dict[str, int]:
    """Prune operational tables beyond their retention windows.

    Returns ``{table: rows_deleted}`` for the tables that ran. Never raises — each
    table is fail-soft (logged + Sentry, then swallowed) so the scheduler and the
    other tables are unaffected by a single failure.
    """
    settings = get_settings()
    if not getattr(settings, "DB_RETENTION_ENABLED", True):
        logger.info("db_retention: disabled via DB_RETENTION_ENABLED")
        return {}

    deleted: dict[str, int] = {}
    try:
        pool = pool or get_pool()
    except Exception as exc:  # noqa: BLE001 — no pool, nothing to do; never crash
        logger.exception("db_retention: pool unavailable: %s", exc)
        return {}

    for table, where, params in _specs(settings):
        try:
            async with pool.acquire() as conn:  # type: ignore[attr-defined]
                n = await _prune(conn, table, where, *params)
            deleted[table] = n
            if n:
                logger.info("db_retention: pruned %d rows from %s", n, table)
        except Exception as exc:  # noqa: BLE001 — one table must not abort the rest
            logger.exception("db_retention: prune failed for %s: %s", table, exc)
            try:
                import sentry_sdk
                sentry_sdk.capture_exception(exc)
            except Exception:  # noqa: BLE001 — Sentry optional
                pass

    if deleted:
        logger.info("db_retention: run complete totals=%s", deleted)
    return deleted


__all__ = ["run_job", "JOB_ID"]
