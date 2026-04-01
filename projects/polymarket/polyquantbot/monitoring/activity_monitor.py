"""Phase 10.8 — ActivityMonitor: inactivity detection and Telegram alerting.

Monitors signal and order activity in the live paper runner.
Sends CRITICAL alerts if:
  - No signal has been generated in 1 hour
  - No order has been placed in 1 hour

Designed to run as a background asyncio task alongside LivePaperRunner.

Usage::

    monitor = ActivityMonitor(
        telegram=telegram_live,
        signal_source=lambda: runner.signal_count,
        order_source=lambda: runner.sim_order_count,
    )
    task = asyncio.create_task(monitor.run())
    ...
    monitor.stop()
    await task
"""
from __future__ import annotations

import asyncio
import time
from typing import Callable

import structlog

from ..telegram.message_formatter import format_no_signal_alert, format_no_trade_alert

log = structlog.get_logger()

# ── Defaults ──────────────────────────────────────────────────────────────────

_DEFAULT_CHECK_INTERVAL_S: float = 60.0   # poll every minute
_DEFAULT_ALERT_WINDOW_S: float = 3600.0   # 1 hour of inactivity → CRITICAL


class ActivityMonitor:
    """Background task that alerts on prolonged signal/trade inactivity.

    Args:
        telegram: TelegramLive instance used to send alerts.
        signal_source: Zero-argument callable returning the current total
            signal count from the runner.
        order_source: Zero-argument callable returning the current total
            simulated-order count from the runner.
        check_interval_s: Seconds between activity checks.
        alert_window_s: Seconds of inactivity before a CRITICAL alert fires.
    """

    def __init__(
        self,
        telegram: object,
        signal_source: Callable[[], int],
        order_source: Callable[[], int],
        check_interval_s: float = _DEFAULT_CHECK_INTERVAL_S,
        alert_window_s: float = _DEFAULT_ALERT_WINDOW_S,
    ) -> None:
        self._telegram = telegram
        self._signal_source = signal_source
        self._order_source = order_source
        self._check_interval = check_interval_s
        self._alert_window = alert_window_s

        self._running: bool = False

        # Timestamps of last observed activity change
        self._last_signal_count: int = 0
        self._last_order_count: int = 0
        self._last_signal_activity_ts: float = time.time()
        self._last_order_activity_ts: float = time.time()

        # Prevent alert flooding — track last alert time per category
        self._last_signal_alert_ts: float = 0.0
        self._last_order_alert_ts: float = 0.0

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def stop(self) -> None:
        """Signal the background loop to exit on its next wake cycle."""
        self._running = False

    async def run(self) -> None:
        """Start the inactivity monitoring loop.

        Runs until stop() is called.  All exceptions are caught and logged so
        this task never crashes the parent runner.
        """
        self._running = True
        log.info(
            "activity_monitor_started",
            check_interval_s=self._check_interval,
            alert_window_s=self._alert_window,
        )

        while self._running:
            await asyncio.sleep(self._check_interval)
            if not self._running:
                break
            try:
                await self._check()
            except Exception as exc:  # noqa: BLE001
                log.error(
                    "activity_monitor_check_error",
                    error=str(exc),
                    exc_info=True,
                )

        log.info("activity_monitor_stopped")

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _check(self) -> None:
        """Perform one round of inactivity checks."""
        now = time.time()
        current_signals = self._signal_source()
        current_orders = self._order_source()

        # Update activity timestamps if counters moved
        if current_signals > self._last_signal_count:
            self._last_signal_count = current_signals
            self._last_signal_activity_ts = now

        if current_orders > self._last_order_count:
            self._last_order_count = current_orders
            self._last_order_activity_ts = now

        # Check signal inactivity
        signal_idle_s = now - self._last_signal_activity_ts
        if signal_idle_s >= self._alert_window:
            await self._alert_no_signals(signal_idle_s, current_signals)

        # Check order inactivity
        order_idle_s = now - self._last_order_activity_ts
        if order_idle_s >= self._alert_window:
            await self._alert_no_trades(order_idle_s, current_orders)

    async def _alert_no_signals(self, idle_s: float, signal_count: int) -> None:
        """Fire a CRITICAL alert for signal inactivity.

        Rate-limited to one alert per alert_window_s.

        Args:
            idle_s: Seconds since last signal activity.
            signal_count: Current total signal count.
        """
        now = time.time()
        if now - self._last_signal_alert_ts < self._alert_window:
            return  # Rate-limit: don't flood

        self._last_signal_alert_ts = now

        log.critical(
            "activity_monitor_no_signal_activity",
            idle_s=round(idle_s, 0),
            signal_count=signal_count,
            alert_window_s=self._alert_window,
        )

        msg = format_no_signal_alert(
            idle_s=idle_s,
            signal_count=signal_count,
        )
        try:
            await self._telegram.alert_error(msg, context="activity_monitor_no_signal")
        except Exception as exc:  # noqa: BLE001
            log.error("activity_monitor_telegram_error", error=str(exc))

    async def _alert_no_trades(self, idle_s: float, order_count: int) -> None:
        """Fire a CRITICAL alert for trade inactivity.

        Rate-limited to one alert per alert_window_s.

        Args:
            idle_s: Seconds since last order activity.
            order_count: Current total simulated-order count.
        """
        now = time.time()
        if now - self._last_order_alert_ts < self._alert_window:
            return  # Rate-limit: don't flood

        self._last_order_alert_ts = now

        log.critical(
            "activity_monitor_no_trade_activity",
            idle_s=round(idle_s, 0),
            order_count=order_count,
            alert_window_s=self._alert_window,
        )

        msg = format_no_trade_alert(
            idle_s=idle_s,
            order_count=order_count,
        )
        try:
            await self._telegram.alert_error(msg, context="activity_monitor_no_trade")
        except Exception as exc:  # noqa: BLE001
            log.error("activity_monitor_telegram_error", error=str(exc))
