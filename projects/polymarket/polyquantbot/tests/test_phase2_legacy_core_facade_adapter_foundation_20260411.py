from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from projects.polymarket.polyquantbot.legacy.adapters.context_bridge import LegacyContextBridge
from projects.polymarket.polyquantbot.platform.context.resolver import LegacySessionSeed
from projects.polymarket.polyquantbot.platform.gateway import (
    LEGACY_CORE_FACADE_CONTEXT_RESOLVER,
    LEGACY_CORE_FACADE_DISABLED,
    LegacyCoreFacadeDisabled,
    LegacyCoreResolverAdapter,
    build_legacy_core_facade,
)
from projects.polymarket.polyquantbot.platform.gateway.legacy_core_facade import (
    LegacySignalExecutionRequest,
    LegacyTradeValidationRequest,
)


def _seed() -> LegacySessionSeed:
    return LegacySessionSeed(
        user_id="legacy-user-adapter",
        external_user_id="external-user-adapter",
        mode="PAPER",
        wallet_binding_id="wb-adapter",
        wallet_type="LEGACY_SESSION",
        signature_type="SESSION",
        funder_address="abc123",
        auth_state="UNVERIFIED",
        allowed_markets=("MKT-ADAPTER",),
        trace_id="trace-adapter",
    )


def test_phase2_facade_import_path_continuity() -> None:
    assert LEGACY_CORE_FACADE_DISABLED == "disabled"
    assert LEGACY_CORE_FACADE_CONTEXT_RESOLVER == "legacy-context-resolver"


def test_phase2_facade_factory_uses_disabled_fallback_by_default() -> None:
    os.environ.pop("PLATFORM_LEGACY_CORE_FACADE_MODE", None)
    facade = build_legacy_core_facade()
    assert isinstance(facade, LegacyCoreFacadeDisabled)
    resolution = facade.resolve_context(_seed())
    assert resolution.activated is False
    assert resolution.context_envelope is None
    assert resolution.source == "disabled"


def test_phase2_facade_factory_constructs_legacy_backed_adapter() -> None:
    facade = build_legacy_core_facade(mode="legacy-context-resolver")
    assert isinstance(facade, LegacyCoreResolverAdapter)
    resolution = facade.prepare_execution_context(_seed())
    assert resolution.activated is True
    assert resolution.context_envelope is not None
    assert resolution.context_envelope.execution_context.trace_id == "trace-adapter"


def test_phase2_bridge_runtime_path_unchanged_when_facade_is_not_activated() -> None:
    os.environ.pop("PLATFORM_LEGACY_CORE_FACADE_MODE", None)
    os.environ["ENABLE_PLATFORM_CONTEXT_BRIDGE"] = "true"
    try:
        bridge = LegacyContextBridge()
        result = bridge.attach_context(seed=_seed())
        assert result.attached is True
        assert result.context is not None
        assert result.context.execution_context.trace_id == "trace-adapter"
        assert result.context.wallet_context.wallet_binding_id == "wb-adapter"
    finally:
        os.environ.pop("ENABLE_PLATFORM_CONTEXT_BRIDGE", None)


def test_phase2_adapter_delegates_execute_signal_with_normalized_output() -> None:
    facade = build_legacy_core_facade(mode="legacy-context-resolver")
    result = asyncio.run(
        facade.execute_signal(
            LegacySignalExecutionRequest(
                markets=(
                    {
                        "market_id": "MKT-ADAPTER-1",
                        "p_market": 0.45,
                        "p_model": 0.65,
                        "liquidity_usd": 20_000.0,
                        "bid": 0.44,
                        "ask": 0.46,
                    },
                ),
                bankroll=1_000.0,
                force_signal_mode=False,
            )
        )
    )

    assert result.source == "legacy-signal-engine"
    assert len(result.signals) >= 1
    assert result.signals[0]["market_id"] == "MKT-ADAPTER-1"


def test_phase2_adapter_rejects_invalid_signal_shape() -> None:
    facade = build_legacy_core_facade(mode="legacy-context-resolver")

    with pytest.raises(ValueError, match="invalid_signal_format"):
        asyncio.run(
            facade.execute_signal(
                LegacySignalExecutionRequest(
                    markets=({"market_id": "MKT-INVALID"},),
                    bankroll=1_000.0,
                )
            )
        )


def test_phase2_adapter_rejects_missing_execution_context() -> None:
    facade = build_legacy_core_facade(mode="legacy-context-resolver")

    with pytest.raises(ValueError, match="missing_execution_context"):
        facade.validate_trade(
            LegacyTradeValidationRequest(
                signal_data={"expected_value": 0.2, "edge": 0.2, "liquidity_usd": 20_000.0, "spread": 0.01},
                decision_data={"position_size": 10.0},
                risk_state={
                    "equity": 10_000.0,
                    "open_trades": 0,
                    "correlated_exposure_ratio": 0.1,
                    "drawdown_ratio": 0.01,
                    "daily_loss": -10.0,
                    "global_trade_block": False,
                },
                execution_context=None,
            )
        )


def test_phase2_gateway_has_no_direct_core_imports() -> None:
    gateway_source = Path(
        "/workspace/walker-ai-team/projects/polymarket/polyquantbot/platform/gateway/public_app_gateway.py"
    ).read_text(encoding="utf-8")

    assert "projects.polymarket.polyquantbot.core" not in gateway_source
    assert "from ...core" not in gateway_source
    assert "adapter_not_used_in_gateway_path" in gateway_source
