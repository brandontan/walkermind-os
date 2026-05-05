"""Hermetic tests for the R12f job_tracker module.

Covers the SUBMITTED/EXECUTED race fix Codex flagged on PR #874:
``pop_job_start`` removes the slot so a fresh SUBMITTED for the same
job_id cannot cross-contaminate the next completion's started_at.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from projects.polymarket.crusaderbot.domain.ops import job_tracker


def test_mark_and_pop_round_trip():
    job_tracker._started_at.clear()
    job_tracker.mark_job_submitted("market_sync")
    popped = job_tracker.pop_job_start("market_sync")
    assert isinstance(popped, datetime)
    # Pop is destructive — second pop returns None.
    assert job_tracker.pop_job_start("market_sync") is None


def test_pop_isolates_concurrent_executions():
    """After pop, a fresh SUBMITTED creates an independent slot.

    This is the regression test for the race Codex flagged: a second
    SUBMITTED that arrives while the prior EXECUTED's create_task is
    still queued must NOT corrupt the prior run's started_at.
    """
    job_tracker._started_at.clear()
    job_tracker.mark_job_submitted("redeem")
    first = job_tracker.pop_job_start("redeem")
    # Listener forwarded ``first`` into record_job_event already; the
    # next SUBMITTED arrives and writes a fresh slot.
    job_tracker.mark_job_submitted("redeem")
    second = job_tracker.pop_job_start("redeem")
    assert first is not None and second is not None
    # The two timestamps are independent — first run's value is intact.
    assert second >= first


def test_pop_returns_none_when_nothing_marked():
    job_tracker._started_at.clear()
    assert job_tracker.pop_job_start("never-marked") is None


def test_record_job_event_uses_explicit_started_at():
    """When the listener forwards started_at, record uses it verbatim."""
    captured: list[tuple] = []

    async def fake_execute(self, query, *args):
        captured.append((query, args))
        return None

    class FakeConn:
        async def execute(self, query, *args):
            captured.append((query, args))

    class FakeAcquire:
        async def __aenter__(self):
            return FakeConn()

        async def __aexit__(self, *_):
            return False

    class FakePool:
        def acquire(self):
            return FakeAcquire()

    started = datetime(2026, 5, 5, 0, 0, 0, tzinfo=timezone.utc)
    finished = datetime(2026, 5, 5, 0, 0, 1, tzinfo=timezone.utc)
    with patch.object(job_tracker, "get_pool", return_value=FakePool()):
        asyncio.run(job_tracker.record_job_event(
            job_id="market_sync", success=True,
            started_at=started, finished_at=finished,
        ))
    # Exactly one INSERT with our explicit timestamps in args.
    inserts = [c for c in captured if "INSERT INTO job_runs" in c[0]]
    assert len(inserts) == 1
    args = inserts[0][1]
    assert args[0] == "market_sync"
    assert args[1] == "success"
    assert args[2] == started
    assert args[3] == finished
    assert args[4] is None  # error


def test_record_job_event_swallows_db_errors():
    class BoomPool:
        def acquire(self):
            raise RuntimeError("DB blip")

    with patch.object(job_tracker, "get_pool", return_value=BoomPool()):
        # Must not raise — observability cannot break the scheduler.
        asyncio.run(job_tracker.record_job_event(
            job_id="redeem", success=False, error="x",
        ))


def test_fetch_recent_zero_limit_returns_empty():
    with patch.object(job_tracker, "get_pool",
                      side_effect=AssertionError("pool must not be hit")):
        out = asyncio.run(job_tracker.fetch_recent(0))
    assert out == []
