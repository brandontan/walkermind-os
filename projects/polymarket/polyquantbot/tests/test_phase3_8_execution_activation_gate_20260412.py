from __future__ import annotations

from dataclasses import fields, replace

from projects.polymarket.polyquantbot.platform.execution.execution_activation_gate import (
    ACTIVATION_BLOCK_ACTIVATION_DISABLED,
    ACTIVATION_BLOCK_ACTIVATION_MODE_NOT_ALLOWED,
    ACTIVATION_BLOCK_ALREADY_READY_FOR_EXECUTION,
    ACTIVATION_BLOCK_INVALID_DECISION_INPUT,
    ACTIVATION_BLOCK_INVALID_DECISION_INPUT_CONTRACT,
    ACTIVATION_BLOCK_INVALID_POLICY_INPUT,
    ACTIVATION_BLOCK_INVALID_POLICY_INPUT_CONTRACT,
    ACTIVATION_BLOCK_SIMULATION_ONLY_REQUIRED,
    ACTIVATION_BLOCK_SOURCE_NON_ACTIVATING_REQUIRED,
    ACTIVATION_BLOCK_UPSTREAM_DECISION_BLOCKED,
    ExecutionActivationDecision,
    ExecutionActivationDecisionInput,
    ExecutionActivationGate,
    ExecutionActivationPolicyInput,
)
from projects.polymarket.polyquantbot.platform.execution.execution_decision import ExecutionDecision

VALID_DECISION = ExecutionDecision(
    allowed=True,
    blocked_reason=None,
    market_id="MKT-3-8",
    outcome="YES",
    side="BUY",
    size=4.0,
    routing_mode="platform-gateway-shadow",
    execution_mode="paper-prep-only",
    ready_for_execution=False,
    non_activating=True,
)

VALID_DECISION_INPUT = ExecutionActivationDecisionInput(
    decision=VALID_DECISION,
    activation_mode="manual-review-approved",
    source_trace_refs={"decision_trace_id": "DEC-3-8"},
)

VALID_POLICY_INPUT = ExecutionActivationPolicyInput(
    activation_enabled=True,
    allowed_activation_modes=("manual-review-approved",),
    require_non_activating_source=True,
    allow_simulation_only=True,
    policy_trace_refs={"policy_trace_id": "POL-3-8"},
)


def test_phase3_8_valid_decision_policy_and_mode_produce_activation_deterministically() -> None:
    gate = ExecutionActivationGate()

    result = gate.evaluate_with_trace(
        decision_input=VALID_DECISION_INPUT,
        policy_input=VALID_POLICY_INPUT,
    )

    assert result.decision is not None
    assert result.decision.activated is True
    assert result.decision.activation_allowed is True
    assert result.decision.ready_for_execution is True
    assert result.trace.decision_created is True


def test_phase3_8_invalid_top_level_decision_input_contract_blocked_deterministically() -> None:
    gate = ExecutionActivationGate()
    result = gate.evaluate_with_trace(
        decision_input=None,  # type: ignore[arg-type]
        policy_input=VALID_POLICY_INPUT,
    )

    assert result.decision is not None
    assert result.decision.activated is False
    assert result.decision.blocked_reason == ACTIVATION_BLOCK_INVALID_DECISION_INPUT_CONTRACT


def test_phase3_8_invalid_top_level_policy_input_contract_blocked_deterministically() -> None:
    gate = ExecutionActivationGate()
    result = gate.evaluate_with_trace(
        decision_input=VALID_DECISION_INPUT,
        policy_input={"activation_enabled": True},  # type: ignore[arg-type]
    )

    assert result.decision is not None
    assert result.decision.activated is False
    assert result.decision.blocked_reason == ACTIVATION_BLOCK_INVALID_POLICY_INPUT_CONTRACT


def test_phase3_8_invalid_inner_decision_blocked_deterministically() -> None:
    gate = ExecutionActivationGate()
    invalid_source = replace(VALID_DECISION, market_id="")

    result = gate.evaluate_with_trace(
        decision_input=ExecutionActivationDecisionInput(
            decision=invalid_source,
            activation_mode="manual-review-approved",
        ),
        policy_input=VALID_POLICY_INPUT,
    )

    assert result.decision is not None
    assert result.decision.activated is False
    assert result.decision.blocked_reason == ACTIVATION_BLOCK_INVALID_DECISION_INPUT


def test_phase3_8_invalid_policy_fields_blocked_deterministically() -> None:
    gate = ExecutionActivationGate()
    invalid_policy = ExecutionActivationPolicyInput(
        activation_enabled=True,
        allowed_activation_modes=(),
    )

    result = gate.evaluate_with_trace(
        decision_input=VALID_DECISION_INPUT,
        policy_input=invalid_policy,
    )

    assert result.decision is not None
    assert result.decision.activated is False
    assert result.decision.blocked_reason == ACTIVATION_BLOCK_INVALID_POLICY_INPUT


