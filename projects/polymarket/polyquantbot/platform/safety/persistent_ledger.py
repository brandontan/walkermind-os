from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any

from .execution_ledger import LedgerBuildResult, LedgerEntry

PERSISTENT_LEDGER_BLOCK_INVALID_CONFIG = "invalid_persistent_config"
PERSISTENT_LEDGER_BLOCK_MISSING_STORAGE_PATH = "missing_storage_path"
PERSISTENT_LEDGER_BLOCK_INVALID_LEDGER_ENTRY = "invalid_ledger_entry"
PERSISTENT_LEDGER_BLOCK_MALFORMED_RECORD = "malformed_persisted_record"
PERSISTENT_LEDGER_BLOCK_HASH_MISMATCH = "persisted_hash_mismatch"
PERSISTENT_LEDGER_BLOCK_QUERY_NOT_ALLOWED = "query_not_allowed"
PERSISTENT_LEDGER_BLOCK_RELOAD_NOT_ALLOWED = "reload_not_allowed"


@dataclass(frozen=True)
class PersistentLedgerConfig:
    storage_path: str
    create_if_missing: bool
    enforce_append_only: bool
    allow_reload: bool
    allow_query: bool


@dataclass(frozen=True)
class AuditTrailQueryInput:
    execution_id: str | None
    stage: str | None
    status: str | None
    limit: int | None


@dataclass(frozen=True)
class PersistentLedgerWriteResult:
    written: bool
    success: bool
    blocked_reason: str | None
    entry_id: str | None
    storage_path: str | None
    bytes_written: int | None
    append_only_confirmed: bool


