from __future__ import annotations

from dataclasses import fields

from projects.polymarket.polyquantbot.platform.execution.execution_plan import (
    PLAN_BLOCK_INVALID_INTENT_CONTRACT,
    PLAN_BLOCK_INVALID_INTENT_INPUT,
    PLAN_BLOCK_INVALID_MARKET_CONTEXT,
    PLAN_BLOCK_INVALID_MARKET_CONTEXT_CONTRACT,
    PLAN_BLOCK_MARKET_CONTEXT_MISMATCH,
    PLAN_BLOCK_MARKET_NOT_PLANNABLE,
    ExecutionPlan,
    ExecutionPlanBuilder,
    ExecutionPlanIntentInput,
    ExecutionPlanMarketContextInput,
)


VALID_INTENT = ExecutionPlanIntentInput(
    market_id="MKT-3-4",
    outcome="YES",
    side="BUY",
    size=8.0,
    routing_mode="platform-gateway-shadow",
    limit_price_hint=0.47,
    source_trace_refs={"intent_trace_id": "INT-3-4"},
)

VALID_MARKET_CONTEXT = ExecutionPlanMarketContextInput(
    market_id="MKT-3-4",
    outcome="YES",
    planning_allowed=True,
    execution_mode_label="paper-prep-only",
    reference_price=0.46,
    slippage_bps_hint=12,
    upstream_trace_refs={"market_trace_id": "MKT-TRACE-3-4"},
)


def test_phase3_4_valid_intent_produces_plan() -> None:
    builder = ExecutionPlanBuilder()

    result = builder.build_with_trace(
        intent_input=VALID_INTENT,
        market_context_input=VALID_MARKET_CONTEXT,
    )

    assert result.plan is not None
    assert result.plan.market_id == "MKT-3-4"
    assert result.plan.execution_mode == "paper-prep-only"
    assert result.trace.plan_created is True
    assert result.trace.blocked_reason is None


def test_phase3_4_invalid_intent_contract_blocked_deterministically() -> None:
    builder = ExecutionPlanBuilder()
    result = builder.build_with_trace(
        intent_input=None,  # type: ignore[arg-type]
        market_context_input=VALID_MARKET_CONTEXT,
    )

    assert result.plan is None
    assert result.trace.blocked_reason == PLAN_BLOCK_INVALID_INTENT_CONTRACT


def test_phase3_4_invalid_market_context_contract_blocked_deterministically() -> None:
    builder = ExecutionPlanBuilder()
    result = builder.build_with_trace(
        intent_input=VALID_INTENT,
        market_context_input={"market_id": "MKT-3-4"},  # type: ignore[arg-type]
    )

    assert result.plan is None
    assert result.trace.blocked_reason == PLAN_BLOCK_INVALID_MARKET_CONTEXT_CONTRACT


def test_phase3_4_deterministic_equality_for_same_valid_input() -> None:
    builder = ExecutionPlanBuilder()
    first = builder.build_with_trace(
        intent_input=VALID_INTENT,
        market_context_input=VALID_MARKET_CONTEXT,
    )
    second = builder.build_with_trace(
        intent_input=VALID_INTENT,
        market_context_input=VALID_MARKET_CONTEXT,
    )

    assert first == second


def test_phase3_4_non_activating_always_true() -> None:
    builder = ExecutionPlanBuilder()
    plan = builder.build_from_intent(
        intent_input=VALID_INTENT,
        market_context_input=VALID_MARKET_CONTEXT,
    )

    assert plan is not None
    assert plan.non_activating is True
    assert plan.plan_ready is True


def test_phase3_4_no_wallet_signing_activation_fields_introduced() -> None:
    field_names = {item.name for item in fields(ExecutionPlan)}

    assert "wallet_address" not in field_names
    assert "private_key" not in field_names
    assert "signature" not in field_names
    assert "order_submission_hook" not in field_names
    assert "activate_runtime_execution" not in field_names


