"""System Activation Monitor — event/signal flow validation."""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Optional

import structlog

log = structlog.get_logger()

_LOG_INTERVAL_S: float = 10.0
_ASSERT_INTERVAL_S: float = 60.0


class SystemActivationMonitor:
    """Monitors event and signal flow with controlled startup assertions."""

    def __init__(
        self,
        log_interval_s: float = _LOG_INTERVAL_S,
        assert_interval_s: float = _ASSERT_INTERVAL_S,
    ) -> None:
        self._log_interval = log_interval_s
        self._assert_interval = assert_interval_s

        self.event_count: int = 0
        self.signal_count: int = 0
        self.trade_count: int = 0
        self.ws_connected: bool = False

        self._running: bool = False
        self._log_task: Optional[asyncio.Task] = None
        self._assert_task: Optional[asyncio.Task] = None
        self._start_ts: float = 0.0
        self._startup_healthy: bool = False
        self._last_flow_signature: tuple[int, int, int] | None = None

    def record_event(self) -> None:
        self.event_count += 1

    def record_signal(self) -> None:
        self.signal_count += 1

    def record_trade(self) -> None:
        self.trade_count += 1

    def record_ws_state(self, connected: bool) -> None:
        self.ws_connected = connected

    def mark_startup_healthy(self, healthy: bool) -> None:
        self._startup_healthy = healthy

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._start_ts = time.time()
        self._last_flow_signature = None
        self._log_task = asyncio.create_task(
            self._run_task(self._log_loop, task_name="activation_monitor_log"),
            name="activation_monitor_log",
        )
        self._assert_task = asyncio.create_task(
            self._run_task(self._assert_loop, task_name="activation_monitor_assert"),
            name="activation_monitor_assert",
        )
        log.info("system_activation_monitor_started")

    async def stop(self) -> None:
        self._running = False
        for task in (self._log_task, self._assert_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        log.info("system_activation_monitor_stopped")

    async def _run_task(self, coro: Callable[[], Awaitable[None]], *, task_name: str) -> None:
        try:
            await coro()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("activation_monitor_task_failed", task=task_name, error=str(exc), exc_info=True)

    async def _log_loop(self) -> None:
        while self._running:
            await asyncio.sleep(self._log_interval)
            flow_signature = (self.event_count, self.signal_count, self.trade_count)
            if flow_signature == self._last_flow_signature:
                continue
            self._last_flow_signature = flow_signature
            log.info(
                "activation_flow",
                events=self.event_count,
                signals=self.signal_count,
                trades=self.trade_count,
            )

    async def _assert_loop(self) -> None:
        await asyncio.sleep(self._assert_interval)
        elapsed = round(time.time() - self._start_ts, 1)

        if self.event_count == 0:
            if self._startup_healthy:
                log.error(
                    "activation_no_events_after_startup",
                    elapsed_s=elapsed,
                    ws_connected=self.ws_connected,
                    hint="WebSocket feed may be disconnected or MARKET_IDS may be invalid",
                )
                return
            log.warning(
                "activation_assertion_deferred_until_startup_healthy",
                elapsed_s=elapsed,
                ws_connected=self.ws_connected,
                hint="Startup not healthy yet; suppressing no-event assertion noise",
            )
            return

        if self.signal_count == 0:
            log.warning(
                "activation_no_signal_generated",
                event_count=self.event_count,
                elapsed_s=elapsed,
                hint="Check edge threshold, market liquidity, and strategy config",
            )
