"""Async token-bucket rate limiter for the Polymarket CLOB outbound surface.

Throttles locally to stay below the broker's per-account limit so the
adapter never trips a 429 in the steady state. Burst capacity equals the
configured ``rps``; refill is continuous (1 token per ``1/rps`` seconds).

Acquire semantics: ``await acquire()`` blocks until a token is available.
``rps <= 0`` disables the limiter entirely (acquire is a no-op) -- used
in unit tests that exercise downstream behavior without sleeping.

Test seam: ``clock`` and ``sleep`` are injectable so tests can advance a
virtual clock instead of doing real ``asyncio.sleep`` calls.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)


class RateLimiter:
    """Token-bucket limiter tuned for steady ``rps`` requests per second.

    A single instance covers every outbound CLOB call; share via the
    factory singleton in ``integrations.clob.__init__`` so unrelated
    adapters built in the same process throttle against the same bucket.
    """

    def __init__(
        self,
        *,
        rps: float = 10.0,
        burst: float | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._rps = float(rps)
        # burst capacity defaults to one full second of throughput; this
        # absorbs short order-burst patterns without giving up steady-state
        # back-pressure.
        if burst is None:
            self._burst = max(1.0, float(rps)) if rps > 0 else 0.0
        else:
            self._burst = float(burst)
        self._tokens = self._burst
        self._last_refill = clock()
        self._clock = clock
        self._sleep = sleep
        self._lock = asyncio.Lock()

    @property
    def rps(self) -> float:
        return self._rps

    @property
    def burst(self) -> float:
        return self._burst

    @property
    def tokens(self) -> float:
        """Current bucket level after refill. Read-only -- snapshot for
        the ops dashboard / tests.
        """
        self._refill()
        return self._tokens

    def _refill(self) -> None:
        if self._rps <= 0:
            return
        now = self._clock()
        elapsed = now - self._last_refill
        if elapsed > 0:
            self._tokens = min(self._burst, self._tokens + elapsed * self._rps)
            self._last_refill = now

    async def acquire(self, n: float = 1.0) -> None:
        """Block until ``n`` tokens are available, then deduct them.

        ``rps <= 0`` short-circuits to a no-op -- callers in unit tests
        skip throttling without re-wiring every adapter.
        """
        if self._rps <= 0:
            return
        if n <= 0:
            return
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= n:
                    self._tokens -= n
                    return
                deficit = n - self._tokens
                wait_for = deficit / self._rps if self._rps > 0 else 0.0
            # release the lock before sleeping so concurrent waiters can
            # also re-check after the refill window.
            await self._sleep(max(wait_for, 0.0))

    def snapshot(self) -> dict[str, float]:
        """Read-only view for the ops dashboard."""
        self._refill()
        return {
            "rps": self._rps,
            "burst": self._burst,
            "tokens": self._tokens,
        }
