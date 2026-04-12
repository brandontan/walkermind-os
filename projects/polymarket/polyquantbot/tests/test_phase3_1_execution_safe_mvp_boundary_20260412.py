from __future__ import annotations

from pathlib import Path

from projects.polymarket.polyquantbot.platform.context.resolver import LegacySessionSeed
from projects.polymarket.polyquantbot.platform.gateway import (
    PUBLIC_APP_GATEWAY_DISABLED,
    PUBLIC_APP_GATEWAY_LEGACY_ONLY,
    READINESS_BLOCK_ACTIVATION_NOT_ALLOWED,
    READINESS_BLOCK_MISSING_EXECUTION_CONTEXT,
    READINESS_BLOCK_RISK_VALIDATION_BLOCKED,
    READINESS_BLOCK_ROUTING_NOT_SAFE,
    READINESS_BLOCK_UNSUPPORTED_MODE,
    READINESS_READY_BUT_NON_ACTIVATING,
    ExecutionSafeReadinessGate,
    PublicAppGatewayRoutingTrace,
    build_legacy_core_facade,
    build_public_app_gateway,
)


def _seed() -> LegacySessionSeed:
    return LegacySessionSeed(
        user_id="phase3-1-user",
        external_user_id="phase3-1-external",
        mode="PAPER",
        wallet_binding_id="phase3-1-wallet",
        wallet_type="LEGACY_SESSION",
        signature_type="SESSION",
        funder_address="0xphase31",
        auth_state="UNVERIFIED",
        allowed_markets=("MKT-3-1",),
        trace_id="phase3-1-trace",
    )


def _signal_data() -> dict[str, float]:
    return {
        "expected_value": 0.20,
        "edge": 0.10,
        "liquidity_usd": 20_000.0,
        "spread": 0.01,
    }


def _decision_data() -> dict[str, float]:
    return {"position_size": 100.0}


def _risk_state() -> dict[str, float | int | bool]:
    return {
        "equity": 10_000.0,
        "open_trades": 0,
        "correlated_exposure_ratio": 0.10,
        "drawdown_ratio": 0.01,
        "daily_loss": -100.0,
        "global_trade_block": False,
    }


def test_phase3_1_safe_path_readiness_is_non_activating_even_when_checks_pass() -> None:
    gateway = build_public_app_gateway(mode=PUBLIC_APP_GATEWAY_LEGACY_ONLY)
    gateway_resolution = gateway.resolve(_seed())
    assert gateway_resolution.facade_resolution is not None

    gate = ExecutionSafeReadinessGate(facade=build_legacy_core_facade(mode="legacy-context-resolver"))
    readiness = gate.evaluate(
        routing_trace=gateway_resolution.routing_trace,
        facade_resolution=gateway_resolution.facade_resolution,
        signal_data=_signal_data(),
        decision_data=_decision_data(),
        risk_state=_risk_state(),
    )

    assert readiness.can_execute is False
    assert readiness.runtime_activation_allowed is False
    assert readiness.block_reason == READINESS_READY_BUT_NON_ACTIVATING
    assert readiness.trace.final_activation_decision is False


def test_phase3_1_unsupported_routing_mode_blocks_deterministically() -> None:
    gate = ExecutionSafeReadinessGate(facade=build_legacy_core_facade(mode="legacy-context-resolver"))
    readiness = gate.evaluate(
        routing_trace=PublicAppGatewayRoutingTrace(
            selected_mode="experimental-mode",
            selected_path="experimental-path",
            platform_participated=True,
            adapter_enforced=True,
            runtime_activation_remained_disabled=True,
        ),
        facade_resolution=None,
        signal_data=_signal_data(),
        decision_data=_decision_data(),
        risk_state=_risk_state(),
    )

    assert readiness.block_reason == READINESS_BLOCK_UNSUPPORTED_MODE


