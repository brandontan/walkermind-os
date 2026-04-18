from __future__ import annotations

import json

from projects.polymarket.polyquantbot.core.execution_memory_foundation import (
    EXECUTION_MEMORY_BLOCK_INVALID_CONTRACT,
    EXECUTION_MEMORY_CLEAR_CLEARED,
    EXECUTION_MEMORY_CLEAR_NOT_FOUND,
    EXECUTION_MEMORY_LOAD_BLOCKED,
    EXECUTION_MEMORY_LOAD_LOADED,
    EXECUTION_MEMORY_LOAD_NOT_FOUND,
    EXECUTION_MEMORY_STORE_STORED,
    ExecutionMemoryContract,
    ExecutionMemoryPersistenceBoundary,
    ExecutionMemoryReadContract,
    ExecutionMemoryState,
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


def _store_contract(tmp_path, **kwargs):  # type: ignore[no-untyped-def]
    defaults: dict = {
        "owner_ref": "owner-1",
        "storage_dir": str(tmp_path),
        "state": _state(),
    }
    defaults.update(kwargs)
    return ExecutionMemoryContract(**defaults)


def _read_contract(tmp_path, **kwargs):  # type: ignore[no-untyped-def]
    defaults: dict = {
        "owner_ref": "owner-1",
        "storage_dir": str(tmp_path),
    }
    defaults.update(kwargs)
    return ExecutionMemoryReadContract(**defaults)


def test_phase7_6_store_then_load_is_deterministic(tmp_path) -> None:
    boundary = ExecutionMemoryPersistenceBoundary()
    contract = _store_contract(tmp_path)

    store = boundary.store(contract)
    load = boundary.load(_read_contract(tmp_path))

    assert store.success is True
    assert store.result_category == EXECUTION_MEMORY_STORE_STORED
    assert store.memory_state == contract.state
    assert load.success is True
    assert load.result_category == EXECUTION_MEMORY_LOAD_LOADED
    assert load.memory_found is True
    assert load.memory_state == contract.state


def test_phase7_6_load_not_found_is_deterministic(tmp_path) -> None:
    boundary = ExecutionMemoryPersistenceBoundary()
    result = boundary.load(_read_contract(tmp_path))

    assert result.success is True
    assert result.result_category == EXECUTION_MEMORY_LOAD_NOT_FOUND
    assert result.memory_found is False
    assert result.memory_state is None


def test_phase7_6_clear_not_found_is_deterministic(tmp_path) -> None:
    boundary = ExecutionMemoryPersistenceBoundary()
    result = boundary.clear(_read_contract(tmp_path))

    assert result.success is True
    assert result.result_category == EXECUTION_MEMORY_CLEAR_NOT_FOUND
    assert result.memory_cleared is False


def test_phase7_6_clear_removes_stored_state(tmp_path) -> None:
    boundary = ExecutionMemoryPersistenceBoundary()
    boundary.store(_store_contract(tmp_path))

    clear_result = boundary.clear(_read_contract(tmp_path))
    load_after = boundary.load(_read_contract(tmp_path))

    assert clear_result.success is True
    assert clear_result.result_category == EXECUTION_MEMORY_CLEAR_CLEARED
    assert clear_result.memory_cleared is True
    assert load_after.result_category == EXECUTION_MEMORY_LOAD_NOT_FOUND


def test_phase7_6_blocks_invalid_store_contract(tmp_path) -> None:
    boundary = ExecutionMemoryPersistenceBoundary()
    result = boundary.store(_store_contract(tmp_path, owner_ref="", state=_state()))

    assert result.success is False
    assert result.blocked_reason == EXECUTION_MEMORY_BLOCK_INVALID_CONTRACT
    assert result.memory_state is None
    assert result.notes == {"contract_error": "owner_ref_required"}


def test_phase7_6_blocks_invalid_read_contract(tmp_path) -> None:
    boundary = ExecutionMemoryPersistenceBoundary()
    result = boundary.load(_read_contract(tmp_path, storage_dir=".."))

    assert result.success is False
    assert result.result_category == EXECUTION_MEMORY_LOAD_BLOCKED
    assert result.blocked_reason == EXECUTION_MEMORY_BLOCK_INVALID_CONTRACT
    assert result.notes == {"contract_error": "storage_dir_invalid"}


def test_phase7_6_load_blocks_on_invalid_persisted_payload(tmp_path) -> None:
    boundary = ExecutionMemoryPersistenceBoundary()
    contract = _store_contract(tmp_path)
    boundary.store(contract)

    bad_file = tmp_path / "owner-1" / "phase7_execution_memory.json"
    with bad_file.open("w", encoding="utf-8") as handle:
        json.dump({"owner_ref": "owner-1", "state": {"bad_key": "x"}}, handle)

    result = boundary.load(_read_contract(tmp_path))

    assert result.success is False
    assert result.result_category == EXECUTION_MEMORY_LOAD_BLOCKED
    assert result.blocked_reason == EXECUTION_MEMORY_BLOCK_INVALID_CONTRACT
    assert result.notes == {"contract_error": "state_keys_invalid"}


def test_phase7_6_store_supports_none_operator_decision(tmp_path) -> None:
    boundary = ExecutionMemoryPersistenceBoundary()
    state = _state(last_operator_control_decision=None)
    contract = _store_contract(tmp_path, state=state)

    store = boundary.store(contract)
    load = boundary.load(_read_contract(tmp_path))

    assert store.success is True
    assert load.success is True
    assert load.memory_state is not None
    assert load.memory_state.last_operator_control_decision is None
