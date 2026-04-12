from __future__ import annotations

from dataclasses import fields, replace

from projects.polymarket.polyquantbot.platform.execution.execution_plan import ExecutionPlan
from projects.polymarket.polyquantbot.platform.execution.execution_risk import (
    RISK_BLOCK_EXECUTION_MODE_NOT_ALLOWED,
    RISK_BLOCK_INVALID_PLAN_INPUT,
    RISK_BLOCK_INVALID_PLAN_INPUT_CONTRACT,
    RISK_BLOCK_INVALID_POLICY_INPUT,
    RISK_BLOCK_INVALID_POLICY_INPUT_CONTRACT,
    RISK_BLOCK_NON_ACTIVATING_REQUIRED,
    RISK_BLOCK_SIZE_EXCEEDS_POLICY_CAP,
    RISK_BLOCK_SLIPPAGE_EXCEEDS_POLICY_CAP,
    ExecutionRiskEvaluator,
    ExecutionRiskPlanInput,
    ExecutionRiskPolicyInput,
)

VALID_PLAN = ExecutionPlan(
    market_id="MKT-3-5",
    outcome="YES",
    side="BUY",
    size=3.0,
    routing_mode="platform-gateway-shadow",
    execution_mode="paper-prep-only",
    limit_price=0.52,
    slippage_bps=10,
    plan_ready=True,
    non_activating=True,
)

VALID_PLAN_INPUT = ExecutionRiskPlanInput(
    plan=VALID_PLAN,
    source_trace_refs={"phase": "3.5", "plan_trace_id": "PLAN-3-5"},
)

VALID_POLICY = ExecutionRiskPolicyInput(
    max_size=10.0,
    max_slippage_bps=25,
    allowed_sides=("BUY", "SELL"),
    allowed_routing_modes=("platform-gateway-shadow", "platform-gateway-primary"),
    allowed_execution_modes=("paper-prep-only",),
    require_non_activating=True,
    policy_trace_refs={"policy_trace_id": "POL-3-5"},
)


def test_phase3_5_valid_plan_and_policy_produce_allowed_decision() -> None:
    evaluator = ExecutionRiskEvaluator()

    result = evaluator.evaluate_with_trace(
        plan_input=VALID_PLAN_INPUT,
        policy_input=VALID_POLICY,
    )

    assert result.decision is not None
    assert result.decision.allowed is True
    assert result.decision.blocked_reason is None
    assert result.trace.decision_created is True


def test_phase3_5_invalid_plan_contract_blocked_deterministically() -> None:
    evaluator = ExecutionRiskEvaluator()
    result = evaluator.evaluate_with_trace(
        plan_input=None,  # type: ignore[arg-type]
        policy_input=VALID_POLICY,
    )

    assert result.decision is not None
    assert result.decision.allowed is False
    assert result.decision.blocked_reason == RISK_BLOCK_INVALID_PLAN_INPUT_CONTRACT


def test_phase3_5_invalid_policy_contract_blocked_deterministically() -> None:
    evaluator = ExecutionRiskEvaluator()
    result = evaluator.evaluate_with_trace(
        plan_input=VALID_PLAN_INPUT,
        policy_input={"max_size": 1.0},  # type: ignore[arg-type]
    )

    assert result.decision is not None
    assert result.decision.allowed is False
    assert result.decision.blocked_reason == RISK_BLOCK_INVALID_POLICY_INPUT_CONTRACT


def test_phase3_5_invalid_plan_fields_blocked_deterministically() -> None:
    evaluator = ExecutionRiskEvaluator()
    invalid_plan = replace(VALID_PLAN, size=-1.0)
    result = evaluator.evaluate_with_trace(
        plan_input=ExecutionRiskPlanInput(plan=invalid_plan),
        policy_input=VALID_POLICY,
    )

    assert result.decision is not None
    assert result.decision.allowed is False
    assert result.decision.blocked_reason == RISK_BLOCK_INVALID_PLAN_INPUT


def test_phase3_5_invalid_policy_fields_blocked_deterministically() -> None:
    evaluator = ExecutionRiskEvaluator()
    invalid_policy = replace(VALID_POLICY, allowed_execution_modes=())
    result = evaluator.evaluate_with_trace(
        plan_input=VALID_PLAN_INPUT,
        policy_input=invalid_policy,
    )

    assert result.decision is not None
    assert result.decision.allowed is False
    assert result.decision.blocked_reason == RISK_BLOCK_INVALID_POLICY_INPUT


