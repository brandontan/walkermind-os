from __future__ import annotations

import asyncio
import importlib
import os
import tempfile
from pathlib import Path

from projects.polymarket.polyquantbot.execution.engine import ExecutionEngine
from projects.polymarket.polyquantbot.execution.strategy_trigger import StrategyConfig, StrategyTrigger
from projects.polymarket.polyquantbot.legacy.adapters.context_bridge import LegacyContextBridge
from projects.polymarket.polyquantbot.platform.context.resolver import ContextResolver, LegacySessionSeed


def _seed_risk_state_file(path: Path) -> None:
    path.write_text(
        (
            '{"correlated_exposure_ratio":0.0,'
            '"daily_pnl_by_day":{},'
            '"drawdown_ratio":0.0,'
            '"equity":10000.0,'
            '"global_trade_block":false,'
            '"open_trades":0,'
            '"peak_equity":10000.0,'
            '"portfolio_pnl":0.0,'
            '"version":1}'
        ),
        encoding="utf-8",
    )


def _seed() -> LegacySessionSeed:
    return LegacySessionSeed(
        user_id="legacy-user-1",
        external_user_id="session-1",
        mode="PAPER",
        wallet_binding_id="wb-1",
        wallet_type="LEGACY_SESSION",
        signature_type="SESSION",
        funder_address="N/A",
        auth_state="UNVERIFIED",
        allowed_markets=("m-1",),
        trace_id="trace-1",
    )


def test_phase1_platform_context_contracts_resolve() -> None:
    resolver = ContextResolver()
    envelope = resolver.resolve(_seed())

    assert envelope.user_account.user_id == "legacy-user-1"
    assert envelope.wallet_context.wallet_binding_id == "wb-1"
    assert envelope.permission_profile.paper_enabled is True
    assert envelope.execution_context.permission_version == "phase2-foundation"
    assert envelope.execution_context.trace_id == "trace-1"


def test_phase1_resolver_has_no_repository_attributes() -> None:
    resolver = ContextResolver()
    attrs = vars(resolver)
    forbidden = {"_repository", "_account_repository", "_wallet_repository", "_permission_repository"}
    assert forbidden.isdisjoint(attrs.keys())


def test_phase1_resolver_deterministic_for_identical_input() -> None:
    resolver = ContextResolver()
    one = resolver.resolve(_seed())
    two = resolver.resolve(_seed())
    assert one.execution_context == two.execution_context
    assert one.wallet_context.wallet_binding_id == two.wallet_context.wallet_binding_id
    assert one.permission_profile.allowed_markets == two.permission_profile.allowed_markets


def test_phase1_bridge_constructor_works_with_current_resolver_signature() -> None:
    os.environ["PLATFORM_STORAGE_BACKEND"] = "none"
    try:
        bridge = LegacyContextBridge()
        result = bridge.attach_context(seed=_seed())
        assert result.strict_mode_blocked is False
    finally:
        os.environ.pop("PLATFORM_STORAGE_BACKEND", None)


def test_phase1_startup_import_chain_smoke() -> None:
    modules = [
        "projects.polymarket.polyquantbot.main",
        "projects.polymarket.polyquantbot.telegram.command_handler",
        "projects.polymarket.polyquantbot.execution.strategy_trigger",
        "projects.polymarket.polyquantbot.legacy.adapters.context_bridge",
        "projects.polymarket.polyquantbot.platform.context.resolver",
    ]
    for module_name in modules:
        module = importlib.import_module(module_name)
        assert module is not None


def test_phase1_legacy_bridge_safe_fallback_non_strict() -> None:
    class _FailingResolver:
        def resolve(self, _seed: LegacySessionSeed):
            raise RuntimeError("forced_resolution_failure")

    os.environ["ENABLE_PLATFORM_CONTEXT_BRIDGE"] = "true"
    os.environ["PLATFORM_CONTEXT_STRICT_MODE"] = "false"
    try:
        bridge = LegacyContextBridge(resolver=_FailingResolver())
        result = bridge.attach_context(seed=_seed())
    finally:
        os.environ.pop("ENABLE_PLATFORM_CONTEXT_BRIDGE", None)
        os.environ.pop("PLATFORM_CONTEXT_STRICT_MODE", None)

    assert result.attached is False
    assert result.fallback_used is True
    assert result.strict_mode_blocked is False


def test_phase1_bridge_enabled_non_strict_keeps_legacy_behavior() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "risk_state.json"
            _seed_risk_state_file(state_path)
            trigger = StrategyTrigger(
                engine=ExecutionEngine(starting_equity=10_000.0),
                config=StrategyConfig(
                    market_id="MARKET-1",
                    threshold=0.40,
                    risk_state_persistence_path=str(state_path),
                ),
            )
            trigger._cooldown_seconds = 0.0  # noqa: SLF001
            trigger._intelligence.evaluate_entry = lambda _snapshot: {"score": 0.10, "reasons": ["test"]}  # type: ignore[assignment] # noqa: SLF001

            os.environ["ENABLE_PLATFORM_CONTEXT_BRIDGE"] = "true"
            os.environ["PLATFORM_CONTEXT_STRICT_MODE"] = "false"
            try:
                decision = await trigger.evaluate(
                    market_price=0.45,
                    market_context={
                        "user_id": "legacy-user-1",
                        "legacy_session_id": "session-1",
                        "market_id": "MARKET-1",
                        "trace_id": "trace-1",
                    },
                )
            finally:
                os.environ.pop("ENABLE_PLATFORM_CONTEXT_BRIDGE", None)
                os.environ.pop("PLATFORM_CONTEXT_STRICT_MODE", None)

            assert decision == "HOLD"
            assert trigger.get_platform_context() is not None

    asyncio.run(_run())


def test_phase1_bridge_strict_mode_blocks_on_resolution_failure() -> None:
    class _FailingResolver:
        def resolve(self, _seed: LegacySessionSeed):
            raise RuntimeError("forced_resolution_failure")

    async def _run() -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "risk_state.json"
            _seed_risk_state_file(state_path)
            trigger = StrategyTrigger(
                engine=ExecutionEngine(starting_equity=10_000.0),
                config=StrategyConfig(
                    market_id="MARKET-1",
                    risk_state_persistence_path=str(state_path),
                ),
            )
            trigger._cooldown_seconds = 0.0  # noqa: SLF001
            trigger._legacy_context_bridge = LegacyContextBridge(resolver=_FailingResolver())  # noqa: SLF001

            os.environ["ENABLE_PLATFORM_CONTEXT_BRIDGE"] = "true"
            os.environ["PLATFORM_CONTEXT_STRICT_MODE"] = "true"
            try:
                decision = await trigger.evaluate(market_price=0.70, market_context={"trace_id": "trace-2"})
            finally:
                os.environ.pop("ENABLE_PLATFORM_CONTEXT_BRIDGE", None)
                os.environ.pop("PLATFORM_CONTEXT_STRICT_MODE", None)

            assert decision == "BLOCKED"

    asyncio.run(_run())
