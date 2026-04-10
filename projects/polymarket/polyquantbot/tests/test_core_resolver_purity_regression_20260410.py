from __future__ import annotations

import asyncio
import inspect

from projects.polymarket.polyquantbot.monitoring.system_activation import SystemActivationMonitor
from projects.polymarket.polyquantbot.platform.context.resolver import ContextResolver, LegacySessionSeed


def test_regression_activation_monitor_unhealthy_boot_is_controlled() -> None:
    async def _run() -> None:
        monitor = SystemActivationMonitor(log_interval_s=9999, assert_interval_s=0.01)
        await monitor.start()
        await asyncio.sleep(0.05)

        assert monitor._assert_task is not None
        assert monitor._assert_task.done()
        assert monitor._assert_task.exception() is None
        assert monitor.is_boot_healthy() is False
        assert monitor.boot_health_reason() == "no_events_received"

        await monitor.stop()

    asyncio.run(_run())


def test_regression_activation_monitor_healthy_boot_no_event_attribution_noise() -> None:
    async def _run() -> None:
        monitor = SystemActivationMonitor(log_interval_s=9999, assert_interval_s=0.01)
        monitor.record_event()
        monitor.record_signal()
        await monitor.start()
        await asyncio.sleep(0.05)

        assert monitor._assert_task is not None
        assert monitor._assert_task.done()
        assert monitor._assert_task.exception() is None
        assert monitor.is_boot_healthy() is True
        assert monitor.boot_health_reason() == "healthy"

        await monitor.stop()

    asyncio.run(_run())


def test_regression_context_resolver_constructor_has_no_repository_side_effect_dependencies() -> None:
    signature = inspect.signature(ContextResolver.__init__)
    assert "execution_context_repository" not in signature.parameters
    assert "audit_event_repository" not in signature.parameters


def test_regression_context_resolver_composes_envelope_without_side_effect_contract() -> None:
    resolver = ContextResolver()
    seed = LegacySessionSeed(
        user_id="legacy-user-r1",
        external_user_id="session-r1",
        mode="PAPER",
        wallet_binding_id="wb-r1",
        wallet_type="LEGACY_SESSION",
        signature_type="SESSION",
        funder_address="abc123",
        auth_state="UNVERIFIED",
        allowed_markets=("MKT-1", "MKT-2"),
        trace_id="trace-r1",
    )

    envelope = resolver.resolve(seed)

    assert envelope.user_account.user_id == "legacy-user-r1"
    assert envelope.execution_context.trace_id == "trace-r1"
    assert envelope.execution_context.allowed_markets == ("MKT-1", "MKT-2")


def test_regression_startup_import_chain_and_log_dedup_markers_present_once() -> None:
    from projects.polymarket.polyquantbot import main as main_module

    source = inspect.getsource(main_module)
    assert source.count("🚀 PolyQuantBot starting (Railway)") == 1
    assert source.count("🚀 NEW TELEGRAM SYSTEM ACTIVE") == 1
    assert source.count("ENTRYPOINT: main.py") == 1
