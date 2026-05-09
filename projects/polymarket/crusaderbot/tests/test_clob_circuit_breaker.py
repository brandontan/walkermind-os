"""Unit tests for CircuitBreaker -- state transitions, no-call when OPEN,
on_open callback, and snapshot exposure.
"""
from __future__ import annotations

import asyncio

import pytest

from projects.polymarket.crusaderbot.integrations.clob.circuit_breaker import (
    CircuitBreaker,
    STATE_CLOSED,
    STATE_HALF_OPEN,
    STATE_OPEN,
)
from projects.polymarket.crusaderbot.integrations.clob.exceptions import (
    ClobAuthError,
    ClobCircuitOpenError,
    ClobNetworkError,
    ClobServerError,
    ClobTimeoutError,
)


pytestmark = pytest.mark.asyncio


class _Clock:
    """Manual monotonic clock so tests don't sleep."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def _make_breaker(
    *,
    threshold: int = 3,
    reset_seconds: float = 30.0,
    on_open=None,
    clock=None,
) -> CircuitBreaker:
    return CircuitBreaker(
        threshold=threshold,
        reset_seconds=reset_seconds,
        on_open=on_open,
        name="test",
        clock=clock or _Clock(),
    )


# --- success path -------------------------------------------------


async def test_closed_breaker_passes_through_and_resets_failures():
    cb = _make_breaker()

    async def ok():
        return "result"

    out = await cb.call(ok)
    assert out == "result"
    assert cb.state == STATE_CLOSED
    assert cb.failure_count == 0


async def test_failure_increments_counter_but_stays_closed_below_threshold():
    cb = _make_breaker(threshold=3)

    async def fail():
        raise ClobServerError(status_code=503, path="/order", body="boom")

    for _ in range(2):
        with pytest.raises(ClobServerError):
            await cb.call(fail)
    assert cb.state == STATE_CLOSED
    assert cb.failure_count == 2


# --- CLOSED -> OPEN ----------------------------------------------


async def test_threshold_failures_trip_breaker_and_fire_on_open_once():
    fired = []

    async def on_open(name):
        fired.append(name)

    cb = _make_breaker(threshold=3, on_open=on_open)

    async def fail():
        raise ClobNetworkError("conn reset")

    for _ in range(3):
        with pytest.raises(ClobNetworkError):
            await cb.call(fail)
    assert cb.state == STATE_OPEN
    assert fired == ["test"]


async def test_open_breaker_rejects_without_calling_underlying():
    cb = _make_breaker(threshold=2)

    calls = {"n": 0}

    async def fail():
        calls["n"] += 1
        raise ClobTimeoutError("timed out")

    for _ in range(2):
        with pytest.raises(ClobTimeoutError):
            await cb.call(fail)
    assert cb.state == STATE_OPEN
    pre_calls = calls["n"]

    async def must_not_run():
        calls["n"] += 1
        return "should not happen"

    with pytest.raises(ClobCircuitOpenError):
        await cb.call(must_not_run)
    assert calls["n"] == pre_calls


# --- OPEN -> HALF_OPEN -> CLOSED on success -----------------------


async def test_half_open_after_reset_window_allows_trial():
    clock = _Clock()
    cb = _make_breaker(threshold=2, reset_seconds=10.0, clock=clock)

    async def fail():
        raise ClobServerError(status_code=503, path="/order", body="x")

    for _ in range(2):
        with pytest.raises(ClobServerError):
            await cb.call(fail)
    assert cb.state == STATE_OPEN
    clock.advance(10.0)
    assert cb.current_state() == STATE_HALF_OPEN

    async def ok():
        return "ok"

    out = await cb.call(ok)
    assert out == "ok"
    assert cb.state == STATE_CLOSED
    assert cb.failure_count == 0


# --- HALF_OPEN -> OPEN on failed trial ----------------------------


async def test_half_open_failure_re_opens_and_resets_timer():
    clock = _Clock()
    fired = []

    async def on_open(name):
        fired.append(name)

    cb = _make_breaker(
        threshold=2, reset_seconds=10.0, on_open=on_open, clock=clock,
    )

    async def fail():
        raise ClobServerError(status_code=503, path="/x", body="")

    for _ in range(2):
        with pytest.raises(ClobServerError):
            await cb.call(fail)
    assert fired == ["test"]
    clock.advance(11.0)
    assert cb.current_state() == STATE_HALF_OPEN

    with pytest.raises(ClobServerError):
        await cb.call(fail)
    assert cb.state == STATE_OPEN
    # on_open fires again on the half-open re-trip
    assert fired == ["test", "test"]


# --- auth errors do NOT count toward breaker ----------------------


async def test_auth_error_does_not_count_toward_breaker():
    cb = _make_breaker(threshold=2)

    async def auth_fail():
        raise ClobAuthError("401 invalid signature")

    for _ in range(5):
        with pytest.raises(ClobAuthError):
            await cb.call(auth_fail)
    assert cb.state == STATE_CLOSED
    assert cb.failure_count == 0


# --- on_open swallow + snapshot ----------------------------------


async def test_on_open_callback_failure_is_swallowed():
    async def bad_callback(name):
        raise RuntimeError("telegram down")

    cb = _make_breaker(threshold=1, on_open=bad_callback)

    async def fail():
        raise ClobNetworkError("nope")

    with pytest.raises(ClobNetworkError):
        await cb.call(fail)
    assert cb.state == STATE_OPEN  # callback failure must not regress state


async def test_snapshot_returns_observable_state():
    clock = _Clock()
    cb = _make_breaker(threshold=2, reset_seconds=10.0, clock=clock)

    async def fail():
        raise ClobServerError(status_code=503, path="/x", body="")

    with pytest.raises(ClobServerError):
        await cb.call(fail)

    snap = cb.snapshot()
    assert snap["state"] == STATE_CLOSED
    assert snap["failures"] == 1
    assert snap["threshold"] == 2

    with pytest.raises(ClobServerError):
        await cb.call(fail)
    snap = cb.snapshot()
    assert snap["state"] == STATE_OPEN
    assert snap["seconds_until_half_open"] == pytest.approx(10.0)


def test_invalid_threshold_raises():
    with pytest.raises(ValueError):
        CircuitBreaker(threshold=0, reset_seconds=10.0)


async def test_force_close_resets_state():
    cb = _make_breaker(threshold=1)

    async def fail():
        raise ClobNetworkError("x")

    with pytest.raises(ClobNetworkError):
        await cb.call(fail)
    assert cb.state == STATE_OPEN

    cb.force_close()
    assert cb.state == STATE_CLOSED
    assert cb.failure_count == 0
