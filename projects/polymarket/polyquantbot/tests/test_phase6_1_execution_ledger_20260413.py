from __future__ import annotations

from dataclasses import replace

from projects.polymarket.polyquantbot.platform.execution.execution_transport import (
    EXECUTION_TRANSPORT_MODE_SIMULATED,
    ExecutionTransportResult,
)
from projects.polymarket.polyquantbot.platform.execution.exchange_integration import (
    EXCHANGE_NETWORK_MODE_SIMULATED,
    ExchangeExecutionResult,
)
from projects.polymarket.polyquantbot.platform.execution.fund_settlement import (
    FUND_SETTLEMENT_STATUS_COMPLETED,
    FundSettlementResult,
)
from projects.polymarket.polyquantbot.platform.execution.secure_signing import (
    SIGNING_METHOD_SIMULATED,
    SigningResult,
)
from projects.polymarket.polyquantbot.platform.execution.wallet_capital import (
    CAPITAL_ALLOCATION_SCOPE_SINGLE,
    WalletCapitalResult,
)
from projects.polymarket.polyquantbot.platform.safety.execution_ledger import (
    LEDGER_BLOCK_INVALID_STAGE,
    LEDGER_BLOCK_INVALID_UPSTREAM_REFS,
    LEDGER_BLOCK_MISSING_SNAPSHOT,
    ExecutionLedger,
    LedgerRecordInput,
    ReconciliationEngine,
    ReconciliationInput,
)


def _sample_transport_result() -> ExecutionTransportResult:
    return ExecutionTransportResult(
        submitted=True,
        success=True,
        blocked_reason=None,
        execution_authorized=True,
        request_payload={"order": "A"},
        exchange_response={"status": "accepted"},
        transport_mode=EXECUTION_TRANSPORT_MODE_SIMULATED,
        simulated=True,
        non_executing=True,
    )


def _sample_exchange_result() -> ExchangeExecutionResult:
    return ExchangeExecutionResult(
        executed=True,
        success=True,
        blocked_reason=None,
        execution_id="exec-001",
        request_payload={"order": "A"},
        signed_payload={"sig": "mock"},
        exchange_response={"accepted": True},
        network_used=EXCHANGE_NETWORK_MODE_SIMULATED,
        signing_used=True,
        simulated=True,
        non_executing=True,
    )


def _sample_signing_result() -> SigningResult:
    return SigningResult(
        signed=True,
        success=True,
        blocked_reason=None,
        signature="sig-001",
        payload_hash="payload-001",
        signing_scheme="HMAC",
        key_reference="key-001",
        signing_method=SIGNING_METHOD_SIMULATED,
        simulated=True,
        non_executing=True,
    )


def _sample_wallet_capital_result() -> WalletCapitalResult:
    return WalletCapitalResult(
        capital_authorized=True,
        success=True,
        blocked_reason=None,
        wallet_id="wallet-001",
        capital_amount=100.0,
        currency="USDC",
        allocation_scope=CAPITAL_ALLOCATION_SCOPE_SINGLE,
        capital_locked=True,
        balance_snapshot={"available": 1000.0, "balance_before": 1000.0},
        simulated=True,
        non_executing=True,
    )


def _sample_settlement_result() -> FundSettlementResult:
    return FundSettlementResult(
        settled=True,
        success=True,
        blocked_reason=None,
        settlement_id="settlement-001",
        wallet_id="wallet-001",
        amount=100.0,
        currency="USDC",
        transfer_reference="tx-001",
        settlement_status=FUND_SETTLEMENT_STATUS_COMPLETED,
        balance_before=1000.0,
        balance_after=900.0,
        simulated=False,
        non_executing=False,
    )


def test_phase6_1_valid_ledger_record_for_all_stages() -> None:
    ledger = ExecutionLedger()

    stage_inputs = [
        (
            "transport",
            {"transport": _sample_transport_result()},
            _sample_transport_result(),
        ),
        (
            "exchange",
            {"exchange": _sample_exchange_result()},
            _sample_exchange_result(),
        ),
        (
            "signing",
            {"signing": _sample_signing_result()},
            _sample_signing_result(),
        ),
        (
            "capital",
            {"capital": _sample_wallet_capital_result()},
            _sample_wallet_capital_result(),
        ),
        (
            "settlement",
            {"settlement": _sample_settlement_result()},
            _sample_settlement_result(),
        ),
    ]

    for stage, snapshot, source in stage_inputs:
        build = ledger.record_with_trace(
            record_input=LedgerRecordInput(
                timestamp_ref="2026-04-13T00:00:00Z",
                execution_id="exec-001",
                stage=stage,
                status="accepted",
                data_snapshot=snapshot,
                upstream_refs={"phase": "6.1", "stage": stage},
                snapshot_source=source,
            )
        )
        assert build.entry is not None
        assert build.entry.stage == stage
        assert build.trace.blocked_reason is None

    assert len(ledger.get_all_entries()) == 5


def test_phase6_1_deterministic_entry_id_and_hash() -> None:
    input_payload = LedgerRecordInput(
        timestamp_ref="2026-04-13T00:00:01Z",
        execution_id="exec-det-1",
        stage="transport",
        status="ok",
        data_snapshot={"payload": {"a": 1, "b": 2}},
        upstream_refs={"trace": "x-1"},
        snapshot_source=_sample_transport_result(),
    )

    ledger_a = ExecutionLedger()
    ledger_b = ExecutionLedger()

    first = ledger_a.record_with_trace(record_input=input_payload)
    second = ledger_b.record_with_trace(record_input=input_payload)

    assert first.entry is not None
    assert second.entry is not None
    assert first.entry.entry_id == second.entry.entry_id
    assert first.entry.hash == second.entry.hash


