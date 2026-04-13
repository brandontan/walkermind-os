from __future__ import annotations

from pathlib import Path

from projects.polymarket.polyquantbot.platform.safety.execution_ledger import (
    ExecutionLedger,
    LedgerEntry,
    LedgerRecordInput,
)
from projects.polymarket.polyquantbot.platform.safety.persistent_ledger import (
    PERSISTENT_LEDGER_BLOCK_HASH_MISMATCH,
    PERSISTENT_LEDGER_BLOCK_INVALID_CONFIG,
    PERSISTENT_LEDGER_BLOCK_INVALID_LEDGER_ENTRY,
    PERSISTENT_LEDGER_BLOCK_MALFORMED_RECORD,
    PERSISTENT_LEDGER_BLOCK_MISSING_STORAGE_PATH,
    AuditTrailQueryInput,
    PersistentExecutionLedger,
    PersistentLedgerConfig,
)


def _sample_entry(
    *,
    execution_id: str | None = "exec-001",
    stage: str = "transport",
    status: str = "accepted",
    timestamp_ref: str = "2026-04-13T10:00:00Z",
    payload: dict[str, object] | None = None,
) -> LedgerEntry:
    ledger = ExecutionLedger()
    built = ledger.record(
        LedgerRecordInput(
            timestamp_ref=timestamp_ref,
            execution_id=execution_id,
            stage=stage,
            status=status,
            data_snapshot=payload if payload is not None else {"order_id": "A", "qty": 1},
            upstream_refs={"phase": "6.2"},
        )
    )
    assert built is not None
    return built


def _config(path: Path, *, allow_reload: bool = True, allow_query: bool = True) -> PersistentLedgerConfig:
    return PersistentLedgerConfig(
        storage_path=str(path),
        create_if_missing=True,
        enforce_append_only=True,
        allow_reload=allow_reload,
        allow_query=allow_query,
    )


def test_phase6_2_valid_append_persists_entry(tmp_path: Path) -> None:
    ledger = PersistentExecutionLedger()
    storage = tmp_path / "ledger.jsonl"

    result = ledger.append_entry(entry=_sample_entry(), config=_config(storage))

    assert result.success is True
    assert result.written is True
    assert result.bytes_written is not None and result.bytes_written > 0
    assert result.append_only_confirmed is True
    lines = storage.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1


def test_phase6_2_valid_load_reconstructs_entries(tmp_path: Path) -> None:
    ledger = PersistentExecutionLedger()
    storage = tmp_path / "ledger.jsonl"
    first = _sample_entry()
    second = _sample_entry(
        stage="exchange",
        status="filled",
        timestamp_ref="2026-04-13T10:00:01Z",
        payload={"order_id": "A", "fill": 1},
    )

    ledger.append_entry(entry=first, config=_config(storage))
    ledger.append_entry(entry=second, config=_config(storage))

    loaded = ledger.load_entries(config=_config(storage))

    assert loaded.success is True
    assert loaded.loaded is True
    assert loaded.entry_count == 2
    assert loaded.entries[0] == first
    assert loaded.entries[1] == second


def test_phase6_2_deterministic_serialized_content(tmp_path: Path) -> None:
    ledger = PersistentExecutionLedger()
    entry = _sample_entry()
    path_a = tmp_path / "a.jsonl"
    path_b = tmp_path / "b.jsonl"

    ledger.append_entry(entry=entry, config=_config(path_a))
    ledger.append_entry(entry=entry, config=_config(path_b))

    assert path_a.read_text(encoding="utf-8") == path_b.read_text(encoding="utf-8")


def test_phase6_2_deterministic_query_ordering(tmp_path: Path) -> None:
    ledger = PersistentExecutionLedger()
    storage = tmp_path / "ledger.jsonl"

    first = _sample_entry(timestamp_ref="2026-04-13T10:00:00Z")
    second = _sample_entry(
        stage="exchange",
        timestamp_ref="2026-04-13T10:00:01Z",
        payload={"order_id": "A", "fill": 1},
        status="filled",
    )

    ledger.append_entry(entry=first, config=_config(storage))
    ledger.append_entry(entry=second, config=_config(storage))

    result = ledger.list_audit_records(
        query_input=AuditTrailQueryInput(execution_id="exec-001", stage=None, status=None, limit=None),
        config=_config(storage),
    )

    assert result.success is True
    assert [record.entry_id for record in result.records] == [first.entry_id, second.entry_id]