@dataclass(frozen=True)
class PersistentLedgerLoadResult:
    loaded: bool
    success: bool
    blocked_reason: str | None
    entry_count: int
    storage_path: str | None
    entries: tuple[LedgerEntry, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class AuditTrailRecord:
    entry_id: str
    execution_id: str | None
    stage: str
    status: str
    timestamp_ref: str
    hash: str


@dataclass(frozen=True)
class AuditTrailQueryResult:
    success: bool
    blocked_reason: str | None
    result_count: int
    records: tuple[AuditTrailRecord, ...] = field(default_factory=tuple)


class PersistentExecutionLedger:
    """Phase 6.2 local append-only persistent ledger and audit-trail queries."""

    def append_entry(
        self,
        entry: LedgerEntry | LedgerBuildResult | None,
        config: PersistentLedgerConfig,
    ) -> PersistentLedgerWriteResult:
        config_error = _validate_config(config)
        if config_error is not None:
            return PersistentLedgerWriteResult(
                written=False,
                success=False,
                blocked_reason=config_error,
                entry_id=None,
                storage_path=None,
                bytes_written=None,
                append_only_confirmed=False,
            )

        path = Path(config.storage_path)
        path_error = _prepare_storage_path(path=path, create_if_missing=config.create_if_missing)
        if path_error is not None:
            return PersistentLedgerWriteResult(
                written=False,
                success=False,
                blocked_reason=path_error,
                entry_id=None,
                storage_path=str(path),
                bytes_written=None,
                append_only_confirmed=False,
            )

        resolved_entry = _resolve_entry(entry)
        if resolved_entry is None:
            return PersistentLedgerWriteResult(
                written=False,
                success=False,
                blocked_reason=PERSISTENT_LEDGER_BLOCK_INVALID_LEDGER_ENTRY,
                entry_id=None,
                storage_path=str(path),
                bytes_written=None,
                append_only_confirmed=False,
            )

        line = _serialize_line(resolved_entry)
        data = f"{line}\n".encode("utf-8")

        with path.open("ab") as handle:
            written = handle.write(data)

        return PersistentLedgerWriteResult(
            written=written > 0,
            success=written > 0,
            blocked_reason=None,
            entry_id=resolved_entry.entry_id,
            storage_path=str(path),
            bytes_written=written,
            append_only_confirmed=config.enforce_append_only,
        )

    def load_entries(self, config: PersistentLedgerConfig) -> PersistentLedgerLoadResult:
        config_error = _validate_config(config)
        if config_error is not None:
            return PersistentLedgerLoadResult(
                loaded=False,
                success=False,
                blocked_reason=config_error,
                entry_count=0,
                storage_path=None,
                entries=(),
            )

        if not config.allow_reload:
            return PersistentLedgerLoadResult(
                loaded=False,
                success=False,
                blocked_reason=PERSISTENT_LEDGER_BLOCK_RELOAD_NOT_ALLOWED,
                entry_count=0,
                storage_path=config.storage_path,
                entries=(),
            )

        path = Path(config.storage_path)
        path_error = _prepare_storage_path(path=path, create_if_missing=config.create_if_missing)
        if path_error is not None:
            return PersistentLedgerLoadResult(
                loaded=False,
                success=False,
                blocked_reason=path_error,
                entry_count=0,
                storage_path=str(path),
                entries=(),
            )

        return _read_entries(path=path)

    def list_audit_records(
        self,
        query_input: AuditTrailQueryInput,
        config: PersistentLedgerConfig,
    ) -> AuditTrailQueryResult:
        config_error = _validate_config(config)
        if config_error is not None:
            return AuditTrailQueryResult(
                success=False,
                blocked_reason=config_error,
                result_count=0,
                records=(),
            )

        if not isinstance(query_input, AuditTrailQueryInput):
            return AuditTrailQueryResult(
                success=False,
                blocked_reason=PERSISTENT_LEDGER_BLOCK_INVALID_CONFIG,
                result_count=0,
                records=(),
            )

        if not config.allow_query:
            return AuditTrailQueryResult(
                success=False,
                blocked_reason=PERSISTENT_LEDGER_BLOCK_QUERY_NOT_ALLOWED,
                result_count=0,
                records=(),
            )

        path = Path(config.storage_path)
        path_error = _prepare_storage_path(path=path, create_if_missing=config.create_if_missing)
        if path_error is not None:
            return AuditTrailQueryResult(
                success=False,
                blocked_reason=path_error,
                result_count=0,
                records=(),
            )

        load_result = _read_entries(path=path)
        if not load_result.success:
            return AuditTrailQueryResult(
                success=False,
                blocked_reason=load_result.blocked_reason,
                result_count=0,
                records=(),
            )

        records = tuple(_to_audit_record(entry) for entry in load_result.entries)
        filtered = _filter_records(records=records, query_input=query_input)
        return AuditTrailQueryResult(
            success=True,
            blocked_reason=None,
            result_count=len(filtered),
            records=filtered,
        )


def _resolve_entry(entry: LedgerEntry | LedgerBuildResult | None) -> LedgerEntry | None:
    if isinstance(entry, LedgerEntry):
        return entry if _validate_ledger_entry(entry) else None
    if isinstance(entry, LedgerBuildResult) and entry.entry is not None and _validate_ledger_entry(entry.entry):
        return entry.entry
    return None


def _prepare_storage_path(*, path: Path, create_if_missing: bool) -> str | None:
    if not str(path).strip():
        return PERSISTENT_LEDGER_BLOCK_MISSING_STORAGE_PATH
    if path.exists() and path.is_dir():
        return PERSISTENT_LEDGER_BLOCK_MISSING_STORAGE_PATH

    if not path.exists():
        if not create_if_missing:
            return PERSISTENT_LEDGER_BLOCK_MISSING_STORAGE_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    return None


def _validate_config(config: PersistentLedgerConfig | None) -> str | None:
    if not isinstance(config, PersistentLedgerConfig):
        return PERSISTENT_LEDGER_BLOCK_INVALID_CONFIG

    if not isinstance(config.storage_path, str):
        return PERSISTENT_LEDGER_BLOCK_INVALID_CONFIG

    if not config.storage_path.strip():
        return PERSISTENT_LEDGER_BLOCK_MISSING_STORAGE_PATH

    fields_valid = all(
        isinstance(value, bool)
        for value in (
            config.create_if_missing,
            config.enforce_append_only,
            config.allow_reload,
            config.allow_query,
        )
    )
    if not fields_valid:
        return PERSISTENT_LEDGER_BLOCK_INVALID_CONFIG
    return None


def _validate_ledger_entry(entry: LedgerEntry) -> bool:
    expected_hash = _stable_hash(entry.data_snapshot)
    if expected_hash != entry.hash:
        return False

    expected_entry_id = _build_entry_id(
        timestamp_ref=entry.timestamp_ref,
        execution_id=entry.execution_id,
        stage=entry.stage,
        status=entry.status,
        snapshot_hash=entry.hash,
        upstream_refs=entry.upstream_refs,
    )
    return expected_entry_id == entry.entry_id


def _serialize_line(entry: LedgerEntry) -> str:
    payload = {
        "entry_id": entry.entry_id,
        "timestamp_ref": entry.timestamp_ref,
        "execution_id": entry.execution_id,
        "stage": entry.stage,
        "status": entry.status,
        "data_snapshot": entry.data_snapshot,
        "upstream_refs": entry.upstream_refs,
        "hash": entry.hash,
    }
    return _canonical_json(payload)


def _read_entries(*, path: Path) -> PersistentLedgerLoadResult:
    entries: list[LedgerEntry] = []

    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if line == "":
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                return PersistentLedgerLoadResult(
                    loaded=False,
                    success=False,
                    blocked_reason=PERSISTENT_LEDGER_BLOCK_MALFORMED_RECORD,
                    entry_count=0,
                    storage_path=str(path),
                    entries=(),
                )

            entry = _entry_from_payload(payload)
            if entry is None:
                return PersistentLedgerLoadResult(
                    loaded=False,
                    success=False,
                    blocked_reason=PERSISTENT_LEDGER_BLOCK_MALFORMED_RECORD,
                    entry_count=0,
                    storage_path=str(path),
                    entries=(),
                )

            if not _validate_ledger_entry(entry):
                return PersistentLedgerLoadResult(
                    loaded=False,
                    success=False,
                    blocked_reason=PERSISTENT_LEDGER_BLOCK_HASH_MISMATCH,
                    entry_count=0,
                    storage_path=str(path),
                    entries=(),
                )

            entries.append(entry)

    return PersistentLedgerLoadResult(
        loaded=True,
        success=True,
        blocked_reason=None,
        entry_count=len(entries),
        storage_path=str(path),
        entries=tuple(entries),
    )


def _entry_from_payload(payload: Any) -> LedgerEntry | None:
    if not isinstance(payload, dict):
        return None

    expected_keys = {
        "entry_id",
        "timestamp_ref",
        "execution_id",
        "stage",
        "status",
        "data_snapshot",
        "upstream_refs",
        "hash",
    }
    if set(payload.keys()) != expected_keys:
        return None

    if not isinstance(payload["entry_id"], str) or payload["entry_id"] == "":
        return None
    if not isinstance(payload["timestamp_ref"], str) or payload["timestamp_ref"] == "":
        return None
    if payload["execution_id"] is not None and not isinstance(payload["execution_id"], str):
        return None
    if not isinstance(payload["stage"], str) or payload["stage"] == "":
        return None
    if not isinstance(payload["status"], str) or payload["status"] == "":
        return None
    if not isinstance(payload["data_snapshot"], dict):
        return None
    if not isinstance(payload["upstream_refs"], dict):
        return None
    if not isinstance(payload["hash"], str) or payload["hash"] == "":
        return None

    return LedgerEntry(
        entry_id=payload["entry_id"],
        timestamp_ref=payload["timestamp_ref"],
        execution_id=payload["execution_id"],
        stage=payload["stage"],
        status=payload["status"],
        data_snapshot=payload["data_snapshot"],
        upstream_refs=payload["upstream_refs"],
        hash=payload["hash"],
    )


def _to_audit_record(entry: LedgerEntry) -> AuditTrailRecord:
    return AuditTrailRecord(
        entry_id=entry.entry_id,
        execution_id=entry.execution_id,
        stage=entry.stage,
        status=entry.status,
        timestamp_ref=entry.timestamp_ref,
        hash=entry.hash,
    )


def _filter_records(
    *,
    records: tuple[AuditTrailRecord, ...],
    query_input: AuditTrailQueryInput,
) -> tuple[AuditTrailRecord, ...]:
    filtered: list[AuditTrailRecord] = list(records)

    if query_input.execution_id is not None:
        filtered = [record for record in filtered if record.execution_id == query_input.execution_id]
    if query_input.stage is not None:
        filtered = [record for record in filtered if record.stage == query_input.stage]
    if query_input.status is not None:
        filtered = [record for record in filtered if record.status == query_input.status]

    if query_input.limit is not None and query_input.limit >= 0:
        filtered = filtered[: query_input.limit]

    return tuple(filtered)


def _build_entry_id(
    *,
    timestamp_ref: str,
    execution_id: str | None,
    stage: str,
    status: str,
    snapshot_hash: str,
    upstream_refs: dict[str, Any],
) -> str:
    deterministic_payload = {
        "timestamp_ref": timestamp_ref,
        "execution_id": execution_id,
        "stage": stage,
        "status": status,
        "snapshot_hash": snapshot_hash,
        "upstream_refs": upstream_refs,
    }
    return hashlib.sha256(_canonical_json(deterministic_payload).encode("utf-8")).hexdigest()


def _stable_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
