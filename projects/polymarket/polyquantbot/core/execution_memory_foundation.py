"""Phase 7.6 -- state persistence / execution memory foundation.

Deterministic local-file persistence boundary for minimal last-run runtime context.
This slice is FOUNDATION only:
  - no database rollout
  - no Redis
  - no distributed state
  - no async persistence workers
  - no replay or recovery orchestration
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

EXECUTION_MEMORY_STORE_STORED = "stored"
EXECUTION_MEMORY_STORE_BLOCKED = "blocked"
EXECUTION_MEMORY_LOAD_LOADED = "loaded"
EXECUTION_MEMORY_LOAD_NOT_FOUND = "not_found"
EXECUTION_MEMORY_LOAD_BLOCKED = "blocked"
EXECUTION_MEMORY_CLEAR_CLEARED = "cleared"
EXECUTION_MEMORY_CLEAR_NOT_FOUND = "not_found"
EXECUTION_MEMORY_CLEAR_BLOCKED = "blocked"
EXECUTION_MEMORY_BLOCK_INVALID_CONTRACT = "invalid_contract"
EXECUTION_MEMORY_BLOCK_RUNTIME_ERROR = "runtime_error"

_MEMORY_FILE_NAME = "phase7_execution_memory.json"


@dataclass(frozen=True)
class ExecutionMemoryState:
    """Minimal deterministic execution memory snapshot for phase 7 runtime surfaces."""

    last_run_result: str
    last_scheduler_decision: str
    last_loop_outcome: str
    last_operator_control_decision: str | None
    last_observability_trace_summary: str


@dataclass(frozen=True)
class ExecutionMemoryContract:
    """Persistence contract with explicit owner and deterministic storage path."""

    owner_ref: str
    storage_dir: str
    state: ExecutionMemoryState


@dataclass(frozen=True)
class ExecutionMemoryReadContract:
    """Read / clear contract without requiring a state payload."""

    owner_ref: str
    storage_dir: str


@dataclass(frozen=True)
class ExecutionMemoryStoreResult:
    success: bool
    result_category: str
    blocked_reason: str | None
    memory_state: ExecutionMemoryState | None
    notes: dict[str, Any] | None = None


@dataclass(frozen=True)
class ExecutionMemoryLoadResult:
    success: bool
    result_category: str
    blocked_reason: str | None
    memory_found: bool
    memory_state: ExecutionMemoryState | None
    notes: dict[str, Any] | None = None


@dataclass(frozen=True)
class ExecutionMemoryClearResult:
    success: bool
    result_category: str
    blocked_reason: str | None
    memory_cleared: bool
    notes: dict[str, Any] | None = None


class ExecutionMemoryPersistenceBoundary:
    """Deterministic local-file execution memory boundary (load/store/clear)."""

    def store(self, contract: ExecutionMemoryContract) -> ExecutionMemoryStoreResult:
        contract_error = _validate_store_contract(contract)
        if contract_error is not None:
            return ExecutionMemoryStoreResult(
                success=False,
                result_category=EXECUTION_MEMORY_STORE_BLOCKED,
                blocked_reason=EXECUTION_MEMORY_BLOCK_INVALID_CONTRACT,
                memory_state=None,
                notes={"contract_error": contract_error},
            )

        try:
            storage_file = _resolve_storage_file(contract.owner_ref, contract.storage_dir)
            storage_file.parent.mkdir(parents=True, exist_ok=True)
            payload = _serialize_payload(contract.owner_ref, contract.state)
            with storage_file.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            return ExecutionMemoryStoreResult(
                success=True,
                result_category=EXECUTION_MEMORY_STORE_STORED,
                blocked_reason=None,
                memory_state=contract.state,
                notes={"storage_file": str(storage_file)},
            )
        except Exception as exc:
            return ExecutionMemoryStoreResult(
                success=False,
                result_category=EXECUTION_MEMORY_STORE_BLOCKED,
                blocked_reason=EXECUTION_MEMORY_BLOCK_RUNTIME_ERROR,
                memory_state=None,
                notes={"error_type": type(exc).__name__},
            )

    def load(self, contract: ExecutionMemoryReadContract) -> ExecutionMemoryLoadResult:
        contract_error = _validate_read_contract(contract)
        if contract_error is not None:
            return ExecutionMemoryLoadResult(
                success=False,
                result_category=EXECUTION_MEMORY_LOAD_BLOCKED,
                blocked_reason=EXECUTION_MEMORY_BLOCK_INVALID_CONTRACT,
                memory_found=False,
                memory_state=None,
                notes={"contract_error": contract_error},
            )

        storage_file = _resolve_storage_file(contract.owner_ref, contract.storage_dir)
        if not storage_file.exists():
            return ExecutionMemoryLoadResult(
                success=True,
                result_category=EXECUTION_MEMORY_LOAD_NOT_FOUND,
                blocked_reason=None,
                memory_found=False,
                memory_state=None,
                notes={"storage_file": str(storage_file)},
            )

        try:
            with storage_file.open("r", encoding="utf-8") as handle:
                raw_payload = json.load(handle)
            parsed = _parse_payload(
                owner_ref=contract.owner_ref,
                payload=raw_payload,
            )
            if isinstance(parsed, str):
                return ExecutionMemoryLoadResult(
                    success=False,
                    result_category=EXECUTION_MEMORY_LOAD_BLOCKED,
                    blocked_reason=EXECUTION_MEMORY_BLOCK_INVALID_CONTRACT,
                    memory_found=False,
                    memory_state=None,
                    notes={"contract_error": parsed},
                )

            return ExecutionMemoryLoadResult(
                success=True,
                result_category=EXECUTION_MEMORY_LOAD_LOADED,
                blocked_reason=None,
                memory_found=True,
                memory_state=parsed,
                notes={"storage_file": str(storage_file)},
            )
        except Exception as exc:
            return ExecutionMemoryLoadResult(
                success=False,
                result_category=EXECUTION_MEMORY_LOAD_BLOCKED,
                blocked_reason=EXECUTION_MEMORY_BLOCK_RUNTIME_ERROR,
                memory_found=False,
                memory_state=None,
                notes={"error_type": type(exc).__name__},
            )

    def clear(self, contract: ExecutionMemoryReadContract) -> ExecutionMemoryClearResult:
        contract_error = _validate_read_contract(contract)
        if contract_error is not None:
            return ExecutionMemoryClearResult(
                success=False,
                result_category=EXECUTION_MEMORY_CLEAR_BLOCKED,
                blocked_reason=EXECUTION_MEMORY_BLOCK_INVALID_CONTRACT,
                memory_cleared=False,
                notes={"contract_error": contract_error},
            )

        storage_file = _resolve_storage_file(contract.owner_ref, contract.storage_dir)
        if not storage_file.exists():
            return ExecutionMemoryClearResult(
                success=True,
                result_category=EXECUTION_MEMORY_CLEAR_NOT_FOUND,
                blocked_reason=None,
                memory_cleared=False,
                notes={"storage_file": str(storage_file)},
            )

        try:
            storage_file.unlink()
            return ExecutionMemoryClearResult(
                success=True,
                result_category=EXECUTION_MEMORY_CLEAR_CLEARED,
                blocked_reason=None,
                memory_cleared=True,
                notes={"storage_file": str(storage_file)},
            )
        except Exception as exc:
            return ExecutionMemoryClearResult(
                success=False,
                result_category=EXECUTION_MEMORY_CLEAR_BLOCKED,
                blocked_reason=EXECUTION_MEMORY_BLOCK_RUNTIME_ERROR,
                memory_cleared=False,
                notes={"error_type": type(exc).__name__},
            )


def _resolve_storage_file(owner_ref: str, storage_dir: str) -> Path:
    return Path(storage_dir) / owner_ref / _MEMORY_FILE_NAME


def _serialize_payload(owner_ref: str, state: ExecutionMemoryState) -> dict[str, Any]:
    return {
        "owner_ref": owner_ref,
        "state": asdict(state),
    }


def _parse_payload(owner_ref: str, payload: Any) -> ExecutionMemoryState | str:
    if not isinstance(payload, dict):
        return "payload_must_be_dict"
    if payload.get("owner_ref") != owner_ref:
        return "owner_ref_mismatch"
    state = payload.get("state")
    if not isinstance(state, dict):
        return "state_must_be_dict"

    required_keys = {
        "last_run_result",
        "last_scheduler_decision",
        "last_loop_outcome",
        "last_operator_control_decision",
        "last_observability_trace_summary",
    }
    if set(state.keys()) != required_keys:
        return "state_keys_invalid"

    string_fields = (
        "last_run_result",
        "last_scheduler_decision",
        "last_loop_outcome",
        "last_observability_trace_summary",
    )
    for field_name in string_fields:
        value = state.get(field_name)
        if not isinstance(value, str) or not value.strip():
            return f"{field_name}_required"

    operator_decision = state.get("last_operator_control_decision")
    if operator_decision is not None and (
        not isinstance(operator_decision, str) or not operator_decision.strip()
    ):
        return "last_operator_control_decision_invalid"

    return ExecutionMemoryState(
        last_run_result=state["last_run_result"],
        last_scheduler_decision=state["last_scheduler_decision"],
        last_loop_outcome=state["last_loop_outcome"],
        last_operator_control_decision=operator_decision,
        last_observability_trace_summary=state["last_observability_trace_summary"],
    )


def _validate_store_contract(contract: ExecutionMemoryContract) -> str | None:
    read_error = _validate_read_contract(
        ExecutionMemoryReadContract(
            owner_ref=contract.owner_ref,
            storage_dir=contract.storage_dir,
        )
    )
    if read_error is not None:
        return read_error

    state = contract.state
    if not isinstance(state, ExecutionMemoryState):
        return "state_required"
    if not state.last_run_result.strip():
        return "last_run_result_required"
    if not state.last_scheduler_decision.strip():
        return "last_scheduler_decision_required"
    if not state.last_loop_outcome.strip():
        return "last_loop_outcome_required"
    if not state.last_observability_trace_summary.strip():
        return "last_observability_trace_summary_required"
    if state.last_operator_control_decision is not None and not state.last_operator_control_decision.strip():
        return "last_operator_control_decision_invalid"
    return None


def _validate_read_contract(contract: ExecutionMemoryReadContract) -> str | None:
    if not isinstance(contract.owner_ref, str) or not contract.owner_ref.strip():
        return "owner_ref_required"
    if not isinstance(contract.storage_dir, str) or not contract.storage_dir.strip():
        return "storage_dir_required"

    normalized = os.path.normpath(contract.storage_dir)
    if normalized in {"", ".", ".."}:
        return "storage_dir_invalid"
    if normalized.startswith(".."):
        return "storage_dir_invalid"
    return None
