from __future__ import annotations

from dataclasses import fields

from projects.polymarket.polyquantbot.platform.execution.execution_intent import (
    INTENT_BLOCK_RISK_VALIDATION_FAILED,
    ExecutionIntent,
    ExecutionIntentBuilder,
    ExecutionIntentReadinessInput,
    ExecutionIntentRoutingInput,
    ExecutionIntentSignalInput,
)


def _signal() -> ExecutionIntentSignalInput:
    return ExecutionIntentSignalInput(
        market_id="MKT-3-2",
        outcome="YES",
        side="BUY",
        size=42.0,
        price=0.61,
        confidence=0.78,
        source_signal_id="SIG-3-2",
    )


def _routing() -> ExecutionIntentRoutingInput:
    return ExecutionIntentRoutingInput(routing_mode="platform-gateway-shadow")


def test_phase3_2_intent_created_when_readiness_passed() -> None:
    builder = ExecutionIntentBuilder()
    result = builder.build_with_trace(
        readiness_input=ExecutionIntentReadinessInput(
            can_execute=True,
            block_reason="phase3_2_ready",
            risk_validation_decision="ALLOW",
        ),
        routing_input=_routing(),
        signal_input=_signal(),
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
        readiness_input=ExecutionIntentReadinessInput(
            can_execute=False,
            block_reason="readiness_not_passed",
            risk_validation_decision="ALLOW",
        ),
        routing_input=_routing(),
        signal_input=_signal(),
    )

    assert result.intent is None
    assert result.trace.intent_created is False
    assert result.trace.blocked_reason == "readiness_not_passed"


def test_phase3_2_output_is_deterministic_for_same_inputs() -> None:
    builder = ExecutionIntentBuilder()
    readiness = ExecutionIntentReadinessInput(
        can_execute=True,
        block_reason=None,
        risk_validation_decision="ALLOW",
    )
    routing = ExecutionIntentRoutingInput(routing_mode="platform-gateway-primary")
    signal = _signal()

    first = builder.build_with_trace(readiness_input=readiness, routing_input=routing, signal_input=signal)
    second = builder.build_with_trace(readiness_input=readiness, routing_input=routing, signal_input=signal)

    assert first == second


def test_phase3_2_risk_validation_cannot_be_bypassed() -> None:
    builder = ExecutionIntentBuilder()
    result = builder.build_with_trace(
        readiness_input=ExecutionIntentReadinessInput(
            can_execute=True,
            block_reason=None,
            risk_validation_decision="BLOCK",
        ),
        routing_input=ExecutionIntentRoutingInput(routing_mode="platform-gateway-primary"),
        signal_input=_signal(),
    )

    assert result.intent is None
    assert result.trace.blocked_reason == INTENT_BLOCK_RISK_VALIDATION_FAILED


def test_phase3_2_execution_intent_has_no_activation_flags() -> None:
    field_names = {item.name for item in fields(ExecutionIntent)}

    assert "runtime_activation_allowed" not in field_names
    assert "activation_requested" not in field_names
