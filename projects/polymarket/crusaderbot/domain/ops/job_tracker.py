"""APScheduler -> structured-log bridge (WARP-82: no durable job_runs).

A single listener is registered on the scheduler in ``setup_scheduler``.
Every job execution emits structured stdout log lines (job.start / job.end /
job.error) and, on error, a Sentry capture — NO database row. The legacy
``job_runs`` table is dropped (WARP-82 kill-realtime-persistence); the operator
panel reads recent runs from an in-memory ring instead of the DB so it keeps
working without durable storage.
"""
from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Optional

logger = logging.getLogger(__name__)

# In-memory, non-durable ring of recent job outcomes. Bounded so it can never
# grow unbounded in memory (the whole point of WARP-82 — no unbounded growth).
# Per-process (resets on restart) — acceptable for operator job-status display.
# Sized to comfortably cover ~1h of high-frequency scheduler ticks so the
# hour-window aggregates below (count_runs_since / distinct_jobs_since), which
# now back /health + the hourly report after job_runs was dropped, stay
# representative rather than truncated.
_RECENT_MAXLEN = 1000
_recent_runs: Deque[dict[str, Any]] = deque(maxlen=_RECENT_MAXLEN)


# Per-job-id start timestamps captured in the scheduler's ``_job_submitted``
# callback so the listener can compute duration. Keys are job ids; values are
# aware UTC datetimes. Popped synchronously by ``pop_job_start`` (see below).
_started_at: dict[str, datetime] = {}


def mark_job_submitted(job_id: str) -> None:
    """Record the wallclock start of a job execution + emit a start log line."""
    _started_at[job_id] = datetime.now(timezone.utc)
    logger.info("job.start name=%s scheduled_at=%s", job_id, _started_at[job_id].isoformat())


def pop_job_start(job_id: str) -> Optional[datetime]:
    """Synchronous pop of the SUBMITTED-time wallclock for a job id."""
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
    """Emit one job execution outcome to stdout (+ Sentry on error). No DB write.

    WARP-82: replaces the former job_runs write with a structured log
    line + a bounded in-memory ring (read by the operator panel). Never raises —
    observability must not break the scheduler loop.
    """
    started = started_at or _started_at.pop(job_id, None) or datetime.now(timezone.utc)
    finished = finished_at or datetime.now(timezone.utc)
    status = "success" if success else "failed"
    err = (error or "")[:500] if not success else None
    duration_ms = int((finished - started).total_seconds() * 1000)
    record = {
        "job_name": job_id, "status": status, "started_at": started,
        "finished_at": finished, "error": err, "metadata": metadata,
        "duration_ms": duration_ms,
    }
    try:
        _recent_runs.appendleft(record)
        if success:
            logger.info("job.end name=%s status=%s duration_ms=%d", job_id, status, duration_ms)
        else:
            logger.error("job.error name=%s duration_ms=%d err=%s", job_id, duration_ms, err)
            try:
                import sentry_sdk
                sentry_sdk.capture_message(
                    f"job.error {job_id}: {err}", level="error",
                )
            except Exception:  # noqa: BLE001 — sentry optional, never break the loop
                pass
    except Exception as exc:  # noqa: BLE001 — never crash the scheduler loop
        logger.error("record_job_event failed for %s: %s", job_id, exc)


async def fetch_latest(job_id: str) -> Optional[dict[str, Any]]:
    """Most recent in-memory outcome for ``job_id`` (operator panel). None if none.

    WARP-82: reads the in-memory ring, not ``job_runs`` (table dropped).
    """
    for r in _recent_runs:  # newest first (appendleft)
        if r.get("job_name") == job_id:
            return dict(r)
    return None


async def fetch_recent(limit: int = 10, *, only_failed: bool = False) -> list[dict[str, Any]]:
    """Most recent in-memory job outcomes, newest first. WARP-82: in-memory ring."""
    if limit <= 0:
        return []
    out: list[dict[str, Any]] = []
    for r in _recent_runs:
        if only_failed and r.get("status") != "failed":
            continue
        out.append(dict(r))
        if len(out) >= limit:
            break
    return out


async def count_runs_since(
    since: datetime, *, job_id: str | None = None, only_failed: bool = False
) -> int:
    """Count ring entries started after ``since`` (aware UTC), best-effort.

    Backs the former ``count(*)`` job_runs hour-window queries in /health and
    the hourly report now that the ``job_runs`` table is dropped.
    ``only_failed`` counts non-success outcomes (ring status is
    ``success`` / ``failed``). Bounded by the ring size — a count over a window
    longer than the ring retains is a lower bound, not exact.
    """
    n = 0
    for r in _recent_runs:
        ts = r.get("started_at")
        if ts is None or ts <= since:
            continue
        if job_id is not None and r.get("job_name") != job_id:
            continue
        if only_failed and r.get("status") == "success":
            continue
        n += 1
    return n


async def distinct_jobs_since(since: datetime) -> int:
    """Count distinct job names started after ``since`` (aware UTC). Best-effort.

    Backs the former ``count(DISTINCT job_name)`` job_runs query in /health
    (the "active jobs" figure) from the in-memory ring.
    """
    names: set[Any] = set()
    for r in _recent_runs:
        ts = r.get("started_at")
        if ts is None or ts <= since:
            continue
        names.add(r.get("job_name"))
    return len(names)