def test_phase6_1_invalid_stage_is_blocked() -> None:
    ledger = ExecutionLedger()

    build = ledger.record_with_trace(
        record_input=LedgerRecordInput(
            timestamp_ref="2026-04-13T00:00:02Z",
            execution_id="exec-002",
            stage="routing",
            status="blocked",
            data_snapshot={"x": 1},
            upstream_refs={"phase": "6.1"},
            snapshot_source=_sample_transport_result(),
        )
    )

    assert build.entry is None
    assert build.trace.blocked_reason == LEDGER_BLOCK_INVALID_STAGE


def test_phase6_1_missing_snapshot_is_blocked() -> None:
    ledger = ExecutionLedger()

    build = ledger.record_with_trace(
        record_input=LedgerRecordInput(
            timestamp_ref="2026-04-13T00:00:03Z",
            execution_id="exec-003",
            stage="exchange",
            status="blocked",
            data_snapshot={},
            upstream_refs={"phase": "6.1"},
            snapshot_source=_sample_exchange_result(),
        )
    )

    assert build.entry is None
    assert build.trace.blocked_reason == LEDGER_BLOCK_MISSING_SNAPSHOT


def test_phase6_1_append_only_behavior_and_retrieval() -> None:
    ledger = ExecutionLedger()

    first = ledger.record(
        LedgerRecordInput(
            timestamp_ref="2026-04-13T00:00:04Z",
            execution_id="exec-100",
            stage="transport",
            status="ok",
            data_snapshot={"step": 1},
            upstream_refs={"src": "A"},
            snapshot_source=_sample_transport_result(),
        )
    )
    second = ledger.record(
        LedgerRecordInput(
            timestamp_ref="2026-04-13T00:00:05Z",
            execution_id="exec-100",
            stage="exchange",
            status="ok",
            data_snapshot={"step": 2},
            upstream_refs={"src": "B"},
            snapshot_source=_sample_exchange_result(),
        )
    )
    third = ledger.record(
        LedgerRecordInput(
            timestamp_ref="2026-04-13T00:00:06Z",
            execution_id="exec-other",
            stage="signing",
            status="ok",
            data_snapshot={"step": 3},
            upstream_refs={"src": "C"},
            snapshot_source=_sample_signing_result(),
        )
    )

    assert first is not None and second is not None and third is not None
    all_entries = ledger.get_all_entries()
    filtered = ledger.get_entries_by_execution_id("exec-100")

    assert len(all_entries) == 3
    assert len(filtered) == 2
    assert filtered[0].entry_id == first.entry_id
    assert filtered[1].entry_id == second.entry_id


def test_phase6_1_reconciliation_success_case() -> None:
    engine = ReconciliationEngine()

    result = engine.check_consistency(
        ReconciliationInput(
            execution_id="exec-200",
            capital_snapshot={"balance_before": 1000.0},
            settlement_result=_sample_settlement_result(),
        )
    )

    assert result.consistent is True
    assert result.mismatch_reason is None
    assert result.expected_balance == 900.0
    assert result.observed_balance == 900.0


def test_phase6_1_reconciliation_mismatch_case() -> None:
    engine = ReconciliationEngine()

    mismatched_settlement = replace(_sample_settlement_result(), balance_after=899.0)
    result = engine.check_consistency(
        ReconciliationInput(
            execution_id="exec-201",
            capital_snapshot={"balance_before": 1000.0},
            settlement_result=mismatched_settlement,
        )
    )

    assert result.consistent is False
    assert result.mismatch_reason == "balance_after_mismatch"
    assert result.expected_balance == 900.0
    assert result.observed_balance == 899.0


def test_phase6_1_invalid_inputs_do_not_crash() -> None:
    ledger = ExecutionLedger()
    reconciliation = ReconciliationEngine()

    invalid_record_input = ledger.record_with_trace(record_input=None)  # type: ignore[arg-type]
    invalid_upstream_refs = ledger.record_with_trace(
        record_input=LedgerRecordInput(
            timestamp_ref="2026-04-13T00:00:08Z",
            execution_id="exec-err",
            stage="capital",
            status="blocked",
            data_snapshot={"x": 1},
            upstream_refs={"": "invalid"},
            snapshot_source=_sample_wallet_capital_result(),
        )
    )
    invalid_reconciliation = reconciliation.check_consistency(None)  # type: ignore[arg-type]
    invalid_capital_snapshot = reconciliation.check_consistency(
        ReconciliationInput(
            execution_id="exec-err-2",
            capital_snapshot="not-a-dict",  # type: ignore[arg-type]
            settlement_result=_sample_settlement_result(),
        )
    )
    missing_settlement_result = reconciliation.check_consistency(
        ReconciliationInput(
            execution_id="exec-err-3",
            capital_snapshot={"balance_before": 1000.0},
            settlement_result=None,
        )
    )

    assert invalid_record_input.entry is None
    assert invalid_record_input.trace.blocked_reason == LEDGER_BLOCK_MISSING_SNAPSHOT
    assert invalid_upstream_refs.entry is None
    assert invalid_upstream_refs.trace.blocked_reason == LEDGER_BLOCK_INVALID_UPSTREAM_REFS
    assert invalid_reconciliation.consistent is False
    assert invalid_reconciliation.mismatch_reason == "invalid_reconciliation_input"
    assert invalid_capital_snapshot.consistent is False
    assert invalid_capital_snapshot.mismatch_reason == "invalid_capital_snapshot"
    assert missing_settlement_result.consistent is False
    assert missing_settlement_result.mismatch_reason == "missing_settlement_result"
