"""Circuit breaker — Phase 6.

Unchanged from Phase 5. Trips on loss streaks, API failures,
or latency breaches. All record_* methods are async.
"""
from __future__ import annotations

import asyncio
import time

import structlog

from .event_bus import CIRCUIT_BREAKER_OPEN, EventBus, EventEnvelope

log = structlog.get_logger()


class CircuitBreaker:
    """Monitors trading health and halts the pipeline when thresholds are breached."""

    def __init__(
        self,
        bus: EventBus,
        max_consecutive_losses: int = 3,
        max_api_failures: int = 5,
        latency_breach_threshold_ms: int = 1000,
        cooldown_seconds: int = 120,
    ) -> None:
        """Initialise circuit breaker with configurable thresholds."""
        self._bus = bus
        self._max_consecutive_losses = max_consecutive_losses
        self._max_api_failures = max_api_failures
        self._latency_breach_threshold_ms = latency_breach_threshold_ms
        self._cooldown_seconds = cooldown_seconds

        self._is_open: bool = False
        self._opened_at: float = 0.0
        self._consecutive_losses: int = 0
        self._api_failures: int = 0

    def is_open(self) -> bool:
        """Return True if circuit is open. Auto-resets after cooldown."""
        if self._is_open:
            elapsed = time.time() - self._opened_at
            if elapsed >= self._cooldown_seconds:
                self._is_open = False
                self._consecutive_losses = 0
                self._api_failures = 0
                log.info("circuit_breaker_reset", elapsed_seconds=round(elapsed, 1))
        return self._is_open

    async def record_win(self) -> None:
        """Reset consecutive loss counter on a winning trade."""
        self._consecutive_losses = 0

    async def record_loss(self) -> None:
        """Increment loss counter; trip if threshold exceeded."""
        self._consecutive_losses += 1
        if self._consecutive_losses >= self._max_consecutive_losses:
            await self._trip(reason="consecutive_losses", count=self._consecutive_losses)

    async def record_api_failure(self) -> None:
        """Increment API failure counter; trip if threshold exceeded."""
        self._api_failures += 1
        if self._api_failures >= self._max_api_failures:
            await self._trip(reason="api_failures", count=self._api_failures)

    async def record_latency_breach(self, elapsed_ms: int) -> None:
        """Trip if a single operation exceeds the latency threshold."""
        if elapsed_ms >= self._latency_breach_threshold_ms:
            await self._trip(
                reason="latency_breach",
                elapsed_ms=elapsed_ms,
                threshold_ms=self._latency_breach_threshold_ms,
            )

    async def _trip(self, **context) -> None:
        """Open the circuit and publish CIRCUIT_BREAKER_OPEN event."""
        if self._is_open:
            return
        self._is_open = True
        self._opened_at = time.time()
        log.warning("circuit_breaker_tripped", **context)
        await self._bus.publish(
            EventEnvelope.create(
                event_type=CIRCUIT_BREAKER_OPEN,
                source="circuit_breaker",
                payload={
                    "reason": context.get("reason", "unknown"),
                    "context": {k: v for k, v in context.items()},
                    "cooldown_seconds": self._cooldown_seconds,
                },
            )
        )
