"""CircuitBreaker — Rolling-window circuit breaker for error rate and latency.

Extracted from the Phase 9 orchestrator into the core domain.

Triggers if:
    - error_rate > error_rate_threshold in the rolling call window, or
    - p95 execution latency > latency_threshold_ms in the window, or
    - N consecutive failures are recorded.

On trigger:
    - Calls risk_guard.trigger_kill_switch() with reason.
    - Respects cooldown_sec to prevent repeated trigger spam.

Thread-safety: single asyncio event loop only.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Optional

import structlog

log = structlog.get_logger()


class CircuitBreaker:
    """Rolling-window circuit breaker for error rate and latency spikes.

    Triggers if:
        - error_rate > error_rate_threshold in the rolling call window, or
        - p95 execution latency > latency_threshold_ms in the window.

    On trigger:
        - Calls risk_guard.trigger_kill_switch() with reason.
        - Respects cooldown_sec to prevent repeated trigger spam.

    Thread-safety: single asyncio event loop only.
    """

    def __init__(
        self,
        risk_guard,
        error_rate_threshold: float = 0.30,
        error_window_size: int = 20,
        latency_threshold_ms: float = 600.0,
        cooldown_sec: float = 60.0,
        enabled: bool = True,
        consecutive_failures_threshold: int = 3,
        telegram=None,
    ) -> None:
        """Initialise the circuit breaker.

        Args:
            risk_guard: RiskGuard instance — called to trigger kill switch.
            error_rate_threshold: Trigger if error_rate exceeds this (0.0–1.0).
            error_window_size: Rolling window size in number of recent calls.
            latency_threshold_ms: Trigger if p95 latency exceeds this (ms).
            cooldown_sec: Suppress re-trigger for this many seconds after fire.
            enabled: If False, circuit breaker is a no-op.
            consecutive_failures_threshold: Trigger if N consecutive failures occur.
            telegram: Optional TelegramLive instance for alert_kill notifications.
        """
        self._risk_guard = risk_guard
        self._error_threshold = error_rate_threshold
        self._window_size = error_window_size
        self._latency_threshold = latency_threshold_ms
        self._cooldown = cooldown_sec
        self._enabled = enabled
        self._consecutive_failures_threshold = consecutive_failures_threshold
        self._telegram = telegram

        self._error_window: deque[bool] = deque(maxlen=error_window_size)
        self._latency_window: deque[float] = deque(maxlen=error_window_size)
        self._last_trigger_at: float = 0.0
        self._trigger_count: int = 0
        self._consecutive_failures: int = 0

        log.info(
            "circuit_breaker_initialized",
            error_rate_threshold=error_rate_threshold,
            latency_threshold_ms=latency_threshold_ms,
            cooldown_sec=cooldown_sec,
            enabled=enabled,
            consecutive_failures_threshold=consecutive_failures_threshold,
        )

    async def record(
        self,
        success: bool,
        latency_ms: float,
        correlation_id: str = "",
    ) -> None:
        """Record a call outcome and evaluate circuit breaker conditions.

        Args:
            success: True if the call succeeded, False on error/timeout.
            latency_ms: Execution latency for this call in milliseconds.
            correlation_id: Request trace ID for log correlation.
        """
        if not self._enabled or self._risk_guard.disabled:
            return

        self._error_window.append(not success)
        self._latency_window.append(latency_ms)

        # Track consecutive failures for rapid failure detection
        if not success:
            self._consecutive_failures += 1
        else:
            self._consecutive_failures = 0

        if self._consecutive_failures >= self._consecutive_failures_threshold:
            await self._trigger(
                reason=f"consecutive_failures:{self._consecutive_failures}",
                correlation_id=correlation_id,
            )
            return

        if time.time() - self._last_trigger_at < self._cooldown:
            return

        if len(self._error_window) >= self._window_size:
            error_rate = sum(self._error_window) / len(self._error_window)
            if error_rate > self._error_threshold:
                await self._trigger(
                    reason=f"error_rate:{error_rate:.3f}_exceeds:{self._error_threshold}",
                    correlation_id=correlation_id,
                )
                return

        if len(self._latency_window) >= self._window_size:
            sorted_lat = sorted(self._latency_window)
            p95_idx = max(0, int(len(sorted_lat) * 0.95) - 1)
            p95 = sorted_lat[p95_idx]
            if p95 > self._latency_threshold:
                await self._trigger(
                    reason=f"p95_latency:{p95:.0f}ms_exceeds:{self._latency_threshold:.0f}ms",
                    correlation_id=correlation_id,
                )

    async def _trigger(self, reason: str, correlation_id: str) -> None:
        """Fire the circuit breaker — activates the kill switch.

        Args:
            reason: Human-readable trigger description.
            correlation_id: Request trace ID.
        """
        self._trigger_count += 1
        self._last_trigger_at = time.time()

        log.error(
            "circuit_breaker_triggered",
            reason=reason,
            trigger_count=self._trigger_count,
            correlation_id=correlation_id,
        )

        if self._telegram:
            await self._telegram.alert_kill(
                reason=f"circuit_breaker:{reason}",
                correlation_id=correlation_id,
            )

        await self._risk_guard.trigger_kill_switch(f"circuit_breaker:{reason}")
