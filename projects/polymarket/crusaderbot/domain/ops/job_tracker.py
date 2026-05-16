"""APScheduler -> job_runs bridge.

A single listener is registered on the scheduler in ``setup_scheduler``.
Every job execution writes one row to ``job_runs`` with status, duration,
and (on failure) the truncated error message. The /jobs operator command
reads from this table directly — no in-memory state.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from ...database import get_pool

logger = logging.getLogger(__name__)


# Per-job-id start timestamps captured in the scheduler's ``_job_submitted``
# callback so the listener can compute duration without depending on
# APScheduler's internal scheduled_run_time vs. wallclock skew. Keys are
# job ids; values are aware UTC datetimes.
#
# The listener pops this value SYNCHRONOUSLY on EVENT_JOB_EXECUTED /
# EVENT_JOB_ERROR and forwards it as a parameter to ``record_job_event``
# (which is dispatched via ``loop.create_task``). The synchronous pop
# avoids a race where a fresh SUBMITTED event for the same job_id
# overwrites the slot before the prior completion's create_task gets to
# read it — APScheduler's ``max_instances=1, coalesce=True`` only
# guarantees serial execution; the EVENT delivery + create_task
# scheduling boundary is still racy.
_started_at: dict[str, datetime] = {}


def mark_job_submitted(job_id: str) -> None:
    """Record the wallclock start of a job execution."""
    _started_at[job_id] = datetime.now(timezone.utc)


def pop_job_start(job_id: str) -> Optional[datetime]:
    """Synchronous pop of the SUBMITTED-time wallclock for a job id.

    Returned to the scheduler listener so the start timestamp is
    captured at EXECUTED-event delivery (before the next SUBMITTED can
    overwrite the slot). The returned value is then passed into
    ``record_job_event`` as the ``started_at`` parameter.
    """
    return _started_at.pop(job_id, None)


async def record_job_event(
    *,
    job_id: str,
    success: bool,
    error: Optional[str] = None,
    started_at: Optional[datetime] = None,
    finished_at: Optional[datetime] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    """Persist a single job execution outcome.

    Failure to write must NEVER bubble up — observability cannot break
    the trading loop. ``error`` is truncated to 500 chars to bound the
    row size; the operator dashboard further truncates to 80 chars when
    rendering. ``metadata`` is an optional dict written to the JSONB column
    (e.g. RunResult counts from exit_watch: submitted/expired/held/errors).
    """
    # ``started_at`` is normally captured synchronously by the scheduler
    # listener via ``pop_job_start`` to defeat the SUBMITTED-overwrite
    # race. We still fall back to the dict + wallclock so a direct
    # caller (e.g. unit tests, or a future code path) that omits the
    # parameter degrades gracefully rather than crashing.
    started = (
        started_at
        or _started_at.pop(job_id, None)
        or datetime.now(timezone.utc)
    )
    finished = finished_at or datetime.now(timezone.utc)
    status = "success" if success else "failed"
    err = (error or "")[:500] if not success else None
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO job_runs (job_name, status, started_at, "
                "finished_at, error, metadata) VALUES ($1, $2, $3, $4, $5, $6)",
                job_id, status, started, finished, err, metadata,
            )
    except Exception as exc:
        # Don't crash the scheduler loop because the ops table is down.
        logger.error("job_runs write failed for %s: %s", job_id, exc)
    # NOTE: no finally cleanup of ``_started_at[job_id]``. The scheduler
    # listener already pops via ``pop_job_start`` on EXECUTED/ERROR
    # delivery, and the test-direct fallback above pops as part of the
    # ``or`` chain. A late cleanup here was racy — a fresh SUBMITTED for
    # the same job_id could arrive before this async DB write finishes,
    # writing the new run's timestamp into the slot, and the cleanup
    # would then erase the next run's start time (Codex P1 follow-up
    # on PR #874).


async def fetch_recent(limit: int = 10, *, only_failed: bool = False) -> list[dict[str, Any]]:
    """Return the most recent job runs, newest first."""
    if limit <= 0:
        return []
    pool = get_pool()
    where = "WHERE status='failed' " if only_failed else ""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT job_name, status, started_at, finished_at, error, metadata "
            f"FROM job_runs {where}"
            f"ORDER BY started_at DESC LIMIT $1",
            limit,
        )
    return [dict(r) for r in rows]
