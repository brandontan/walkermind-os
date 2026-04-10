from __future__ import annotations

import asyncio
import importlib


def test_hotfix_resolver_startup_import_chain_regression() -> None:
    modules = (
        "projects.polymarket.polyquantbot.main",
        "projects.polymarket.polyquantbot.telegram.command_handler",
        "projects.polymarket.polyquantbot.execution.strategy_trigger",
        "projects.polymarket.polyquantbot.legacy.adapters.context_bridge",
        "projects.polymarket.polyquantbot.platform.context.resolver",
    )
    for module_name in modules:
        loaded = importlib.import_module(module_name)
        assert loaded is not None


def test_hotfix_bridge_smoke_import_under_entrypoint_path(monkeypatch) -> None:
    async def _run() -> None:
        bridge_mod = importlib.import_module("projects.polymarket.polyquantbot.legacy.adapters.context_bridge")
        resolver_mod = importlib.import_module("projects.polymarket.polyquantbot.platform.context.resolver")

        monkeypatch.setenv("ENABLE_PLATFORM_CONTEXT_BRIDGE", "false")

        bridge = bridge_mod.LegacyContextBridge()
        seed = resolver_mod.LegacySessionSeed(
            user_id="legacy-user",
            external_user_id="legacy-user",
            mode="PAPER",
            wallet_binding_id="wb-1",
            wallet_type="EOA",
            signature_type="EIP712",
            funder_address="0xabc",
            auth_state="approved",
            allowed_markets=("market-1",),
            trace_id="trace-1",
        )
        result = bridge.attach_context(seed=seed)

        assert result.attached is False
        assert result.fallback_used is True
        assert result.strict_mode_blocked is False

    asyncio.run(_run())


def test_hotfix_activation_monitor_defers_assertion_during_unhealthy_startup() -> None:
    async def _run() -> None:
        monitor_mod = importlib.import_module("projects.polymarket.polyquantbot.monitoring.system_activation")
        monitor = monitor_mod.SystemActivationMonitor(log_interval_s=9999, assert_interval_s=0.05)
        monitor.mark_startup_healthy(False)

        await monitor.start()
        await asyncio.sleep(0.2)

        assert monitor._assert_task is not None
        assert monitor._assert_task.done()
        assert monitor._assert_task.exception() is None
        await monitor.stop()

    asyncio.run(_run())


def test_hotfix_activation_monitor_surfaces_no_event_after_healthy_startup() -> None:
    async def _run() -> None:
        monitor_mod = importlib.import_module("projects.polymarket.polyquantbot.monitoring.system_activation")
        monitor = monitor_mod.SystemActivationMonitor(log_interval_s=9999, assert_interval_s=0.05)
        monitor.mark_startup_healthy(True)

        await monitor.start()
        await asyncio.sleep(0.2)

        assert monitor._assert_task is not None
        assert monitor._assert_task.done()
        assert monitor._assert_task.exception() is None
        await monitor.stop()

    asyncio.run(_run())


def test_hotfix_activation_flow_log_deduplicates_identical_snapshots(monkeypatch) -> None:
    async def _run() -> None:
        monitor_mod = importlib.import_module("projects.polymarket.polyquantbot.monitoring.system_activation")
        flow_log_calls: list[dict[str, object]] = []

        original_info = monitor_mod.log.info

        def _capture_info(event: str, **kwargs: object) -> None:
            if event == "activation_flow":
                flow_log_calls.append(kwargs)
            original_info(event, **kwargs)

        monkeypatch.setattr(monitor_mod.log, "info", _capture_info)

        monitor = monitor_mod.SystemActivationMonitor(log_interval_s=0.03, assert_interval_s=9999)
        await monitor.start()
        await asyncio.sleep(0.13)
        await monitor.stop()

        assert len(flow_log_calls) == 1

    asyncio.run(_run())


def test_hotfix_no_strategy_risk_execution_constant_drift() -> None:
    from projects.polymarket.polyquantbot.execution.strategy_trigger import StrategyConfig

    cfg = StrategyConfig(market_id="market-1")
    assert cfg.max_position_size_ratio == 0.10
    assert cfg.min_liquidity_usd == 10_000.0
    assert cfg.cross_exchange_min_net_edge == 0.02
    assert cfg.max_market_exposure_ratio == 0.15
