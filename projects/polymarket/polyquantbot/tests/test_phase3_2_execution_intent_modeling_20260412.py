from __future__ import annotations

from dataclasses import fields

from projects.polymarket.polyquantbot.platform.execution.execution_intent import (
    INTENT_BLOCK_RISK_VALIDATION_FAILED,
    ExecutionIntent,
    ExecutionIntentBuilder,
)


def _signal() -> dict[str, object]:
    return {
        "market_id": "MKT-3-2",
        "outcome": "YES",
        "side": "BUY",
        "size": 42.0,
        "price": 0.61,
        "confidence": 0.78,
        "source_signal_id": "SIG-3-2",
    }


def test_phase3_2_intent_created_when_readiness_passed() -> None:
    builder = ExecutionIntentBuilder()
    result = builder.build_with_trace(
        readiness_result={
            "can_execute": True,
            "block_reason": "phase3_2_ready",
            "readiness_checks": {"risk_validation_decision": "ALLOW"},
        },
        routing_result={"selected_mode": "platform-gateway-shadow"},
        signal=_signal(),
    )

    assert result.intent is not None
    assert result.intent.market_id == "MKT-3-2"
    assert result.intent.readiness_passed is True
    assert result.intent.risk_validated is True
    assert result.trace.intent_created is True
    assert result.trace.blocked_reason is None


def test_phase3_2_intent_blocked_when_readiness_false() -> None:
    builder = ExecutionIntentBuilder()
    result = builder.build_with_trace(
        readiness_result={
            "can_execute": False,
            "block_reason": "readiness_not_passed",
            "readiness_checks": {"risk_validation_decision": "ALLOW"},
        },
        routing_result={"selected_mode": "platform-gateway-shadow"},
        signal=_signal(),
    )

    assert result.intent is None
    assert result.trace.intent_created is False
    assert result.trace.blocked_reason == "readiness_not_passed"


def test_phase3_2_null_safety_for_upstream_inputs() -> None:
    builder = ExecutionIntentBuilder()
    result = builder.build_with_trace(
        readiness_result=None,
        routing_result=None,
        signal=None,
    )

    assert result.intent is None
    assert result.trace.intent_created is False
    assert result.trace.blocked_reason == "readiness_failed"
    assert result.trace.upstream_trace_refs["routing"]["selected_mode"] == "unknown"


def test_phase3_2_output_is_deterministic_for_same_inputs() -> None:
    builder = ExecutionIntentBuilder()
    readiness = {
        "can_execute": True,
        "block_reason": None,
        "readiness_checks": {"risk_validation_decision": "ALLOW"},
    }
    routing = {"selected_mode": "platform-gateway-primary"}
    signal = _signal()

    first = builder.build_with_trace(readiness_result=readiness, routing_result=routing, signal=signal)
    second = builder.build_with_trace(readiness_result=readiness, routing_result=routing, signal=signal)

    assert first == second


def test_phase3_2_risk_validation_cannot_be_bypassed() -> None:
    builder = ExecutionIntentBuilder()
    result = builder.build_with_trace(
        readiness_result={
            "can_execute": True,
            "block_reason": None,
            "readiness_checks": {"risk_validation_decision": "BLOCK"},
        },
        routing_result={"selected_mode": "platform-gateway-primary"},
        signal=_signal(),
    )

    assert result.intent is None
    assert result.trace.blocked_reason == INTENT_BLOCK_RISK_VALIDATION_FAILED


def test_phase3_2_execution_intent_has_no_activation_flags() -> None:
    field_names = {item.name for item in fields(ExecutionIntent)}

    assert "runtime_activation_allowed" not in field_names
    assert "activation_requested" not in field_names