def test_phase6_2_append_only_behavior(tmp_path: Path) -> None:
    ledger = PersistentExecutionLedger()
    storage = tmp_path / "ledger.jsonl"

    ledger.append_entry(entry=_sample_entry(), config=_config(storage))
    before = storage.stat().st_size
    ledger.append_entry(
        entry=_sample_entry(
            stage="capital",
            status="ok",
            timestamp_ref="2026-04-13T10:00:02Z",
            payload={"capital": 100.0},
        ),
        config=_config(storage),
    )

    assert storage.stat().st_size > before
    assert len(storage.read_text(encoding="utf-8").strip().splitlines()) == 2


def test_phase6_2_invalid_config_blocked() -> None:
    ledger = PersistentExecutionLedger()

    result = ledger.append_entry(entry=_sample_entry(), config=None)  # type: ignore[arg-type]

    assert result.success is False
    assert result.blocked_reason == PERSISTENT_LEDGER_BLOCK_INVALID_CONFIG


def test_phase6_2_missing_storage_path_blocked() -> None:
    ledger = PersistentExecutionLedger()
    config = PersistentLedgerConfig(
        storage_path="",
        create_if_missing=True,
        enforce_append_only=True,
        allow_reload=True,
        allow_query=True,
    )

    result = ledger.append_entry(entry=_sample_entry(), config=config)

    assert result.success is False
    assert result.blocked_reason == PERSISTENT_LEDGER_BLOCK_MISSING_STORAGE_PATH


def test_phase6_2_malformed_persisted_record_blocked_on_load(tmp_path: Path) -> None:
    ledger = PersistentExecutionLedger()
    storage = tmp_path / "ledger.jsonl"
    storage.write_text("{not-json}\n", encoding="utf-8")

    result = ledger.load_entries(config=_config(storage))

    assert result.success is False
    assert result.blocked_reason == PERSISTENT_LEDGER_BLOCK_MALFORMED_RECORD


def test_phase6_2_hash_mismatch_blocked_on_load(tmp_path: Path) -> None:
    ledger = PersistentExecutionLedger()
    storage = tmp_path / "ledger.jsonl"
    storage.write_text(
        '{"data_snapshot":{"x":1},"entry_id":"bad","execution_id":"exec-001","hash":"bad-hash","stage":"transport","status":"ok","timestamp_ref":"2026-04-13T10:00:00Z","upstream_refs":{"phase":"6.2"}}\n',
        encoding="utf-8",
    )

    result = ledger.load_entries(config=_config(storage))

    assert result.success is False
    assert result.blocked_reason == PERSISTENT_LEDGER_BLOCK_HASH_MISMATCH


def test_phase6_2_query_filtering_by_execution_stage_status(tmp_path: Path) -> None:
    ledger = PersistentExecutionLedger()
    storage = tmp_path / "ledger.jsonl"

    first = _sample_entry(execution_id="exec-1", stage="transport", status="ok")
    second = _sample_entry(
        execution_id="exec-1",
        stage="exchange",
        status="filled",
        payload={"order_id": "A", "fill": 1},
        timestamp_ref="2026-04-13T10:00:01Z",
    )
    third = _sample_entry(
        execution_id="exec-2",
        stage="exchange",
        status="filled",
        payload={"order_id": "B", "fill": 2},
        timestamp_ref="2026-04-13T10:00:02Z",
    )

    ledger.append_entry(entry=first, config=_config(storage))
    ledger.append_entry(entry=second, config=_config(storage))
    ledger.append_entry(entry=third, config=_config(storage))

    result = ledger.list_audit_records(
        query_input=AuditTrailQueryInput(execution_id="exec-1", stage="exchange", status="filled", limit=1),
        config=_config(storage),
    )

    assert result.success is True
    assert result.result_count == 1
    assert result.records[0].entry_id == second.entry_id


def test_phase6_2_invalid_entry_does_not_crash(tmp_path: Path) -> None:
    ledger = PersistentExecutionLedger()
    storage = tmp_path / "ledger.jsonl"

    result = ledger.append_entry(entry=None, config=_config(storage))

    assert result.success is False
    assert result.blocked_reason == PERSISTENT_LEDGER_BLOCK_INVALID_LEDGER_ENTRY