def test_phase3_8_upstream_blocked_decision_propagates_deterministically() -> None:
    gate = ExecutionActivationGate()
    blocked_upstream_decision = replace(
        VALID_DECISION,
        allowed=False,
        blocked_reason="risk_blocked",
    )

    result = gate.evaluate_with_trace(
        decision_input=ExecutionActivationDecisionInput(
            decision=blocked_upstream_decision,
            activation_mode="manual-review-approved",
        ),
        policy_input=VALID_POLICY_INPUT,
    )

    assert result.decision is not None
    assert result.decision.activated is False
    assert result.decision.blocked_reason == ACTIVATION_BLOCK_UPSTREAM_DECISION_BLOCKED


def test_phase3_8_activation_disabled_blocks_deterministically() -> None:
    gate = ExecutionActivationGate()
    policy = replace(VALID_POLICY_INPUT, activation_enabled=False)

    result = gate.evaluate_with_trace(
        decision_input=VALID_DECISION_INPUT,
        policy_input=policy,
    )

    assert result.decision is not None
    assert result.decision.blocked_reason == ACTIVATION_BLOCK_ACTIVATION_DISABLED


def test_phase3_8_activation_mode_not_allowed_blocks_deterministically() -> None:
    gate = ExecutionActivationGate()

    result = gate.evaluate_with_trace(
        decision_input=replace(VALID_DECISION_INPUT, activation_mode="not-on-allow-list"),
        policy_input=VALID_POLICY_INPUT,
    )

    assert result.decision is not None
    assert result.decision.blocked_reason == ACTIVATION_BLOCK_ACTIVATION_MODE_NOT_ALLOWED


def test_phase3_8_already_ready_for_execution_blocks_deterministically() -> None:
    gate = ExecutionActivationGate()
    already_ready = replace(VALID_DECISION, ready_for_execution=True)

    result = gate.evaluate_with_trace(
        decision_input=ExecutionActivationDecisionInput(
            decision=already_ready,
            activation_mode="manual-review-approved",
        ),
        policy_input=VALID_POLICY_INPUT,
    )

    assert result.decision is not None
    assert result.decision.blocked_reason == ACTIVATION_BLOCK_ALREADY_READY_FOR_EXECUTION


def test_phase3_8_source_non_activating_requirement_enforced() -> None:
    gate = ExecutionActivationGate()
    activating_source = replace(VALID_DECISION, non_activating=False)

    result = gate.evaluate_with_trace(
        decision_input=ExecutionActivationDecisionInput(
            decision=activating_source,
            activation_mode="manual-review-approved",
        ),
        policy_input=VALID_POLICY_INPUT,
    )

    assert result.decision is not None
    assert result.decision.blocked_reason == ACTIVATION_BLOCK_SOURCE_NON_ACTIVATING_REQUIRED


def test_phase3_8_simulation_only_requirement_enforced() -> None:
    gate = ExecutionActivationGate()
    non_simulation_decision = replace(VALID_DECISION, execution_mode="live-routing-ready")

    result = gate.evaluate_with_trace(
        decision_input=ExecutionActivationDecisionInput(
            decision=non_simulation_decision,
            activation_mode="manual-review-approved",
        ),
        policy_input=VALID_POLICY_INPUT,
    )

    assert result.decision is not None
    assert result.decision.blocked_reason == ACTIVATION_BLOCK_SIMULATION_ONLY_REQUIRED


def test_phase3_8_deterministic_equality_for_same_valid_input() -> None:
    gate = ExecutionActivationGate()
    first = gate.evaluate_with_trace(
        decision_input=VALID_DECISION_INPUT,
        policy_input=VALID_POLICY_INPUT,
    )
    second = gate.evaluate_with_trace(
        decision_input=VALID_DECISION_INPUT,
        policy_input=VALID_POLICY_INPUT,
    )

    assert first == second


def test_phase3_8_no_wallet_signing_network_order_submission_capital_fields_introduced() -> None:
    field_names = {item.name for item in fields(ExecutionActivationDecision)}

    assert "wallet_address" not in field_names
    assert "signature" not in field_names
    assert "private_key" not in field_names
    assert "submit_order" not in field_names
    assert "network_client" not in field_names
    assert "capital_transfer" not in field_names


def test_phase3_8_none_dict_wrong_object_inputs_do_not_crash() -> None:
    gate = ExecutionActivationGate()

    none_result = gate.evaluate_with_trace(
        decision_input=None,  # type: ignore[arg-type]
        policy_input=VALID_POLICY_INPUT,
    )
    assert none_result.decision is not None
    assert none_result.decision.blocked_reason == ACTIVATION_BLOCK_INVALID_DECISION_INPUT_CONTRACT

    dict_policy_result = gate.evaluate_with_trace(
        decision_input=VALID_DECISION_INPUT,
        policy_input=None,  # type: ignore[arg-type]
    )
    assert dict_policy_result.decision is not None
    assert dict_policy_result.decision.blocked_reason == ACTIVATION_BLOCK_INVALID_POLICY_INPUT_CONTRACT

    wrong_inner_decision_result = gate.evaluate_with_trace(
        decision_input=ExecutionActivationDecisionInput(
            decision=None,  # type: ignore[arg-type]
            activation_mode="manual-review-approved",
        ),
        policy_input=VALID_POLICY_INPUT,
    )
    assert wrong_inner_decision_result.decision is not None
    assert wrong_inner_decision_result.decision.blocked_reason == ACTIVATION_BLOCK_INVALID_DECISION_INPUT
