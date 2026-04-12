from __future__ import annotations

from dataclasses import fields, replace

from projects.polymarket.polyquantbot.platform.execution.execution_decision import (
    DECISION_BLOCK_INVALID_INTENT_CONTRACT,
    DECISION_BLOCK_INVALID_PLAN_CONTRACT,
    DECISION_BLOCK_INVALID_RISK_CONTRACT,
    DECISION_BLOCK_UPSTREAM_BLOCKED,
    DECISION_BLOCK_UPSTREAM_CONTRACT_MISMATCH,
    ExecutionDecision,
    ExecutionDecisionAggregator,
    ExecutionDecisionIntentInput,
    ExecutionDecisionPlanInput,
    ExecutionDecisionRiskInput,
)
from projects.polymarket.polyquantbot.platform.execution.execution_intent import ExecutionIntent
from projects.polymarket.polyquantbot.platform.execution.execution_plan import ExecutionPlan
from projects.polymarket.polyquantbot.platform.execution.execution_risk import ExecutionRiskDecision

VALID_INTENT = ExecutionIntent(
    market_id="MKT-3-6",
    outcome="YES",
    side="BUY",
    size=4.0,
    price=0.55,
    confidence=0.81,
    source_signal_id="SIG-3-6",
    routing_mode="platform-gateway-shadow",
    risk_validated=True,
    readiness_passed=True,
)

VALID_PLAN = ExecutionPlan(
    market_id="MKT-3-6",
    outcome="YES",
    side="BUY",
    size=4.0,
    routing_mode="platform-gateway-shadow",
    execution_mode="paper-prep-only",
    limit_price=0.55,
    slippage_bps=10,
    plan_ready=True,
    non_activating=True,
)

VALID_RISK = ExecutionRiskDecision(
    allowed=True,
    risk_score=0.34,
    blocked_reason=None,
    risk_flags=[],
    non_activating=True,
)

VALID_INTENT_INPUT = ExecutionDecisionIntentInput(
    intent=VALID_INTENT,
    source_trace_refs={"intent_trace_id": "INT-3-6"},
)
VALID_PLAN_INPUT = ExecutionDecisionPlanInput(
    plan=VALID_PLAN,
    source_trace_refs={"plan_trace_id": "PLAN-3-6"},
)
VALID_RISK_INPUT = ExecutionDecisionRiskInput(
    risk_decision=VALID_RISK,
    source_trace_refs={"risk_trace_id": "RISK-3-6"},
)


def test_phase3_6_valid_intent_plan_risk_allowed_produces_final_decision() -> None:
    aggregator = ExecutionDecisionAggregator()

    result = aggregator.aggregate_with_trace(
        intent_input=VALID_INTENT_INPUT,
        plan_input=VALID_PLAN_INPUT,
        risk_input=VALID_RISK_INPUT,
    )

    assert result.decision is not None
    assert result.decision.allowed is True
    assert result.decision.blocked_reason is None
    assert result.trace.decision_created is True


def test_phase3_6_invalid_intent_contract_blocked_deterministically() -> None:
    aggregator = ExecutionDecisionAggregator()
    result = aggregator.aggregate_with_trace(
        intent_input=None,  # type: ignore[arg-type]
        plan_input=VALID_PLAN_INPUT,
        risk_input=VALID_RISK_INPUT,
    )

    assert result.decision is not None
    assert result.decision.allowed is False
    assert result.decision.blocked_reason == DECISION_BLOCK_INVALID_INTENT_CONTRACT


def test_phase3_6_invalid_plan_contract_blocked_deterministically() -> None:
    aggregator = ExecutionDecisionAggregator()
    result = aggregator.aggregate_with_trace(
        intent_input=VALID_INTENT_INPUT,
        plan_input={"plan": "bad"},  # type: ignore[arg-type]
        risk_input=VALID_RISK_INPUT,
    )

    assert result.decision is not None
    assert result.decision.allowed is False
    assert result.decision.blocked_reason == DECISION_BLOCK_INVALID_PLAN_CONTRACT


def test_phase3_6_invalid_risk_contract_blocked_deterministically() -> None:
    aggregator = ExecutionDecisionAggregator()
    result = aggregator.aggregate_with_trace(
        intent_input=VALID_INTENT_INPUT,
        plan_input=VALID_PLAN_INPUT,
        risk_input=object(),  # type: ignore[arg-type]
    )

    assert result.decision is not None
    assert result.decision.allowed is False
    assert result.decision.blocked_reason == DECISION_BLOCK_INVALID_RISK_CONTRACT