def test_phase3_1_missing_execution_context_blocks_deterministically() -> None:
    gate = ExecutionSafeReadinessGate(facade=build_legacy_core_facade(mode="legacy-context-resolver"))
    readiness = gate.evaluate(
        routing_trace=PublicAppGatewayRoutingTrace(
            selected_mode=PUBLIC_APP_GATEWAY_LEGACY_ONLY,
            selected_path=PUBLIC_APP_GATEWAY_LEGACY_ONLY,
            platform_participated=False,
            adapter_enforced=True,
            runtime_activation_remained_disabled=True,
        ),
        facade_resolution=None,
        signal_data=_signal_data(),
        decision_data=_decision_data(),
        risk_state=_risk_state(),
    )

    assert readiness.block_reason == READINESS_BLOCK_MISSING_EXECUTION_CONTEXT


def test_phase3_1_pre_trade_validator_block_is_surfaced() -> None:
    gateway = build_public_app_gateway(mode=PUBLIC_APP_GATEWAY_LEGACY_ONLY)
    gateway_resolution = gateway.resolve(_seed())
    assert gateway_resolution.facade_resolution is not None

    blocked_risk_state = {
        **_risk_state(),
        "global_trade_block": True,
    }
    gate = ExecutionSafeReadinessGate(facade=build_legacy_core_facade(mode="legacy-context-resolver"))
    readiness = gate.evaluate(
        routing_trace=gateway_resolution.routing_trace,
        facade_resolution=gateway_resolution.facade_resolution,
        signal_data=_signal_data(),
        decision_data=_decision_data(),
        risk_state=blocked_risk_state,
    )

    assert readiness.block_reason == READINESS_BLOCK_RISK_VALIDATION_BLOCKED
    assert readiness.readiness_checks["risk_validation_decision"] == "BLOCK"
    assert readiness.readiness_checks["risk_validation_reason"] == "global_trade_block_active"


def test_phase3_1_activation_request_remains_blocked() -> None:
    gateway = build_public_app_gateway(mode=PUBLIC_APP_GATEWAY_LEGACY_ONLY)
    gateway_resolution = gateway.resolve(_seed())
    assert gateway_resolution.facade_resolution is not None

    gate = ExecutionSafeReadinessGate(facade=build_legacy_core_facade(mode="legacy-context-resolver"))
    readiness = gate.evaluate(
        routing_trace=gateway_resolution.routing_trace,
        facade_resolution=gateway_resolution.facade_resolution,
        signal_data=_signal_data(),
        decision_data=_decision_data(),
        risk_state=_risk_state(),
        activation_requested=True,
    )

    assert readiness.block_reason == READINESS_BLOCK_ACTIVATION_NOT_ALLOWED
    assert readiness.runtime_activation_allowed is False


def test_phase3_1_disabled_mode_is_not_safe_for_readiness_gate() -> None:
    gate = ExecutionSafeReadinessGate(facade=build_legacy_core_facade(mode="legacy-context-resolver"))
    readiness = gate.evaluate(
        routing_trace=PublicAppGatewayRoutingTrace(
            selected_mode=PUBLIC_APP_GATEWAY_DISABLED,
            selected_path=PUBLIC_APP_GATEWAY_DISABLED,
            platform_participated=False,
            adapter_enforced=False,
            runtime_activation_remained_disabled=True,
        ),
        facade_resolution=None,
        signal_data=_signal_data(),
        decision_data=_decision_data(),
        risk_state=_risk_state(),
    )

    assert readiness.block_reason == READINESS_BLOCK_ROUTING_NOT_SAFE


def test_phase3_1_gateway_boundary_has_no_direct_core_import_regression() -> None:
    gateway_boundary_files = (
        "/workspace/walker-ai-team/projects/polymarket/polyquantbot/platform/gateway/public_app_gateway.py",
        "/workspace/walker-ai-team/projects/polymarket/polyquantbot/platform/gateway/execution_readiness_gate.py",
    )

    for file_path in gateway_boundary_files:
        source = Path(file_path).read_text(encoding="utf-8")
        assert "projects.polymarket.polyquantbot.core" not in source
        assert "from ...core" not in source
