"""Phase 8 — HealthMonitor: Latency/fill-rate alerts and exposure consistency.

Design guarantees:
    - Periodic health check loop with configurable interval.
    - Latency threshold alert: log WARNING if p95 latency exceeds threshold.
    - Fill rate threshold alert: log WARNING if fill rate drops below threshold.
    - Exposure anomaly: trigger kill switch if total_exposure > balance * 0.45.
    - All risk_guard checks use the fast-path (if guard.disabled: return).
    - Structured JSON warning logs on every alert condition.
    - No side effects on read-only metrics — only RiskGuard.trigger_kill_switch
      causes state change.

Alert thresholds (configurable via constructor):
    latency_warn_ms:    500ms   — p95 latency warning
    fill_rate_warn:     0.50    — fill rate below 50% triggers warning
    exposure_limit_pct: 0.45    — exposure > 45% of balance → kill switch

Usage::

    monitor = HealthMonitor(
        position_tracker=tracker,
        fill_monitor=fill_mon,
        latency_tracker=latency_tracker,
        feedback_tracker=feedback_tracker,
        risk_guard=guard,
        check_interval_sec=30.0,
        balance_provider=lambda: account_balance,
    )

    await monitor.run()
"""
from __future__ import annotations

import asyncio
import time
from typing import Callable, Optional

import structlog

log = structlog.get_logger()

# ── Defaults ──────────────────────────────────────────────────────────────────

_LATENCY_WARN_MS: float = 500.0      # p95 latency warning threshold
_FILL_RATE_WARN: float = 0.50        # fill rate below this triggers alert
_EXPOSURE_LIMIT_PCT: float = 0.45    # > 45% of balance → kill switch
_CHECK_INTERVAL_SEC: float = 30.0    # health check interval


# ── HealthMonitor ─────────────────────────────────────────────────────────────

