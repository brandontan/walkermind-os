"""Async circuit breaker for the Polymarket CLOB outbound surface.

States
------

    CLOSED     normal -- requests flow through; consecutive failures count up.
    OPEN       tripped -- ``call`` raises ``ClobCircuitOpenError`` immediately
               with NO broker call. Auto half-opens after
               ``reset_seconds``.
    HALF_OPEN  one trial request is allowed through. Success closes the
               breaker (failure count reset to zero); failure re-opens it
               and restarts the cool-down clock.

Threshold: ``threshold`` consecutive failures from CLOSED transitions to
OPEN. Successes reset the failure counter. Only retryable broker-class
exceptions count as failures (the breaker should NOT trip on a 4xx auth
rejection -- that is an operator-credential issue, not a transport
incident).

Integration
-----------
Wraps ``ClobAdapter.post_order``, ``cancel_order``, and ``get_order``
via the ``call`` coroutine. Test seam: ``clock`` callable lets tests
fast-forward past the reset window without ``asyncio.sleep``.

When the breaker transitions to OPEN, the optional ``on_open`` callback
fires once. Failures inside the callback are logged at ERROR and
swallowed -- a Telegram outage must not keep the breaker stuck in
CLOSED. The ``on_open`` invocation is awaited (or scheduled if the
callback returns ``None`` synchronously) so test harnesses can assert it
fired exactly once per OPEN transition.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable, Optional, TypeVar

from .exceptions import (
    ClobAuthError,
    ClobCircuitOpenError,
    ClobMaxRetriesError,
    ClobNetworkError,
    ClobRateLimitError,
    ClobServerError,
    ClobTimeoutError,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")

STATE_CLOSED = "CLOSED"
STATE_OPEN = "OPEN"
STATE_HALF_OPEN = "HALF_OPEN"

# Exceptions that count as a "failure" for breaker purposes. Auth errors
# are intentionally excluded -- a stale signature is an operator problem,
# not a transport one, and tripping the breaker would mask the real cause.
FAILURE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    ClobRateLimitError,
    ClobServerError,
    ClobTimeoutError,
    ClobNetworkError,
    ClobMaxRetriesError,
)


class CircuitBreaker:
    """Async, instance-scoped circuit breaker.

    Construct one per outbound dependency. Concurrency-safe via an
    internal ``asyncio.Lock`` so two simultaneous failures cannot
    double-increment the counter or fire ``on_open`` twice.
    """

    def __init__(
        self,
        *,
        threshold: int = 5,
        reset_seconds: float = 60.0,
        on_open: Optional[Callable[[str], Awaitable[None]]] = None,
        name: str = "clob",
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if threshold <= 0:
            raise ValueError("CircuitBreaker threshold must be positive")
        if reset_seconds < 0:
            raise ValueError("CircuitBreaker reset_seconds must be non-negative")
        self._threshold = int(threshold)
        self._reset_seconds = float(reset_seconds)
        self._on_open = on_open
        self._name = name
        self._clock = clock
        self._state = STATE_CLOSED
        self._failures = 0
        self._opened_at = 0.0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> str:
        """Last-known state. Reading does NOT advance the half-open clock --
        callers wanting the live state should call ``current_state``.
        """
        return self._state

    @property
    def name(self) -> str:
        return self._name

    @property
    def failure_count(self) -> int:
        return self._failures

    def current_state(self) -> str:
        """Resolve the live state, transitioning OPEN -> HALF_OPEN if the
        reset window has elapsed. Safe to call from non-async contexts
        (the ops dashboard reads this synchronously).
        """
        if self._state == STATE_OPEN:
            if (self._clock() - self._opened_at) >= self._reset_seconds:
                self._state = STATE_HALF_OPEN
        return self._state

    async def call(self, fn: Callable[[], Awaitable[T]]) -> T:
        """Invoke ``fn`` under breaker control.

        Behavior by state:
            CLOSED    : run fn; on success reset failures; on failure
                        increment and trip if >= threshold.
            OPEN      : if reset window elapsed -> HALF_OPEN; otherwise
                        raise ``ClobCircuitOpenError`` with NO call.
            HALF_OPEN : allow one trial; success -> CLOSED + reset,
                        failure -> OPEN + restart cool-down.
        """
        async with self._lock:
            if self._state == STATE_OPEN:
                if (self._clock() - self._opened_at) >= self._reset_seconds:
                    self._state = STATE_HALF_OPEN
                else:
                    raise ClobCircuitOpenError(
                        f"circuit breaker '{self._name}' is OPEN "
                        f"({self._failures} consecutive failures)"
                    )

        try:
            result = await fn()
        except FAILURE_EXCEPTIONS as exc:
            await self._record_failure(exc)
            raise
        except ClobAuthError:
            # Auth-class rejection is operator-actionable, not transport.
            # Do NOT count toward the breaker; do NOT reset the counter
            # either (a 401 mid-incident shouldn't paper over a real
            # transport outage in progress).
            raise
        except BaseException:  # noqa: BLE001 -- propagate, do not count
            raise
        else:
            await self._record_success()
            return result

    async def _record_success(self) -> None:
        async with self._lock:
            if self._state == STATE_HALF_OPEN:
                logger.info(
                    "circuit breaker '%s' HALF_OPEN -> CLOSED on trial success",
                    self._name,
                )
            self._state = STATE_CLOSED
            self._failures = 0
            self._opened_at = 0.0

    async def _record_failure(self, exc: BaseException) -> None:
        fire_callback = False
        async with self._lock:
            if self._state == STATE_HALF_OPEN:
                logger.warning(
                    "circuit breaker '%s' HALF_OPEN trial failed (%s) -> OPEN",
                    self._name,
                    type(exc).__name__,
                )
                self._state = STATE_OPEN
                self._opened_at = self._clock()
                fire_callback = True
            else:
                self._failures += 1
                if self._failures >= self._threshold:
                    logger.error(
                        "circuit breaker '%s' tripping CLOSED -> OPEN "
                        "after %d consecutive failures (last=%s)",
                        self._name,
                        self._failures,
                        type(exc).__name__,
                    )
                    self._state = STATE_OPEN
                    self._opened_at = self._clock()
                    fire_callback = True
        if fire_callback and self._on_open is not None:
            try:
                await self._on_open(self._name)
            except Exception as cb_exc:  # noqa: BLE001 -- alert is best effort
                logger.error(
                    "circuit breaker '%s' on_open callback failed: %s",
                    self._name,
                    cb_exc,
                )

    def force_close(self) -> None:
        """Operator override -- reset to CLOSED. Used by tests and any
        future ``/ops/circuit-reset`` endpoint.
        """
        self._state = STATE_CLOSED
        self._failures = 0
        self._opened_at = 0.0

    def snapshot(self) -> dict[str, object]:
        """Read-only dict for the ops dashboard. Safe to call sync."""
        live_state = self.current_state()
        return {
            "name": self._name,
            "state": live_state,
            "failures": self._failures,
            "threshold": self._threshold,
            "reset_seconds": self._reset_seconds,
            "opened_at_monotonic": self._opened_at if self._opened_at else None,
            "seconds_until_half_open": (
                max(0.0, self._reset_seconds - (self._clock() - self._opened_at))
                if live_state == STATE_OPEN
                else 0.0
            ),
        }
