"""Circuit breaker — trips on loss streaks, API failures, or latency breaches."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

import structlog

from .event_bus import CIRCUIT_BREAKER_OPEN, EventBus, EventEnvelope

if TYPE_CHECKING:
    pass

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
        """Return True if circuit is open (trading halted).

        Auto-resets after cooldown period.
        """
        if self._is_open:
            elapsed = time.time() - self._opened_at
            if elapsed >= self._cooldown_seconds:
                self._is_open = False
                self._consecutive_losses = 0
                self._api_failures = 0
                log.info(
                    "circuit_breaker_reset",
                    elapsed_seconds=round(elapsed, 1),
                )
        return self._is_open

    def record_win(self) -> None:
        """Reset consecutive loss counter on a winning trade."""
        self._consecutive_losses = 0

    def record_loss(self) -> None:
        """Increment loss counter; trip if threshold exceeded."""
        self._consecutive_losses += 1
        if self._consecutive_losses >= self._max_consecutive_losses:
            self._trip(
                reason="consecutive_losses",
                count=self._consecutive_losses,
            )

    def record_api_failure(self) -> None:
        """Increment API failure counter; trip if threshold exceeded."""
        self._api_failures += 1
        if self._api_failures >= self._max_api_failures:
            self._trip(
                reason="api_failures",
                count=self._api_failures,
            )

    def record_latency_breach(self, elapsed_ms: int) -> None:
        """Trip if a single operation exceeds the latency threshold."""
        if elapsed_ms >= self._latency_breach_threshold_ms:
            self._trip(
                reason="latency_breach",
                elapsed_ms=elapsed_ms,
                threshold_ms=self._latency_breach_threshold_ms,
            )

    def _trip(self, **context) -> None:
        """Open the circuit and publish CIRCUIT_BREAKER_OPEN event."""
        if self._is_open:
            return  # already open
        self._is_open = True
        self._opened_at = time.time()
        log.warning("circuit_breaker_tripped", **context)
        import asyncio
        asyncio.create_task(
            self._bus.publish(
                EventEnvelope(
                    event_type=CIRCUIT_BREAKER_OPEN,
                    source="circuit_breaker",
                    payload={
                        "reason": context.get("reason", "unknown"),
                        "context": context,
                        "cooldown_seconds": self._cooldown_seconds,
                    },
                )
            )
        )
