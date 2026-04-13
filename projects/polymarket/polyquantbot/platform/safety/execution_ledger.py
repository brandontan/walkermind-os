from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
import hashlib
import json
from typing import Any

from projects.polymarket.polyquantbot.platform.execution.execution_transport import ExecutionTransportResult
from projects.polymarket.polyquantbot.platform.execution.exchange_integration import ExchangeExecutionResult
from projects.polymarket.polyquantbot.platform.execution.fund_settlement import FundSettlementResult
from projects.polymarket.polyquantbot.platform.execution.secure_signing import SigningResult
from projects.polymarket.polyquantbot.platform.execution.wallet_capital import WalletCapitalResult

LEDGER_BLOCK_INVALID_STAGE = "invalid_stage"
LEDGER_BLOCK_MISSING_SNAPSHOT = "missing_snapshot"
LEDGER_BLOCK_INVALID_UPSTREAM_REFS = "invalid_upstream_refs"

LEDGER_ALLOWED_STAGES = {"transport", "exchange", "signing", "capital", "settlement"}


@dataclass(frozen=True)
class LedgerEntry:
    entry_id: str
    timestamp_ref: str
    execution_id: str | None
    stage: str
    status: str
    data_snapshot: dict[str, Any]
    upstream_refs: dict[str, Any]
    hash: str


@dataclass(frozen=True)
class LedgerTrace:
    record_attempted: bool
    blocked_reason: str | None
    trace_refs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LedgerBuildResult:
    entry: LedgerEntry | None
    trace: LedgerTrace


@dataclass(frozen=True)
class ReconciliationCheckResult:
    consistent: bool
    mismatch_reason: str | None
    expected_balance: float | None
    observed_balance: float | None
    reconciliation_notes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LedgerRecordInput:
    timestamp_ref: str
    execution_id: str | None
    stage: str
    status: str
    data_snapshot: dict[str, Any]
    upstream_refs: dict[str, Any]
    snapshot_source: (
        ExecutionTransportResult
        | ExchangeExecutionResult
        | SigningResult
        | WalletCapitalResult
        | FundSettlementResult
        | None
    ) = None


@dataclass(frozen=True)
class ReconciliationInput:
    execution_id: str | None
    capital_snapshot: dict[str, Any]
    settlement_result: FundSettlementResult | None


class ExecutionLedger:
    """Phase 6.1 deterministic in-memory append-only execution ledger."""

    def __init__(self) -> None:
        self._entries: list[LedgerEntry] = []

    def record(self, record_input: LedgerRecordInput) -> LedgerEntry | None:
        return self.record_with_trace(record_input=record_input).entry

    def record_with_trace(self, *, record_input: LedgerRecordInput) -> LedgerBuildResult:
        if not isinstance(record_input, LedgerRecordInput):
            return LedgerBuildResult(
                entry=None,
                trace=LedgerTrace(
                    record_attempted=False,
                    blocked_reason=LEDGER_BLOCK_MISSING_SNAPSHOT,
                    trace_refs={
                        "contract_error": {
                            "expected_type": "LedgerRecordInput",
                            "actual_type": type(record_input).__name__,
                        }
                    },
                ),
            )

        block_reason = _validate_record_input(record_input=record_input)
        if block_reason is not None:
            return LedgerBuildResult(
                entry=None,
                trace=LedgerTrace(
                    record_attempted=False,
                    blocked_reason=block_reason,
                    trace_refs={
                        "execution_id": record_input.execution_id,
                        "stage": record_input.stage,
                    },
                ),
            )

        snapshot_hash = _stable_hash(record_input.data_snapshot)
        upstream_refs = _copy_dict(record_input.upstream_refs)
        entry_id = _build_entry_id(
            timestamp_ref=record_input.timestamp_ref,
            execution_id=record_input.execution_id,
            stage=record_input.stage,
            status=record_input.status,
            snapshot_hash=snapshot_hash,
            upstream_refs=upstream_refs,
        )

        entry = LedgerEntry(
            entry_id=entry_id,
            timestamp_ref=record_input.timestamp_ref,
            execution_id=record_input.execution_id,
            stage=record_input.stage,
            status=record_input.status,
            data_snapshot=_copy_dict(record_input.data_snapshot),
            upstream_refs=upstream_refs,
            hash=snapshot_hash,
        )
        self._entries.append(entry)

        return LedgerBuildResult(
            entry=entry,
            trace=LedgerTrace(
                record_attempted=True,
                blocked_reason=None,
                trace_refs={
                    "entry_id": entry.entry_id,
                    "stage": entry.stage,
                    "execution_id": entry.execution_id,
                },
            ),
        )

    def get_all_entries(self) -> tuple[LedgerEntry, ...]:
        return tuple(self._entries)

    def get_entries_by_execution_id(self, execution_id: str) -> tuple[LedgerEntry, ...]:
        return tuple(entry for entry in self._entries if entry.execution_id == execution_id)