class HealthMonitor:
    """Continuous health monitoring and anomaly detection for Phase 8.

    Checks on every tick:
        1. Latency spike: p95 > latency_warn_ms → WARNING log.
        2. Fill rate drop: fill_rate < fill_rate_warn → WARNING log.
        3. Exposure anomaly: total_exposure > balance * exposure_limit_pct
           → trigger kill switch.

    Thread-safety: designed for single asyncio event loop.
    All checks are read-only except the kill switch trigger path.
    """

    def __init__(
        self,
        position_tracker,           # PositionTracker — source of exposure data
        fill_monitor,               # FillMonitor — source of fill rate data
        risk_guard,                 # RiskGuard — kill switch authority
        latency_tracker=None,       # Phase 7 LatencyTracker (optional)
        feedback_tracker=None,      # Phase 7 ExecutionFeedbackTracker (optional)
        balance_provider: Optional[Callable[[], float]] = None,
        check_interval_sec: float = _CHECK_INTERVAL_SEC,
        latency_warn_ms: float = _LATENCY_WARN_MS,
        fill_rate_warn: float = _FILL_RATE_WARN,
        exposure_limit_pct: float = _EXPOSURE_LIMIT_PCT,
    ) -> None:
        """Initialise the health monitor.

        Args:
            position_tracker: PositionTracker for exposure calculation.
            fill_monitor: FillMonitor for fill rate statistics.
            risk_guard: RiskGuard for kill switch and disabled flag.
            latency_tracker: Optional LatencyTracker from Phase 7.
            feedback_tracker: Optional ExecutionFeedbackTracker from Phase 7.
            balance_provider: Callable returning current account balance.
                              Defaults to returning 0.0 (disables exposure check).
            check_interval_sec: Interval between health checks.
            latency_warn_ms: p95 latency alert threshold (ms).
            fill_rate_warn: Fill rate below this fraction triggers WARNING.
            exposure_limit_pct: Total exposure fraction above which kill switch fires.
        """
        self._tracker = position_tracker
        self._fill_monitor = fill_monitor
        self._risk_guard = risk_guard
        self._latency_tracker = latency_tracker
        self._feedback_tracker = feedback_tracker
        self._balance_provider = balance_provider or (lambda: 0.0)
        self._check_interval_sec = check_interval_sec
        self._latency_warn_ms = latency_warn_ms
        self._fill_rate_warn = fill_rate_warn
        self._exposure_limit_pct = exposure_limit_pct

        self._running: bool = False
        self._last_check_at: Optional[float] = None
        self._alert_count: int = 0

        log.info(
            "health_monitor_initialized",
            check_interval_sec=check_interval_sec,
            latency_warn_ms=latency_warn_ms,
            fill_rate_warn=fill_rate_warn,
            exposure_limit_pct=exposure_limit_pct,
        )

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Start the health monitoring loop.

        Runs until risk_guard.disabled is True or stop() is called.
        """
        # ── Kill switch fast-path ─────────────────────────────────────────────
        if self._risk_guard is not None and self._risk_guard.disabled:
            log.warning("health_monitor_startup_blocked_kill_switch")
            return

        self._running = True
        log.info("health_monitor_loop_started")

        while self._running:
            # ── Kill switch check at top of every loop ────────────────────────
            if self._risk_guard is not None and self._risk_guard.disabled:
                log.warning("health_monitor_loop_killed")
                self._running = False
                break

            await self._run_checks()
            self._last_check_at = time.time()
            await asyncio.sleep(self._check_interval_sec)

        log.info("health_monitor_loop_stopped", total_alerts=self._alert_count)

    async def stop(self) -> None:
        """Gracefully stop the health monitor."""
        self._running = False

    # ── Health checks ─────────────────────────────────────────────────────────

    async def _run_checks(self) -> None:
        """Run all health checks in sequence.

        Each check is independent — a failure in one does not skip others.
        """
        await self._check_latency()
        await self._check_fill_rate()
        await self._check_exposure()
        await self._log_position_summary()

    async def _check_latency(self) -> None:
        """Alert if p95 execution latency exceeds threshold.

        Fast-path exits if risk_guard.disabled.
        """
        if self._risk_guard is not None and self._risk_guard.disabled:
            return
        if self._latency_tracker is None:
            return

        try:
            stats = self._latency_tracker.global_stats()
            if stats is None:
                return

            p95_ms = getattr(stats, "p95_ms", None)
            mean_ms = getattr(stats, "mean_ms", None)

            if p95_ms is not None and p95_ms > self._latency_warn_ms:
                self._alert_count += 1
                log.warning(
                    "health_alert_latency_spike",
                    p95_ms=round(p95_ms, 2),
                    mean_ms=round(mean_ms or 0.0, 2),
                    threshold_ms=self._latency_warn_ms,
                    alert_count=self._alert_count,
                )

        except Exception as exc:  # noqa: BLE001
            log.error(
                "health_monitor_latency_check_error",
                error=str(exc),
                exc_info=True,
            )

    async def _check_fill_rate(self) -> None:
        """Alert if fill rate drops below threshold.

        Fast-path exits if risk_guard.disabled.
        """
        if self._risk_guard is not None and self._risk_guard.disabled:
            return
        if self._feedback_tracker is None:
            return

        try:
            summary = self._feedback_tracker.calibration_summary()
            fill_rate = float(summary.get("fill_rate", 1.0))
            pending = int(summary.get("pending_orders", 0))
            mean_fill_error = float(summary.get("mean_fill_error", 0.0))

            if fill_rate < self._fill_rate_warn and pending > 0:
                self._alert_count += 1
                log.warning(
                    "health_alert_low_fill_rate",
                    fill_rate=round(fill_rate, 4),
                    threshold=self._fill_rate_warn,
                    pending_orders=pending,
                    mean_fill_error=round(mean_fill_error, 4),
                    alert_count=self._alert_count,
                )

        except Exception as exc:  # noqa: BLE001
            log.error(
                "health_monitor_fill_rate_check_error",
                error=str(exc),
                exc_info=True,
            )

    async def _check_exposure(self) -> None:
        """Trigger kill switch if total exposure exceeds balance threshold.

        This is the primary exposure anomaly guard:
            if total_exposure > balance * exposure_limit_pct:
                trigger_kill_switch("exposure_anomaly")

        Fast-path exits if risk_guard.disabled.
        """
        if self._risk_guard is not None and self._risk_guard.disabled:
            return

        try:
            balance = self._balance_provider()
            if balance <= 0:
                return  # can't compute ratio without valid balance

            total_exposure = await self._tracker.total_exposure()
            ratio = total_exposure / balance

            if ratio > self._exposure_limit_pct:
                self._alert_count += 1
                log.warning(
                    "health_alert_exposure_anomaly",
                    total_exposure=round(total_exposure, 2),
                    balance=round(balance, 2),
                    ratio=round(ratio, 4),
                    threshold_pct=self._exposure_limit_pct,
                    alert_count=self._alert_count,
                )
                # Delegate to RiskGuard for kill switch
                await self._risk_guard.check_exposure(
                    total_exposure=total_exposure,
                    balance=balance,
                    threshold_pct=self._exposure_limit_pct,
                )

        except Exception as exc:  # noqa: BLE001
            log.error(
                "health_monitor_exposure_check_error",
                error=str(exc),
                exc_info=True,
            )

    async def _log_position_summary(self) -> None:
        """Log a structured position summary every check cycle."""
        if self._risk_guard is not None and self._risk_guard.disabled:
            return

        try:
            summary = await self._tracker.summary()
            fill_status = self._fill_monitor.status() if self._fill_monitor else {}

            log.info(
                "health_monitor_tick",
                open_positions=summary.get("open_positions", 0),
                total_exposure_usd=summary.get("total_exposure_usd", 0.0),
                closed_history=summary.get("closed_positions_history", 0),
                tracked_orders=fill_status.get("tracked_orders", 0),
                processed_orders=fill_status.get("processed_order_count", 0),
                alert_count=self._alert_count,
            )

        except Exception as exc:  # noqa: BLE001
            log.error(
                "health_monitor_summary_log_error",
                error=str(exc),
                exc_info=True,
            )

    # ── Force check ───────────────────────────────────────────────────────────

    async def check_now(self) -> None:
        """Run all health checks immediately (callable outside the loop).

        Useful for triggering a check after a significant event.
        """
        if self._risk_guard is not None and self._risk_guard.disabled:
            return
        await self._run_checks()

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Return structured monitoring state."""
        return {
            "running": self._running,
            "last_check_at": self._last_check_at,
            "alert_count": self._alert_count,
            "latency_warn_ms": self._latency_warn_ms,
            "fill_rate_warn": self._fill_rate_warn,
            "exposure_limit_pct": self._exposure_limit_pct,
        }
