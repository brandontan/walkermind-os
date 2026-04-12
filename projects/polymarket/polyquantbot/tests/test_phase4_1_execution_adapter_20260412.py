from __future__ import annotations

from dataclasses import fields, replace

from projects.polymarket.polyquantbot.platform.execution.execution_adapter import (
    ADAPTER_BLOCK_DECISION_NOT_READY,
    ADAPTER_BLOCK_INVALID_DECISION_CONTRACT,
    ADAPTER_BLOCK_INVALID_DECISION_INPUT,
    ADAPTER_BLOCK_NON_ACTIVATING_REQUIRED,
    ADAPTER_BLOCK_UPSTREAM_NOT_ALLOWED,
    ExecutionAdapter,
    ExecutionAdapterDecisionInput,
    ExecutionOrderSpec,
)
from projects.polymarket.polyquantbot.platform.execution.execution_decision import ExecutionDecision

VALID_DECISION = ExecutionDecision(
    allowed=True,
    blocked_reason=None,
    market_id="MKT-4-1",
    outcome="YES",
    side="YES",
    size=5.0,
    routing_mode="platform-gateway-shadow",
    execution_mode="paper-prep-only",
    ready_for_execution=True,
    non_activating=True,
)

VALID_DECISION_INPUT = ExecutionAdapterDecisionInput(
    decision=VALID_DECISION,
    source_trace_refs={"decision_trace_id": "DEC-4-1"},
)


def test_phase4_1_valid_activated_decision_produces_order_spec() -> None:
    adapter = ExecutionAdapter()

    result = adapter.build_order_with_trace(decision_input=VALID_DECISION_INPUT)

    assert result.order is not None
    assert result.trace.order_created is True
    assert result.trace.blocked_reason is None
    assert result.order.non_executing is True


def test_phase4_1_invalid_decision_contract_blocked_deterministically() -> None:
    adapter = ExecutionAdapter()

    result = adapter.build_order_with_trace(
        decision_input=ExecutionAdapterDecisionInput(
            decision=None,  # type: ignore[arg-type]
        )
    )

    assert result.order is None
    assert result.trace.order_created is False
    assert result.trace.blocked_reason == ADAPTER_BLOCK_INVALID_DECISION_CONTRACT


def test_phase4_1_invalid_top_level_input_blocked_deterministically() -> None:
    adapter = ExecutionAdapter()

    result = adapter.build_order_with_trace(
        decision_input=None,  # type: ignore[arg-type]
    )

    assert result.order is None
    assert result.trace.order_created is False
    assert result.trace.blocked_reason == ADAPTER_BLOCK_INVALID_DECISION_INPUT


def test_phase4_1_upstream_blocked_decision_propagates() -> None:
    adapter = ExecutionAdapter()
    blocked_decision = replace(VALID_DECISION, allowed=False, blocked_reason="risk_blocked")

    result = adapter.build_order_with_trace(
        decision_input=ExecutionAdapterDecisionInput(decision=blocked_decision)
    )

    assert result.order is None
    assert result.trace.blocked_reason == ADAPTER_BLOCK_UPSTREAM_NOT_ALLOWED


def test_phase4_1_ready_for_execution_false_blocked() -> None:
    adapter = ExecutionAdapter()

    result = adapter.build_order_with_trace(
        decision_input=ExecutionAdapterDecisionInput(
            decision=replace(VALID_DECISION, ready_for_execution=False)
        )
    )

    assert result.order is None
    assert result.trace.blocked_reason == ADAPTER_BLOCK_DECISION_NOT_READY


def test_phase4_1_non_activating_false_blocked() -> None:
    adapter = ExecutionAdapter()

    result = adapter.build_order_with_trace(
        decision_input=ExecutionAdapterDecisionInput(
            decision=replace(VALID_DECISION, non_activating=False)
        )
    )

    assert result.order is None
    assert result.trace.blocked_reason == ADAPTER_BLOCK_NON_ACTIVATING_REQUIRED


def test_phase4_1_deterministic_mapping_same_input_same_output() -> None:
    adapter = ExecutionAdapter()

    first = adapter.build_order_with_trace(decision_input=VALID_DECISION_INPUT)
    second = adapter.build_order_with_trace(decision_input=VALID_DECISION_INPUT)

    assert first == second


def test_phase4_1_mapping_correctness_side_order_type_symbol() -> None:
    adapter = ExecutionAdapter()

    result = adapter.build_order_with_trace(decision_input=VALID_DECISION_INPUT)

    assert result.order is not None
    assert result.order.external_side == "BUY"
    assert result.order.order_type == "LIMIT"
    assert result.order.external_order_type == "LIMIT"
    assert result.order.execution_mode == "LIMIT"
    assert result.order.external_symbol == "MKT-4-1::YES"


def test_phase4_1_no_execution_network_wallet_fields_introduced() -> None:
    field_names = {item.name for item in fields(ExecutionOrderSpec)}

    assert "wallet_address" not in field_names
    assert "signature" not in field_names
    assert "private_key" not in field_names
    assert "submit_order" not in field_names
    assert "network_client" not in field_names
    assert "capital_transfer" not in field_names


def test_phase4_1_none_dict_wrong_object_inputs_do_not_crash() -> None:
    adapter = ExecutionAdapter()

    none_input_result = adapter.build_order_with_trace(
        decision_input=None,  # type: ignore[arg-type]
    )
    assert none_input_result.trace.blocked_reason == ADAPTER_BLOCK_INVALID_DECISION_INPUT

    dict_input_result = adapter.build_order_with_trace(
        decision_input={"decision": VALID_DECISION},  # type: ignore[arg-type]
    )
    assert dict_input_result.trace.blocked_reason == ADAPTER_BLOCK_INVALID_DECISION_INPUT

    wrong_inner_result = adapter.build_order_with_trace(
        decision_input=ExecutionAdapterDecisionInput(
            decision=object(),  # type: ignore[arg-type]
        )
    )
    assert wrong_inner_result.trace.blocked_reason == ADAPTER_BLOCK_INVALID_DECISION_CONTRACT
