from __future__ import annotations

from dataclasses import fields

from projects.polymarket.polyquantbot.platform.execution.execution_intent import (
    INTENT_BLOCK_INVALID_READINESS_CONTRACT,
    INTENT_BLOCK_INVALID_ROUTING_CONTRACT,
    INTENT_BLOCK_INVALID_SIGNAL_CONTRACT,
    INTENT_BLOCK_RISK_VALIDATION_FAILED,
    ExecutionIntent,
    ExecutionIntentBuilder,
    ExecutionIntentReadinessInput,
    ExecutionIntentRoutingInput,
    ExecutionIntentSignalInput,
)


VALID_READINESS = ExecutionIntentReadinessInput(
    can_execute=True,
    block_reason=None,
    risk_validation_decision="ALLOW",
)
VALID_ROUTING = ExecutionIntentRoutingInput(routing_mode="platform-gateway-shadow")
VALID_SIGNAL = ExecutionIntentSignalInput(
    market_id="MKT-3-3",
    outcome="YES",
    side="BUY",
    size=10.0,
    price=0.56,
    confidence=0.81,
    source_signal_id="SIG-3-3",
)


def test_phase3_3_valid_typed_contract_path() -> None:
    builder = ExecutionIntentBuilder()

    result = builder.build_with_trace(
        readiness_input=VALID_READINESS,
        routing_input=VALID_ROUTING,
        signal_input=VALID_SIGNAL,
    )

    assert result.intent is not None
    assert result.intent.market_id == "MKT-3-3"
    assert result.trace.intent_created is True


def test_phase3_3_readiness_input_none_is_blocked_without_exception() -> None:
    builder = ExecutionIntentBuilder()
    result = builder.build_with_trace(
        readiness_input=None,  # type: ignore[arg-type]
        routing_input=VALID_ROUTING,
        signal_input=VALID_SIGNAL,
    )

    assert result.intent is None
    assert result.trace.blocked_reason == INTENT_BLOCK_INVALID_READINESS_CONTRACT


def test_phase3_3_routing_input_none_is_blocked_without_exception() -> None:
    builder = ExecutionIntentBuilder()
    result = builder.build_with_trace(
        readiness_input=VALID_READINESS,
        routing_input=None,  # type: ignore[arg-type]
        signal_input=VALID_SIGNAL,
    )

    assert result.intent is None
    assert result.trace.blocked_reason == INTENT_BLOCK_INVALID_ROUTING_CONTRACT


def test_phase3_3_signal_input_none_is_blocked_without_exception() -> None:
    builder = ExecutionIntentBuilder()
    result = builder.build_with_trace(
        readiness_input=VALID_READINESS,
        routing_input=VALID_ROUTING,
        signal_input=None,  # type: ignore[arg-type]
    )

    assert result.intent is None
    assert result.trace.blocked_reason == INTENT_BLOCK_INVALID_SIGNAL_CONTRACT


def test_phase3_3_readiness_dict_input_rejected_deterministically() -> None:
    builder = ExecutionIntentBuilder()
    result = builder.build_with_trace(
        readiness_input={"can_execute": True},  # type: ignore[arg-type]
        routing_input=VALID_ROUTING,
        signal_input=VALID_SIGNAL,
    )

    assert result.intent is None
    assert result.trace.blocked_reason == INTENT_BLOCK_INVALID_READINESS_CONTRACT


def test_phase3_3_wrong_object_type_rejected_deterministically() -> None:
    builder = ExecutionIntentBuilder()
    result = builder.build_with_trace(
        readiness_input=VALID_READINESS,
        routing_input=VALID_ROUTING,
        signal_input=object(),  # type: ignore[arg-type]
    )

    assert result.intent is None
    assert result.trace.blocked_reason == INTENT_BLOCK_INVALID_SIGNAL_CONTRACT


def test_phase3_3_invalid_market_id_rejected() -> None:
    builder = ExecutionIntentBuilder()
    result = builder.build_with_trace(
        readiness_input=VALID_READINESS,
        routing_input=VALID_ROUTING,
        signal_input=ExecutionIntentSignalInput(
            market_id="",
            outcome="YES",
            side="BUY",
            size=10.0,
            price=None,
            confidence=None,
            source_signal_id=None,
        ),
    )

    assert result.intent is None
    assert result.trace.blocked_reason == INTENT_BLOCK_INVALID_SIGNAL_CONTRACT