def test_phase3_6_upstream_identity_mismatch_blocked_deterministically() -> None:
    aggregator = ExecutionDecisionAggregator()
    mismatch_plan = replace(VALID_PLAN, market_id="MKT-OTHER")
    result = aggregator.aggregate_with_trace(
        intent_input=VALID_INTENT_INPUT,
        plan_input=ExecutionDecisionPlanInput(plan=mismatch_plan),
        risk_input=VALID_RISK_INPUT,
    )

    assert result.decision is not None
    assert result.decision.allowed is False
    assert result.decision.blocked_reason == DECISION_BLOCK_UPSTREAM_CONTRACT_MISMATCH


def test_phase3_6_upstream_blocked_risk_propagates_deterministically() -> None:
    aggregator = ExecutionDecisionAggregator()
    blocked_risk = replace(VALID_RISK, allowed=False, blocked_reason="policy_block")

    result = aggregator.aggregate_with_trace(
        intent_input=VALID_INTENT_INPUT,
        plan_input=VALID_PLAN_INPUT,
        risk_input=ExecutionDecisionRiskInput(risk_decision=blocked_risk),
    )

    assert result.decision is not None
    assert result.decision.allowed is False
    assert result.decision.blocked_reason == DECISION_BLOCK_UPSTREAM_BLOCKED


def test_phase3_6_allowed_final_decision_still_not_ready_for_execution() -> None:
    aggregator = ExecutionDecisionAggregator()
    decision = aggregator.aggregate(
        intent_input=VALID_INTENT_INPUT,
        plan_input=VALID_PLAN_INPUT,
        risk_input=VALID_RISK_INPUT,
    )

    assert decision is not None
    assert decision.allowed is True
    assert decision.ready_for_execution is False


def test_phase3_6_non_activating_remains_true() -> None:
    aggregator = ExecutionDecisionAggregator()
    result = aggregator.aggregate_with_trace(
        intent_input=VALID_INTENT_INPUT,
        plan_input=VALID_PLAN_INPUT,
        risk_input=VALID_RISK_INPUT,
    )

    assert result.decision is not None
    assert result.decision.non_activating is True


def test_phase3_6_deterministic_equality_for_same_valid_inputs() -> None:
    aggregator = ExecutionDecisionAggregator()
    first = aggregator.aggregate_with_trace(
        intent_input=VALID_INTENT_INPUT,
        plan_input=VALID_PLAN_INPUT,
        risk_input=VALID_RISK_INPUT,
    )
    second = aggregator.aggregate_with_trace(
        intent_input=VALID_INTENT_INPUT,
        plan_input=VALID_PLAN_INPUT,
        risk_input=VALID_RISK_INPUT,
    )

    assert first == second


def test_phase3_6_no_wallet_signing_activation_order_submission_fields_introduced() -> None:
    field_names = {item.name for item in fields(ExecutionDecision)}

    assert "wallet_address" not in field_names
    assert "private_key" not in field_names
    assert "signature" not in field_names
    assert "submit_order" not in field_names
    assert "order_submission_hook" not in field_names
    assert "activate_runtime_execution" not in field_names


def test_phase3_6_none_dict_wrong_object_inputs_do_not_crash() -> None:
    aggregator = ExecutionDecisionAggregator()

    none_result = aggregator.aggregate_with_trace(
        intent_input=None,  # type: ignore[arg-type]
        plan_input=VALID_PLAN_INPUT,
        risk_input=VALID_RISK_INPUT,
    )
    assert none_result.decision is not None
    assert none_result.decision.blocked_reason == DECISION_BLOCK_INVALID_INTENT_CONTRACT

    dict_result = aggregator.aggregate_with_trace(
        intent_input=VALID_INTENT_INPUT,
        plan_input=None,  # type: ignore[arg-type]
        risk_input=VALID_RISK_INPUT,
    )
    assert dict_result.decision is not None
    assert dict_result.decision.blocked_reason == DECISION_BLOCK_INVALID_PLAN_CONTRACT

    wrong_object_result = aggregator.aggregate_with_trace(
        intent_input=VALID_INTENT_INPUT,
        plan_input=VALID_PLAN_INPUT,
        risk_input=None,  # type: ignore[arg-type]
    )
    assert wrong_object_result.decision is not None
    assert wrong_object_result.decision.blocked_reason == DECISION_BLOCK_INVALID_RISK_CONTRACT
