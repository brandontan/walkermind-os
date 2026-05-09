"""Unit tests for the token-bucket RateLimiter.

The tests use a manual ``_Clock`` and a ``_FakeSleep`` so no real
``asyncio.sleep`` ever fires -- each test runs to completion in <1ms.
"""
from __future__ import annotations

import pytest

from projects.polymarket.crusaderbot.integrations.clob.rate_limiter import (
    RateLimiter,
)


pytestmark = pytest.mark.asyncio


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class _FakeSleep:
    """Records every requested sleep + advances the clock so the limiter
    sees tokens replenish without real wall-clock waits.
    """

    def __init__(self, clock: _Clock) -> None:
        self.requested: list[float] = []
        self._clock = clock

    async def __call__(self, seconds: float) -> None:
        self.requested.append(seconds)
        self._clock.advance(seconds)


def _make(rps: float, burst: float | None = None):
    clock = _Clock()
    sleep = _FakeSleep(clock)
    rl = RateLimiter(rps=rps, burst=burst, clock=clock, sleep=sleep)
    return rl, clock, sleep


# --- under limit: passes through without sleeping -----------------


async def test_under_limit_does_not_sleep():
    rl, _, sleep = _make(rps=10.0, burst=5.0)
    for _ in range(5):
        await rl.acquire()
    assert sleep.requested == []
    # Bucket should now be near-empty.
    assert rl.tokens < 1.0


# --- at limit: throttles ------------------------------------------


async def test_at_limit_sleeps_to_refill():
    rl, _, sleep = _make(rps=10.0, burst=2.0)
    # Drain the bucket.
    for _ in range(2):
        await rl.acquire()
    assert sleep.requested == []
    # Next call must wait for one token to refill (1 token / 10 rps = 0.1s).
    await rl.acquire()
    assert sleep.requested  # at least one sleep happened
    assert sleep.requested[0] == pytest.approx(0.1, rel=0.01)


async def test_burst_then_steady_state():
    rl, clock, sleep = _make(rps=5.0, burst=3.0)
    for _ in range(3):
        await rl.acquire()
    assert sleep.requested == []
    # Advance the virtual clock a full second -> bucket refills to burst cap.
    clock.advance(1.0)
    for _ in range(3):
        await rl.acquire()
    # No additional sleeps because the refill carried us through the burst.
    assert sleep.requested == []


# --- disabled limiter is a no-op ----------------------------------


async def test_zero_rps_disables_limiter():
    rl, _, sleep = _make(rps=0.0)
    for _ in range(50):
        await rl.acquire()
    assert sleep.requested == []


async def test_negative_rps_disables_limiter():
    rl, _, sleep = _make(rps=-5.0)
    await rl.acquire()
    assert sleep.requested == []


# --- snapshot ------------------------------------------------------


async def test_snapshot_reflects_current_state():
    rl, clock, _ = _make(rps=10.0, burst=4.0)
    for _ in range(2):
        await rl.acquire()
    snap = rl.snapshot()
    assert snap["rps"] == 10.0
    assert snap["burst"] == 4.0
    # 2 tokens consumed, no time elapsed -> 2 left.
    assert snap["tokens"] == pytest.approx(2.0, rel=0.05)
    clock.advance(0.2)
    snap = rl.snapshot()
    # 0.2s @ 10rps = 2 tokens added -> back to 4 (capped at burst).
    assert snap["tokens"] == pytest.approx(4.0, rel=0.05)


async def test_acquire_zero_tokens_is_noop():
    rl, _, sleep = _make(rps=10.0, burst=1.0)
    await rl.acquire(0)
    assert sleep.requested == []
    assert rl.tokens == pytest.approx(1.0)
