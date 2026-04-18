from __future__ import annotations

import json

from projects.polymarket.polyquantbot.core.execution_memory_foundation import (
    ExecutionMemoryContract,
    ExecutionMemoryPersistenceBoundary,
    ExecutionMemoryState,
)
from projects.polymarket.polyquantbot.core.recovery_resume_foundation import (
    RECOVERY_DECISION_BLOCKED,
    RECOVERY_DECISION_NO_MEMORY,
    RECOVERY_DECISION_RESUME,
    RECOVERY_DECISION_RESTART_FRESH,
    RECOVERY_REASON_MEMORY_INVALID_CONTRACT,
    RECOVERY_REASON_MEMORY_NOT_FOUND,
    RECOVERY_REASON_MEMORY_VALID_INTERRUPTED,
    RECOVERY_REASON_OPERATOR_HOLD,
    RECOVERY_REASON_PREVIOUS_BLOCKED,
    RecoveryResumeContract,
    RecoveryResumeFoundationBoundary,
)


def _state(**kwargs) -> ExecutionMemoryState:  # type: ignore[no-untyped-def]
    defaults: dict = {
        "last_run_result": "completed",
        "last_scheduler_decision": "triggered",
        "last_loop_outcome": "completed",
        "last_operator_control_decision": "allow",
        "last_observability_trace_summary": "visible:trace-001",
    }
    defaults.update(kwargs)
    return ExecutionMemoryState(**defaults)


def _store_memory(tmp_path, **state_kwargs):  # type: ignore[no-untyped-def]
    contract = ExecutionMemoryContract(
        owner_ref="owner-1",
        storage_dir=str(tmp_path),
        state=_state(**state_kwargs),
    )
    result = ExecutionMemoryPersistenceBoundary().store(contract)
    assert result.success is True


def test_phase7_7_returns_no_memory_when_memory_is_missing(tmp_path) -> None:
    decision = RecoveryResumeFoundationBoundary().decide(
        RecoveryResumeContract(owner_ref="owner-1", storage_dir=str(tmp_path))
    )

    assert decision.success is True
    assert decision.decision_category == RECOVERY_DECISION_NO_MEMORY
    assert decision.reason == RECOVERY_REASON_MEMORY_NOT_FOUND


def test_phase7_7_returns_restart_fresh_when_memory_is_closed(tmp_path) -> None:
    _store_memory(tmp_path, last_run_result="completed", last_scheduler_decision="triggered", last_loop_outcome="completed")

    decision = RecoveryResumeFoundationBoundary().decide(
        RecoveryResumeContract(owner_ref="owner-1", storage_dir=str(tmp_path))
    )

    assert decision.success is True
    assert decision.decision_category == RECOVERY_DECISION_RESTART_FRESH


def test_phase7_7_returns_resume_when_memory_shows_interrupted_flow(tmp_path) -> None:
    _store_memory(tmp_path, last_run_result="triggered", last_scheduler_decision="triggered", last_loop_outcome="in_progress")

    decision = RecoveryResumeFoundationBoundary().decide(
        RecoveryResumeContract(owner_ref="owner-1", storage_dir=str(tmp_path))
    )

    assert decision.success is True
    assert decision.decision_category == RECOVERY_DECISION_RESUME
    assert decision.reason == RECOVERY_REASON_MEMORY_VALID_INTERRUPTED


def test_phase7_7_returns_blocked_when_memory_shows_blocked_condition(tmp_path) -> None:
    _store_memory(tmp_path, last_run_result="stopped_blocked", last_scheduler_decision="blocked", last_loop_outcome="stopped_blocked")

    decision = RecoveryResumeFoundationBoundary().decide(
        RecoveryResumeContract(owner_ref="owner-1", storage_dir=str(tmp_path))
    )

    assert decision.success is False
    assert decision.decision_category == RECOVERY_DECISION_BLOCKED
    assert decision.reason == RECOVERY_REASON_PREVIOUS_BLOCKED


def test_phase7_7_returns_blocked_when_operator_memory_is_force_block(tmp_path) -> None:
    _store_memory(
        tmp_path,
        last_run_result="triggered",
        last_scheduler_decision="triggered",
        last_loop_outcome="in_progress",
        last_operator_control_decision="force_block",
    )

    decision = RecoveryResumeFoundationBoundary().decide(
        RecoveryResumeContract(owner_ref="owner-1", storage_dir=str(tmp_path))
    )

    assert decision.success is False
    assert decision.decision_category == RECOVERY_DECISION_BLOCKED
    assert decision.reason == RECOVERY_REASON_PREVIOUS_BLOCKED


def test_phase7_7_returns_restart_fresh_when_memory_is_exhausted(tmp_path) -> None:
    _store_memory(
        tmp_path,
        last_run_result="exhausted",
        last_scheduler_decision="triggered",
        last_loop_outcome="exhausted",
    )

    decision = RecoveryResumeFoundationBoundary().decide(
        RecoveryResumeContract(owner_ref="owner-1", storage_dir=str(tmp_path))
    )

    assert decision.success is True
    assert decision.decision_category == RECOVERY_DECISION_RESTART_FRESH


def test_phase7_7_returns_non_resume_when_operator_memory_is_hold(tmp_path) -> None:
    _store_memory(
        tmp_path,
        last_run_result="triggered",
        last_scheduler_decision="triggered",
        last_loop_outcome="in_progress",
        last_operator_control_decision="hold",
    )

    decision = RecoveryResumeFoundationBoundary().decide(
        RecoveryResumeContract(owner_ref="owner-1", storage_dir=str(tmp_path))
    )

    assert decision.success is True
    assert decision.decision_category == RECOVERY_DECISION_RESTART_FRESH
    assert decision.reason == RECOVERY_REASON_OPERATOR_HOLD


def test_phase7_7_returns_blocked_when_persisted_memory_contract_is_invalid(tmp_path) -> None:
    _store_memory(tmp_path)

    bad_file = tmp_path / "owner-1" / "phase7_execution_memory.json"
    with bad_file.open("w", encoding="utf-8") as handle:
        json.dump({"owner_ref": "owner-1", "state": {"invalid": "payload"}}, handle)

    decision = RecoveryResumeFoundationBoundary().decide(
        RecoveryResumeContract(owner_ref="owner-1", storage_dir=str(tmp_path))
    )

    assert decision.success is False
    assert decision.decision_category == RECOVERY_DECISION_BLOCKED
    assert decision.reason == RECOVERY_REASON_MEMORY_INVALID_CONTRACT


def test_phase7_7_blocks_invalid_recovery_contract(tmp_path) -> None:
    decision = RecoveryResumeFoundationBoundary().decide(
        RecoveryResumeContract(owner_ref="", storage_dir=str(tmp_path))
    )

    assert decision.success is False
    assert decision.decision_category == RECOVERY_DECISION_BLOCKED
    assert decision.reason == RECOVERY_REASON_MEMORY_INVALID_CONTRACT
    assert decision.notes == {"contract_error": "owner_ref_required"}