class ReconciliationEngine:
    """Read-only deterministic reconciliation for Phase 6.1 foundation."""

    def check_consistency(self, reconciliation_input: ReconciliationInput) -> ReconciliationCheckResult:
        if not isinstance(reconciliation_input, ReconciliationInput):
            return ReconciliationCheckResult(
                consistent=False,
                mismatch_reason="invalid_reconciliation_input",
                expected_balance=None,
                observed_balance=None,
                reconciliation_notes={
                    "expected_type": "ReconciliationInput",
                    "actual_type": type(reconciliation_input).__name__,
                },
            )

        if reconciliation_input.settlement_result is None:
            return ReconciliationCheckResult(
                consistent=False,
                mismatch_reason="missing_settlement_result",
                expected_balance=None,
                observed_balance=None,
                reconciliation_notes={"execution_id": reconciliation_input.execution_id},
            )

        if not isinstance(reconciliation_input.capital_snapshot, dict):
            return ReconciliationCheckResult(
                consistent=False,
                mismatch_reason="invalid_capital_snapshot",
                expected_balance=None,
                observed_balance=None,
                reconciliation_notes={
                    "execution_id": reconciliation_input.execution_id,
                    "actual_type": type(reconciliation_input.capital_snapshot).__name__,
                },
            )

        balance_before = _to_float(reconciliation_input.capital_snapshot.get("balance_before"))
        if balance_before is None:
            balance_before = _to_float(reconciliation_input.capital_snapshot.get("available"))

        settlement = reconciliation_input.settlement_result
        if balance_before is None or settlement.balance_before is None or settlement.balance_after is None:
            return ReconciliationCheckResult(
                consistent=False,
                mismatch_reason="missing_balance_fields",
                expected_balance=None,
                observed_balance=settlement.balance_after,
                reconciliation_notes={"execution_id": reconciliation_input.execution_id},
            )

        amount = settlement.amount if settlement.amount is not None else 0.0
        expected_balance = balance_before - amount if settlement.settled else balance_before
        observed_balance = settlement.balance_after

        if settlement.balance_before != balance_before:
            return ReconciliationCheckResult(
                consistent=False,
                mismatch_reason="balance_before_mismatch",
                expected_balance=expected_balance,
                observed_balance=observed_balance,
                reconciliation_notes={
                    "capital_balance_before": balance_before,
                    "settlement_balance_before": settlement.balance_before,
                },
            )

        if expected_balance != observed_balance:
            return ReconciliationCheckResult(
                consistent=False,
                mismatch_reason="balance_after_mismatch",
                expected_balance=expected_balance,
                observed_balance=observed_balance,
                reconciliation_notes={
                    "amount": amount,
                    "settled": settlement.settled,
                },
            )

        return ReconciliationCheckResult(
            consistent=True,
            mismatch_reason=None,
            expected_balance=expected_balance,
            observed_balance=observed_balance,
            reconciliation_notes={
                "execution_id": reconciliation_input.execution_id,
                "deterministic": True,
            },
        )


def _validate_record_input(*, record_input: LedgerRecordInput) -> str | None:
    if record_input.stage not in LEDGER_ALLOWED_STAGES:
        return LEDGER_BLOCK_INVALID_STAGE

    if not isinstance(record_input.data_snapshot, dict) or len(record_input.data_snapshot) == 0:
        return LEDGER_BLOCK_MISSING_SNAPSHOT

    if not isinstance(record_input.upstream_refs, dict) or not _is_mapping_serializable(record_input.upstream_refs):
        return LEDGER_BLOCK_INVALID_UPSTREAM_REFS

    if record_input.snapshot_source is not None and not isinstance(
        record_input.snapshot_source,
        (
            ExecutionTransportResult,
            ExchangeExecutionResult,
            SigningResult,
            WalletCapitalResult,
            FundSettlementResult,
        ),
    ):
        return LEDGER_BLOCK_INVALID_UPSTREAM_REFS

    return None


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
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=_json_default)


def _json_default(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    return str(value)


def _is_mapping_serializable(value: dict[str, Any]) -> bool:
    for key in value.keys():
        if not isinstance(key, str) or key == "":
            return False
    try:
        _canonical_json(value)
    except (TypeError, ValueError):
        return False
    return True


def _copy_dict(source: dict[str, Any]) -> dict[str, Any]:
    return json.loads(_canonical_json(source))


def _to_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None