def test_phase3_5_size_cap_violation_blocked_deterministically() -> None:
    evaluator = ExecutionRiskEvaluator()
    size_policy = replace(VALID_POLICY, max_size=2.0)
    result = evaluator.evaluate_with_trace(
        plan_input=VALID_PLAN_INPUT,
        policy_input=size_policy,
    )

    assert result.decision is not None
    assert result.decision.allowed is False
    assert result.decision.blocked_reason == RISK_BLOCK_SIZE_EXCEEDS_POLICY_CAP


def test_phase3_5_slippage_cap_violation_blocked_deterministically() -> None:
    evaluator = ExecutionRiskEvaluator()
    slippage_policy = replace(VALID_POLICY, max_slippage_bps=5)
    result = evaluator.evaluate_with_trace(
        plan_input=VALID_PLAN_INPUT,
        policy_input=slippage_policy,
    )

    assert result.decision is not None
    assert result.decision.allowed is False
    assert result.decision.blocked_reason == RISK_BLOCK_SLIPPAGE_EXCEEDS_POLICY_CAP


def test_phase3_5_execution_mode_not_allowed_blocked_deterministically() -> None:
    evaluator = ExecutionRiskEvaluator()
    execution_mode_policy = replace(VALID_POLICY, allowed_execution_modes=("live",))
    result = evaluator.evaluate_with_trace(
        plan_input=VALID_PLAN_INPUT,
        policy_input=execution_mode_policy,
    )

    assert result.decision is not None
    assert result.decision.allowed is False
    assert result.decision.blocked_reason == RISK_BLOCK_EXECUTION_MODE_NOT_ALLOWED


def test_phase3_5_non_activating_requirement_enforced() -> None:
    evaluator = ExecutionRiskEvaluator()
    activating_plan = replace(VALID_PLAN, non_activating=False)
    result = evaluator.evaluate_with_trace(
        plan_input=ExecutionRiskPlanInput(plan=activating_plan),
        policy_input=VALID_POLICY,
    )

    assert result.decision is not None
    assert result.decision.allowed is False
    assert result.decision.blocked_reason == RISK_BLOCK_NON_ACTIVATING_REQUIRED


def test_phase3_5_deterministic_equality_for_same_valid_input() -> None:
    evaluator = ExecutionRiskEvaluator()
    first = evaluator.evaluate_with_trace(
        plan_input=VALID_PLAN_INPUT,
        policy_input=VALID_POLICY,
    )
    second = evaluator.evaluate_with_trace(
        plan_input=VALID_PLAN_INPUT,
        policy_input=VALID_POLICY,
    )

    assert first == second


def test_phase3_5_no_wallet_signing_activation_fields_introduced() -> None:
    field_names = {item.name for item in fields(ExecutionPlan)}

    assert "wallet_address" not in field_names
    assert "private_key" not in field_names
    assert "signature" not in field_names
    assert "order_submission_hook" not in field_names
    assert "activate_runtime_execution" not in field_names


def test_phase3_5_none_dict_wrong_object_inputs_do_not_crash() -> None:
    evaluator = ExecutionRiskEvaluator()

    none_result = evaluator.evaluate_with_trace(
        plan_input=None,  # type: ignore[arg-type]
        policy_input=VALID_POLICY,
    )
    assert none_result.decision is not None
    assert none_result.decision.blocked_reason == RISK_BLOCK_INVALID_PLAN_INPUT_CONTRACT

    dict_result = evaluator.evaluate_with_trace(
        plan_input=VALID_PLAN_INPUT,
        policy_input=None,  # type: ignore[arg-type]
    )
    assert dict_result.decision is not None
    assert dict_result.decision.blocked_reason == RISK_BLOCK_INVALID_POLICY_INPUT_CONTRACT

    wrong_object_result = evaluator.evaluate_with_trace(
        plan_input=object(),  # type: ignore[arg-type]
        policy_input=VALID_POLICY,
    )
    assert wrong_object_result.decision is not None
    assert wrong_object_result.decision.blocked_reason == RISK_BLOCK_INVALID_PLAN_INPUT_CONTRACT
