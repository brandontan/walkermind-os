"""Hermetic tests for the job_tracker module (WARP-82: in-memory, no DB).

mark/pop race-fix coverage is retained; the former job_runs INSERT tests are
replaced with in-memory-ring assertions (WARP-82 killed durable job persistence).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from projects.polymarket.crusaderbot.domain.ops import job_tracker


def _run(coro):
    return asyncio.run(coro)


def test_mark_and_pop_round_trip():
    job_tracker._started_at.clear()
    job_tracker.mark_job_submitted("market_sync")
    popped = job_tracker.pop_job_start("market_sync")
    assert isinstance(popped, datetime)
    assert job_tracker.pop_job_start("market_sync") is None


def test_pop_isolates_concurrent_executions():
    job_tracker._started_at.clear()
    job_tracker.mark_job_submitted("redeem")
    first = job_tracker.pop_job_start("redeem")
    job_tracker.mark_job_submitted("redeem")
    second = job_tracker.pop_job_start("redeem")
    assert first is not None and second is not None
    assert second >= first


def test_pop_returns_none_when_nothing_marked():
    job_tracker._started_at.clear()
    assert job_tracker.pop_job_start("never-marked") is None


# ── WARP-82: in-memory ring, no DB ──────────────────────────────────────────────

def test_record_job_event_rings_success_no_db():
    job_tracker._recent_runs.clear()
    started = datetime(2026, 5, 5, 0, 0, 0, tzinfo=timezone.utc)
    finished = datetime(2026, 5, 5, 0, 0, 1, tzinfo=timezone.utc)
    _run(job_tracker.record_job_event(
        job_id="market_sync", success=True, started_at=started, finished_at=finished,
    ))
    latest = _run(job_tracker.fetch_latest("market_sync"))
    assert latest is not None
    assert latest["status"] == "success"
    assert latest["started_at"] == started and latest["finished_at"] == finished
    assert latest["error"] is None
    assert latest["duration_ms"] == 1000


def test_record_job_event_rings_failure_only_failed():
    job_tracker._recent_runs.clear()
    _run(job_tracker.record_job_event(job_id="redeem", success=False, error="boom"))
    failed = _run(job_tracker.fetch_recent(10, only_failed=True))
    assert failed and failed[0]["job_name"] == "redeem"
    assert failed[0]["status"] == "failed" and failed[0]["error"] == "boom"


def test_record_job_event_does_not_clobber_next_runs_start():
    """Explicit started_at short-circuits the pop, leaving a fresh slot intact."""
    job_tracker._started_at.clear()
    next_run_started = datetime(2026, 5, 5, 12, 0, 0, tzinfo=timezone.utc)
    job_tracker._started_at["redeem"] = next_run_started
    _run(job_tracker.record_job_event(
        job_id="redeem", success=True,
        started_at=datetime(2026, 5, 5, 11, 59, 0, tzinfo=timezone.utc),
        finished_at=datetime(2026, 5, 5, 11, 59, 30, tzinfo=timezone.utc),
    ))
    assert job_tracker._started_at.get("redeem") == next_run_started


def test_record_job_event_never_raises_and_no_get_pool():
    # WARP-82 removed the DB dependency entirely — there is no get_pool to hit.
    assert not hasattr(job_tracker, "get_pool")
    _run(job_tracker.record_job_event(job_id="redeem", success=False, error="x"))


def test_fetch_recent_zero_limit_returns_empty():
    assert _run(job_tracker.fetch_recent(0)) == []


# ── hour-window aggregates (back /health + hourly_report after job_runs drop) ──

def _seed_ring() -> datetime:
    """Seed the ring with a fixed mix; return a `since` cutoff at T-30m."""
    job_tracker._recent_runs.clear()
    now = datetime.now(timezone.utc)
    from datetime import timedelta
    def at(mins_ago: int):
        return now - timedelta(minutes=mins_ago)
    # 2 scanner successes + 1 scanner failure inside window; 1 scanner before it
    _run(job_tracker.record_job_event(job_id="market_signal_scanner", success=True, started_at=at(5), finished_at=at(5)))
    _run(job_tracker.record_job_event(job_id="market_signal_scanner", success=True, started_at=at(10), finished_at=at(10)))
    _run(job_tracker.record_job_event(job_id="market_signal_scanner", success=False, error="e", started_at=at(15), finished_at=at(15)))
    _run(job_tracker.record_job_event(job_id="redeem", success=True, started_at=at(20), finished_at=at(20)))
    _run(job_tracker.record_job_event(job_id="market_signal_scanner", success=True, started_at=at(90), finished_at=at(90)))
    return now - timedelta(minutes=30)


def test_count_runs_since_total_and_filtered():
    since = _seed_ring()
    # 4 runs inside the 30m window (the 90m-old scanner run is excluded).
    assert _run(job_tracker.count_runs_since(since)) == 4
    assert _run(job_tracker.count_runs_since(since, job_id="market_signal_scanner")) == 3
    assert _run(job_tracker.count_runs_since(since, only_failed=True)) == 1


def test_distinct_jobs_since():
    since = _seed_ring()
    # Two distinct job names inside the window: scanner + redeem.
    assert _run(job_tracker.distinct_jobs_since(since)) == 2
