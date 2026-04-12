from __future__ import annotations

from dataclasses import fields, replace

from projects.polymarket.polyquantbot.platform.execution.execution_decision import ExecutionDecision
from projects.polymarket.polyquantbot.platform.execution.execution_engine import (
    ENGINE_BLOCK_DECISION_NOT_READY,
    ENGINE_BLOCK_INVALID_DECISION_CONTRACT,
    ENGINE_BLOCK_INVALID_DECISION_INPUT,
    ENGINE_BLOCK_NON_ACTIVATING_REQUIRED,
    ENGINE_BLOCK_UPSTREAM_DECISION_BLOCKED,
    EXECUTION_STATUS_BLOCKED,
    EXECUTION_STATUS_SIMULATED_ACCEPTED,
    ExecutionEngine,
    ExecutionEngineDecisionInput,
)

VALID_DECISION = ExecutionDecision(
    allowed=True,
    blocked_reason=None,
    market_id="MKT-3-7",
    outcome="YES",
    side="BUY",
    size=5.0,
    routing_mode="platform-gateway-shadow",
    execution_mode="paper-prep-only",
    ready_for_execution=True,
    non_activating=True,
)

VALID_DECISION_INPUT = ExecutionEngineDecisionInput(
    decision=VALID_DECISION,
    source_trace_refs={"decision_trace_id": "DEC-3-7"},
)


def test_phase3_7_valid_decision_returns_simulated_accepted_result() -> None:
    engine = ExecutionEngine()

    result = engine.execute_with_trace(decision_input=VALID_DECISION_INPUT)

    assert result.result is not None
    assert result.result.status == EXECUTION_STATUS_SIMULATED_ACCEPTED
    assert result.result.blocked_reason is None
    assert result.result.accepted is True
    assert result.result.simulated is True
    assert result.result.non_activating is True


def test_phase3_7_invalid_decision_contract_blocked_deterministically() -> None:
    engine = ExecutionEngine()

    result = engine.execute_with_trace(
        decision_input=ExecutionEngineDecisionInput(decision=None),  # type: ignore[arg-type]
    )

    assert result.result is not None
    assert result.result.status == EXECUTION_STATUS_BLOCKED
    assert result.result.blocked_reason == ENGINE_BLOCK_INVALID_DECISION_CONTRACT


def test_phase3_7_invalid_top_level_engine_input_blocked_deterministically() -> None:
    engine = ExecutionEngine()

    result = engine.execute_with_trace(decision_input=None)  # type: ignore[arg-type]

    assert result.result is not None
    assert result.result.status == EXECUTION_STATUS_BLOCKED
    assert result.result.blocked_reason == ENGINE_BLOCK_INVALID_DECISION_INPUT


def test_phase3_7_upstream_blocked_decision_propagates_deterministically() -> None:
    engine = ExecutionEngine()
    blocked_decision = replace(VALID_DECISION, allowed=False, blocked_reason="upstream_block")

    result = engine.execute_with_trace(
        decision_input=ExecutionEngineDecisionInput(decision=blocked_decision),
    )

    assert result.result is not None
    assert result.result.status == EXECUTION_STATUS_BLOCKED
    assert result.result.blocked_reason == ENGINE_BLOCK_UPSTREAM_DECISION_BLOCKED


def test_phase3_7_not_ready_decision_is_blocked_deterministically() -> None:
    engine = ExecutionEngine()
    not_ready_decision = replace(VALID_DECISION, ready_for_execution=False)

    result = engine.execute_with_trace(
        decision_input=ExecutionEngineDecisionInput(decision=not_ready_decision),
    )

    assert result.result is not None
    assert result.result.status == EXECUTION_STATUS_BLOCKED
    assert result.result.blocked_reason == ENGINE_BLOCK_DECISION_NOT_READY


def test_phase3_7_non_activating_false_is_blocked_deterministically() -> None:
    engine = ExecutionEngine()
    activating_decision = replace(VALID_DECISION, non_activating=False)

    result = engine.execute_with_trace(
        decision_input=ExecutionEngineDecisionInput(decision=activating_decision),
    )

    assert result.result is not None
    assert result.result.status == EXECUTION_STATUS_BLOCKED
    assert result.result.blocked_reason == ENGINE_BLOCK_NON_ACTIVATING_REQUIRED


def test_phase3_7_deterministic_equality_for_same_valid_input() -> None:
    engine = ExecutionEngine()

    first = engine.execute_with_trace(decision_input=VALID_DECISION_INPUT)
    second = engine.execute_with_trace(decision_input=VALID_DECISION_INPUT)

    assert first == second


def test_phase3_7_deterministic_execution_id_for_same_valid_input() -> None:
    engine = ExecutionEngine()

    first = engine.execute(decision_input=VALID_DECISION_INPUT)
    second = engine.execute(decision_input=VALID_DECISION_INPUT)

    assert first is not None
    assert second is not None
    assert first.execution_id == second.execution_id


def test_phase3_7_no_wallet_signing_network_or_order_submission_fields_introduced() -> None:
    field_names = {item.name for item in fields(type(engine_result_for_fields_check()))}

    assert "wallet_address" not in field_names
    assert "private_key" not in field_names
    assert "signature" not in field_names
    assert "network_client" not in field_names
    assert "exchange_client" not in field_names
    assert "order_submission_hook" not in field_names
    assert "capital_allocation" not in field_names


def engine_result_for_fields_check():
    engine = ExecutionEngine()
    result = engine.execute(decision_input=VALID_DECISION_INPUT)
    assert result is not None
    return result


def test_phase3_7_none_dict_wrong_object_inputs_do_not_crash() -> None:
    engine = ExecutionEngine()

    none_result = engine.execute_with_trace(decision_input=None)  # type: ignore[arg-type]
    assert none_result.result is not None
    assert none_result.result.blocked_reason == ENGINE_BLOCK_INVALID_DECISION_INPUT

    dict_result = engine.execute_with_trace(decision_input={"decision": "bad"})  # type: ignore[arg-type]
    assert dict_result.result is not None
    assert dict_result.result.blocked_reason == ENGINE_BLOCK_INVALID_DECISION_INPUT

    wrong_object_result = engine.execute_with_trace(decision_input=object())  # type: ignore[arg-type]
    assert wrong_object_result.result is not None
    assert wrong_object_result.result.blocked_reason == ENGINE_BLOCK_INVALID_DECISION_INPUT