def test_phase3_4_invalid_side_routing_size_market_outcome_blocked() -> None:
    builder = ExecutionPlanBuilder()

    invalid_side_result = builder.build_with_trace(
        intent_input=ExecutionPlanIntentInput(
            market_id="MKT-3-4",
            outcome="YES",
            side="HOLD",
            size=1.0,
            routing_mode="platform-gateway-shadow",
        ),
        market_context_input=VALID_MARKET_CONTEXT,
    )
    assert invalid_side_result.plan is None
    assert invalid_side_result.trace.blocked_reason == PLAN_BLOCK_INVALID_INTENT_INPUT

    invalid_routing_result = builder.build_with_trace(
        intent_input=ExecutionPlanIntentInput(
            market_id="MKT-3-4",
            outcome="YES",
            side="BUY",
            size=1.0,
            routing_mode="unknown",
        ),
        market_context_input=VALID_MARKET_CONTEXT,
    )
    assert invalid_routing_result.plan is None
    assert invalid_routing_result.trace.blocked_reason == PLAN_BLOCK_INVALID_INTENT_INPUT

    invalid_size_result = builder.build_with_trace(
        intent_input=ExecutionPlanIntentInput(
            market_id="MKT-3-4",
            outcome="YES",
            side="BUY",
            size=-0.5,
            routing_mode="platform-gateway-shadow",
        ),
        market_context_input=VALID_MARKET_CONTEXT,
    )
    assert invalid_size_result.plan is None
    assert invalid_size_result.trace.blocked_reason == PLAN_BLOCK_INVALID_INTENT_INPUT

    invalid_market_result = builder.build_with_trace(
        intent_input=ExecutionPlanIntentInput(
            market_id=" ",
            outcome="YES",
            side="BUY",
            size=1.0,
            routing_mode="platform-gateway-shadow",
        ),
        market_context_input=VALID_MARKET_CONTEXT,
    )
    assert invalid_market_result.plan is None
    assert invalid_market_result.trace.blocked_reason == PLAN_BLOCK_INVALID_INTENT_INPUT

    invalid_outcome_result = builder.build_with_trace(
        intent_input=ExecutionPlanIntentInput(
            market_id="MKT-3-4",
            outcome=" ",
            side="BUY",
            size=1.0,
            routing_mode="platform-gateway-shadow",
        ),
        market_context_input=VALID_MARKET_CONTEXT,
    )
    assert invalid_outcome_result.plan is None
    assert invalid_outcome_result.trace.blocked_reason == PLAN_BLOCK_INVALID_INTENT_INPUT


def test_phase3_4_market_context_validation_and_mismatch_blocked() -> None:
    builder = ExecutionPlanBuilder()
    invalid_context = builder.build_with_trace(
        intent_input=VALID_INTENT,
        market_context_input=ExecutionPlanMarketContextInput(
            market_id="MKT-3-4",
            outcome="YES",
            planning_allowed=True,
            execution_mode_label="",
            reference_price=0.50,
            slippage_bps_hint=10,
        ),
    )

    assert invalid_context.plan is None
    assert invalid_context.trace.blocked_reason == PLAN_BLOCK_INVALID_MARKET_CONTEXT

    mismatch = builder.build_with_trace(
        intent_input=VALID_INTENT,
        market_context_input=ExecutionPlanMarketContextInput(
            market_id="MKT-OTHER",
            outcome="YES",
            planning_allowed=True,
            execution_mode_label="paper-prep-only",
        ),
    )
    assert mismatch.plan is None
    assert mismatch.trace.blocked_reason == PLAN_BLOCK_MARKET_CONTEXT_MISMATCH

    blocked_not_plannable = builder.build_with_trace(
        intent_input=VALID_INTENT,
        market_context_input=ExecutionPlanMarketContextInput(
            market_id="MKT-3-4",
            outcome="YES",
            planning_allowed=False,
            execution_mode_label="paper-prep-only",
        ),
    )
    assert blocked_not_plannable.plan is None
    assert blocked_not_plannable.trace.blocked_reason == PLAN_BLOCK_MARKET_NOT_PLANNABLE


def test_phase3_4_planning_metadata_is_deterministic() -> None:
    builder = ExecutionPlanBuilder()
    first = builder.build_with_trace(
        intent_input=VALID_INTENT,
        market_context_input=VALID_MARKET_CONTEXT,
    )
    second = builder.build_with_trace(
        intent_input=VALID_INTENT,
        market_context_input=VALID_MARKET_CONTEXT,
    )

    assert first.trace.planning_notes == second.trace.planning_notes
    assert first.trace.upstream_trace_refs == second.trace.upstream_trace_refs


def test_phase3_4_none_dict_wrong_object_inputs_do_not_crash() -> None:
    builder = ExecutionPlanBuilder()

    none_result = builder.build_with_trace(
        intent_input=VALID_INTENT,
        market_context_input=None,  # type: ignore[arg-type]
    )
    assert none_result.plan is None
    assert none_result.trace.blocked_reason == PLAN_BLOCK_INVALID_MARKET_CONTEXT_CONTRACT

    dict_result = builder.build_with_trace(
        intent_input={"market_id": "MKT-3-4"},  # type: ignore[arg-type]
        market_context_input=VALID_MARKET_CONTEXT,
    )
    assert dict_result.plan is None
    assert dict_result.trace.blocked_reason == PLAN_BLOCK_INVALID_INTENT_CONTRACT

    wrong_object_result = builder.build_with_trace(
        intent_input=object(),  # type: ignore[arg-type]
        market_context_input=VALID_MARKET_CONTEXT,
    )
    assert wrong_object_result.plan is None
    assert wrong_object_result.trace.blocked_reason == PLAN_BLOCK_INVALID_INTENT_CONTRACT