def test_phase3_3_invalid_outcome_rejected() -> None:
    builder = ExecutionIntentBuilder()
    result = builder.build_with_trace(
        readiness_input=VALID_READINESS,
        routing_input=VALID_ROUTING,
        signal_input=ExecutionIntentSignalInput(
            market_id="MKT-3-3",
            outcome=" ",
            side="BUY",
            size=10.0,
            price=None,
            confidence=None,
            source_signal_id=None,
        ),
    )

    assert result.intent is None
    assert result.trace.blocked_reason == INTENT_BLOCK_INVALID_SIGNAL_CONTRACT


def test_phase3_3_invalid_side_rejected() -> None:
    builder = ExecutionIntentBuilder()
    result = builder.build_with_trace(
        readiness_input=VALID_READINESS,
        routing_input=VALID_ROUTING,
        signal_input=ExecutionIntentSignalInput(
            market_id="MKT-3-3",
            outcome="YES",
            side="HOLD",
            size=10.0,
            price=None,
            confidence=None,
            source_signal_id=None,
        ),
    )

    assert result.intent is None
    assert result.trace.blocked_reason == INTENT_BLOCK_INVALID_SIGNAL_CONTRACT


def test_phase3_3_invalid_size_rejected() -> None:
    builder = ExecutionIntentBuilder()
    result = builder.build_with_trace(
        readiness_input=VALID_READINESS,
        routing_input=VALID_ROUTING,
        signal_input=ExecutionIntentSignalInput(
            market_id="MKT-3-3",
            outcome="YES",
            side="BUY",
            size=-1.0,
            price=None,
            confidence=None,
            source_signal_id=None,
        ),
    )

    assert result.intent is None
    assert result.trace.blocked_reason == INTENT_BLOCK_INVALID_SIGNAL_CONTRACT


def test_phase3_3_invalid_routing_contract_rejected() -> None:
    builder = ExecutionIntentBuilder()
    result = builder.build_with_trace(
        readiness_input=VALID_READINESS,
        routing_input=ExecutionIntentRoutingInput(routing_mode="unknown"),
        signal_input=VALID_SIGNAL,
    )

    assert result.intent is None
    assert result.trace.blocked_reason == INTENT_BLOCK_INVALID_ROUTING_CONTRACT


def test_phase3_3_readiness_false_still_blocks() -> None:
    builder = ExecutionIntentBuilder()
    result = builder.build_with_trace(
        readiness_input=ExecutionIntentReadinessInput(
            can_execute=False,
            block_reason="readiness_gate_block",
            risk_validation_decision="ALLOW",
        ),
        routing_input=ExecutionIntentRoutingInput(routing_mode="unknown"),
        signal_input=ExecutionIntentSignalInput(
            market_id="",
            outcome="",
            side="HOLD",
            size=-1.0,
            price=None,
            confidence=None,
            source_signal_id=None,
        ),
    )

    assert result.intent is None
    assert result.trace.blocked_reason == "readiness_gate_block"


def test_phase3_3_risk_not_allow_still_blocks() -> None:
    builder = ExecutionIntentBuilder()
    result = builder.build_with_trace(
        readiness_input=ExecutionIntentReadinessInput(
            can_execute=True,
            block_reason=None,
            risk_validation_decision="BLOCK",
        ),
        routing_input=VALID_ROUTING,
        signal_input=VALID_SIGNAL,
    )

    assert result.intent is None
    assert result.trace.blocked_reason == INTENT_BLOCK_RISK_VALIDATION_FAILED


def test_phase3_3_deterministic_equality_for_same_valid_input() -> None:
    builder = ExecutionIntentBuilder()

    first = builder.build_with_trace(
        readiness_input=VALID_READINESS,
        routing_input=VALID_ROUTING,
        signal_input=VALID_SIGNAL,
    )
    second = builder.build_with_trace(
        readiness_input=VALID_READINESS,
        routing_input=VALID_ROUTING,
        signal_input=VALID_SIGNAL,
    )

    assert first == second


def test_phase3_3_no_activation_fields_introduced() -> None:
    field_names = {item.name for item in fields(ExecutionIntent)}

    assert "runtime_activation_allowed" not in field_names
    assert "activation_requested" not in field_names
