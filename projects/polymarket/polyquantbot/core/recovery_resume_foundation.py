"""Phase 7.7 -- recovery / resume foundation.

Narrow deterministic recovery decision boundary over Phase 7.6 execution memory only.

This slice is FOUNDATION only:
  - no distributed recovery
  - no daemon orchestration
  - no replay engine
  - no database rollout
  - no Redis
  - no async workers
  - no crash supervisor
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from projects.polymarket.polyquantbot.core.execution_memory_foundation import (
    EXECUTION_MEMORY_BLOCK_INVALID_CONTRACT,
    EXECUTION_MEMORY_LOAD_BLOCKED,
    EXECUTION_MEMORY_LOAD_LOADED,
    EXECUTION_MEMORY_LOAD_NOT_FOUND,
    ExecutionMemoryLoadResult,
    ExecutionMemoryPersistenceBoundary,
    ExecutionMemoryReadContract,
)

RECOVERY_DECISION_RESUME = "resume"
RECOVERY_DECISION_RESTART_FRESH = "restart_fresh"
RECOVERY_DECISION_BLOCKED = "blocked"
RECOVERY_DECISION_NO_MEMORY = "no_memory"

RECOVERY_REASON_MEMORY_VALID_INTERRUPTED = "memory_valid_interrupted"
RECOVERY_REASON_MEMORY_VALID_CLOSED = "memory_valid_closed"
RECOVERY_REASON_MEMORY_NOT_FOUND = "memory_not_found"
RECOVERY_REASON_MEMORY_INVALID_CONTRACT = "memory_invalid_contract"
RECOVERY_REASON_MEMORY_RUNTIME_ERROR = "memory_runtime_error"
RECOVERY_REASON_PREVIOUS_BLOCKED = "previous_blocked"
RECOVERY_REASON_OPERATOR_HOLD = "operator_hold"


@dataclass(frozen=True)
class RecoveryResumeContract:
    """Deterministic recovery contract using only Phase 7.6 memory boundary."""

    owner_ref: str
    storage_dir: str


@dataclass(frozen=True)
class RecoveryResumeDecision:
    """Deterministic recovery decision categories and explicit reason/notes."""

    success: bool
    decision_category: str
    reason: str
    notes: dict[str, Any] | None = None


class RecoveryResumeFoundationBoundary:
    """Deterministic recovery decision boundary over execution memory state."""

    def decide(self, contract: RecoveryResumeContract) -> RecoveryResumeDecision:
        if not isinstance(contract.owner_ref, str) or not contract.owner_ref.strip():
            return RecoveryResumeDecision(
                success=False,
                decision_category=RECOVERY_DECISION_BLOCKED,
                reason=RECOVERY_REASON_MEMORY_INVALID_CONTRACT,
                notes={"contract_error": "owner_ref_required"},
            )
        if not isinstance(contract.storage_dir, str) or not contract.storage_dir.strip():
            return RecoveryResumeDecision(
                success=False,
                decision_category=RECOVERY_DECISION_BLOCKED,
                reason=RECOVERY_REASON_MEMORY_INVALID_CONTRACT,
                notes={"contract_error": "storage_dir_required"},
            )

        read_contract = ExecutionMemoryReadContract(
            owner_ref=contract.owner_ref,
            storage_dir=contract.storage_dir,
        )
        load_result = ExecutionMemoryPersistenceBoundary().load(read_contract)
        return _decide_from_load_result(load_result)


def _decide_from_load_result(load_result: ExecutionMemoryLoadResult) -> RecoveryResumeDecision:
    if load_result.result_category == EXECUTION_MEMORY_LOAD_NOT_FOUND:
        return RecoveryResumeDecision(
            success=True,
            decision_category=RECOVERY_DECISION_NO_MEMORY,
            reason=RECOVERY_REASON_MEMORY_NOT_FOUND,
            notes=load_result.notes,
        )

    if load_result.result_category == EXECUTION_MEMORY_LOAD_BLOCKED:
        if load_result.blocked_reason == EXECUTION_MEMORY_BLOCK_INVALID_CONTRACT:
            return RecoveryResumeDecision(
                success=False,
                decision_category=RECOVERY_DECISION_BLOCKED,
                reason=RECOVERY_REASON_MEMORY_INVALID_CONTRACT,
                notes=load_result.notes,
            )

        return RecoveryResumeDecision(
            success=False,
            decision_category=RECOVERY_DECISION_BLOCKED,
            reason=RECOVERY_REASON_MEMORY_RUNTIME_ERROR,
            notes=load_result.notes,
        )

    if load_result.result_category != EXECUTION_MEMORY_LOAD_LOADED or load_result.memory_state is None:
        return RecoveryResumeDecision(
            success=False,
            decision_category=RECOVERY_DECISION_BLOCKED,
            reason=RECOVERY_REASON_MEMORY_RUNTIME_ERROR,
            notes={"error": "unexpected_memory_load_result", "load_result": load_result.result_category},
        )

    memory = load_result.memory_state

    if (
        memory.last_run_result == "stopped_blocked"
        or memory.last_scheduler_decision == "blocked"
        or memory.last_loop_outcome == "stopped_blocked"
        or memory.last_operator_control_decision == "force_block"
    ):
        return RecoveryResumeDecision(
            success=False,
            decision_category=RECOVERY_DECISION_BLOCKED,
            reason=RECOVERY_REASON_PREVIOUS_BLOCKED,
            notes={
                "last_run_result": memory.last_run_result,
                "last_scheduler_decision": memory.last_scheduler_decision,
                "last_loop_outcome": memory.last_loop_outcome,
                "last_operator_control_decision": memory.last_operator_control_decision,
            },
        )

    if memory.last_operator_control_decision == "hold":
        return RecoveryResumeDecision(
            success=True,
            decision_category=RECOVERY_DECISION_RESTART_FRESH,
            reason=RECOVERY_REASON_OPERATOR_HOLD,
            notes={
                "last_run_result": memory.last_run_result,
                "last_scheduler_decision": memory.last_scheduler_decision,
                "last_loop_outcome": memory.last_loop_outcome,
                "last_operator_control_decision": memory.last_operator_control_decision,
            },
        )

    if memory.last_loop_outcome in {"completed", "stopped_hold", "exhausted"}:
        return RecoveryResumeDecision(
            success=True,
            decision_category=RECOVERY_DECISION_RESTART_FRESH,
            reason=RECOVERY_REASON_MEMORY_VALID_CLOSED,
            notes={
                "last_run_result": memory.last_run_result,
                "last_scheduler_decision": memory.last_scheduler_decision,
                "last_loop_outcome": memory.last_loop_outcome,
            },
        )

    return RecoveryResumeDecision(
        success=True,
        decision_category=RECOVERY_DECISION_RESUME,
        reason=RECOVERY_REASON_MEMORY_VALID_INTERRUPTED,
        notes={
            "last_run_result": memory.last_run_result,
            "last_scheduler_decision": memory.last_scheduler_decision,
            "last_loop_outcome": memory.last_loop_outcome,
        },
    )
