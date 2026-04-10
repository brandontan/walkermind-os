from __future__ import annotations

import asyncio

from projects.polymarket.polyquantbot.monitoring.system_activation import SystemActivationMonitor


def test_activation_monitor_unhealthy_startup_is_guarded() -> None:
    async def _run() -> None:
        monitor = SystemActivationMonitor(log_interval_s=9999, assert_interval_s=0.05)
        await monitor.start()
        await asyncio.sleep(0.2)
        assert monitor._assert_task is not None
        assert monitor._assert_task.done()
        assert monitor._assert_task.exception() is None
        await monitor.stop()

    asyncio.run(_run())


def test_activation_monitor_no_event_condition_is_controlled() -> None:
    async def _run() -> None:
        monitor = SystemActivationMonitor(log_interval_s=9999, assert_interval_s=0.05)
        await monitor.start()
        await asyncio.sleep(0.2)
        assert monitor.event_count == 0
        assert monitor._assert_task is not None
        assert monitor._assert_task.exception() is None
        await monitor.stop()

    asyncio.run(_run())


def test_activation_monitor_warn_path_completes() -> None:
    async def _run() -> None:
        monitor = SystemActivationMonitor(log_interval_s=9999, assert_interval_s=0.05)
        monitor.event_count = 3
        await monitor.start()
        await asyncio.sleep(0.2)
        assert monitor._assert_task is not None
        assert monitor._assert_task.done()
        assert monitor._assert_task.exception() is None
        await monitor.stop()

    asyncio.run(_run())
