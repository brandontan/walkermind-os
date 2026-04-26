"""Priority 7 — Alert Policy + Persistence — Tests.

Test IDs: ST-33 .. ST-38

Coverage:
  ST-33  HALT anomaly -> is_critical=True in LIVE mode
  ST-33b HALT anomaly -> is_critical=False in PAPER mode
  ST-34  Fatal blocked reason -> is_critical=True in LIVE on FAILED event
  ST-35  Exhausted retries -> is_critical=True in LIVE on RETRY_ATTEMPT event
  ST-36  Stuck reconciliation -> is_drift=True
  ST-36b Partial batch -> is_drift=True
  ST-36c No recon/batch -> is_drift=False
  ST-37  Event type constants are all unique strings
  ST-38  SettlementPersistence.append_event returns True on success (stub DB)
  ST-38b SettlementPersistence.load_events_for_workflow returns [] on DB error
  ST-38c SettlementPersistence.append_retry_record returns False on DB error
"""
from __future__ import annotations

import pytest

from projects.polymarket.polyquantbot.platform.execution.fund_settlement import (
    FUND_SETTLEMENT_HALT_MONITORING_ANOMALY,
)
from projects.polymarket.polyquantbot.server.settlement.settlement_alert_policy import (
    SettlementAlertPolicy,
)
from projects.polymarket.polyquantbot.server.settlement.settlement_persistence import (
    SettlementPersistence,
)
from projects.polymarket.polyquantbot.server.settlement.schemas import (
    BATCH_STATUS_PARTIAL,
    RECON_OUTCOME_MISMATCH,
    RECON_OUTCOME_STUCK,
    RETRY_OUTCOME_EXHAUSTED,
    SETTLEMENT_EVENT_COMPLETED,
    SETTLEMENT_EVENT_CREATED,
    SETTLEMENT_EVENT_DRIFT_DETECTED,
    SETTLEMENT_EVENT_FAILED,
    SETTLEMENT_EVENT_PROCESSING,
    SETTLEMENT_EVENT_RECONCILED,
    SETTLEMENT_EVENT_RETRY_ATTEMPT,
    SETTLEMENT_EVENT_RETRY_QUEUED,
    SETTLEMENT_EVENT_CANCELLED,
    BatchReconciliationResult,
    ReconciliationResult,
    RetryAttemptRecord,
    SettlementBatchResult,
    SettlementEvent,
    BatchItemResult,
    REPAIR_ACTION_FLAG_MANUAL,
    SETTLEMENT_STATUS_COMPLETED,
    SETTLEMENT_STATUS_FAILED,
    _utc_now,
)
from projects.polymarket.polyquantbot.server.settlement.retry_engine import FATAL_BLOCK_REASONS


# ── Helpers ───────────────────────────────────────────────────────────────────

_policy = SettlementAlertPolicy()


def _event(
    event_type: str = SETTLEMENT_EVENT_FAILED,
    workflow_id: str = "stl_aaa",
    blocked_reason: str | None = None,
) -> SettlementEvent:
    payload: dict = {}
    if blocked_reason:
        payload["blocked_reason"] = blocked_reason
    return SettlementEvent(
        event_type=event_type,
        workflow_id=workflow_id,
        payload=payload,
    )


def _recon(outcome: str = RECON_OUTCOME_STUCK) -> ReconciliationResult:
    return ReconciliationResult(
        workflow_id="stl_aaa",
        outcome=outcome,
        repair_action=REPAIR_ACTION_FLAG_MANUAL,
        is_stuck=(outcome == RECON_OUTCOME_STUCK),
        internal_status=SETTLEMENT_STATUS_FAILED,
    )


def _partial_batch() -> SettlementBatchResult:
    return SettlementBatchResult(
        batch_id="bat_x",
        batch_status=BATCH_STATUS_PARTIAL,
        total_items=2,
        completed_count=1,
        failed_count=1,
        blocked_count=0,
        partial=True,
        item_results=(
            BatchItemResult(workflow_id="stl_ok",  status=SETTLEMENT_STATUS_COMPLETED, success=True),
            BatchItemResult(workflow_id="stl_bad", status=SETTLEMENT_STATUS_FAILED,    success=False),
        ),
    )


# ── Alert policy tests ────────────────────────────────────────────────────────

def test_st_33_halt_anomaly_critical_in_live():
    """ST-33: HALT monitoring anomaly is critical in LIVE mode."""
    assert SettlementAlertPolicy.is_critical(
        SETTLEMENT_EVENT_FAILED,
        FUND_SETTLEMENT_HALT_MONITORING_ANOMALY,
        "live",
    ) is True


def test_st_33b_halt_anomaly_not_critical_in_paper():
    """ST-33b: HALT monitoring anomaly is NOT critical in PAPER mode."""
    assert SettlementAlertPolicy.is_critical(
        SETTLEMENT_EVENT_FAILED,
        FUND_SETTLEMENT_HALT_MONITORING_ANOMALY,
        "paper",
    ) is False


def test_st_34_fatal_blocked_reason_critical_in_live():
    """ST-34: Any fatal blocked_reason on FAILED event is critical in LIVE."""
    for reason in FATAL_BLOCK_REASONS:
        result = SettlementAlertPolicy.is_critical(
            SETTLEMENT_EVENT_FAILED, reason, "live"
        )
        assert result is True, f"Expected critical for fatal reason {reason!r}"


def test_st_35_exhausted_retries_critical_in_live():
    """ST-35: RETRY_ATTEMPT event with EXHAUSTED outcome is critical in LIVE."""
    assert SettlementAlertPolicy.is_critical(
        SETTLEMENT_EVENT_RETRY_ATTEMPT,
        RETRY_OUTCOME_EXHAUSTED,
        "live",
    ) is True


def test_st_35b_exhausted_retries_not_critical_in_paper():
    """ST-35b: RETRY_ATTEMPT exhausted is NOT critical in PAPER."""
    assert SettlementAlertPolicy.is_critical(
        SETTLEMENT_EVENT_RETRY_ATTEMPT,
        RETRY_OUTCOME_EXHAUSTED,
        "paper",
    ) is False


def test_st_36_stuck_recon_is_drift():
    """ST-36: Stuck reconciliation result triggers is_drift=True."""
    assert SettlementAlertPolicy.is_drift(_recon(RECON_OUTCOME_STUCK), None) is True


def test_st_36b_partial_batch_is_drift():
    """ST-36b: Partial batch triggers is_drift=True."""
    assert SettlementAlertPolicy.is_drift(None, _partial_batch()) is True


def test_st_36c_no_recon_no_batch_is_not_drift():
    """ST-36c: Both None inputs return is_drift=False."""
    assert SettlementAlertPolicy.is_drift(None, None) is False


def test_st_37_event_type_constants_are_unique():
    """ST-37: All SETTLEMENT_EVENT_* constants are distinct non-empty strings."""
    constants = [
        SETTLEMENT_EVENT_CREATED,
        SETTLEMENT_EVENT_PROCESSING,
        SETTLEMENT_EVENT_COMPLETED,
        SETTLEMENT_EVENT_FAILED,
        SETTLEMENT_EVENT_RETRY_QUEUED,
        SETTLEMENT_EVENT_RETRY_ATTEMPT,
        SETTLEMENT_EVENT_CANCELLED,
        SETTLEMENT_EVENT_RECONCILED,
        SETTLEMENT_EVENT_DRIFT_DETECTED,
    ]
    assert len(constants) == len(set(constants)), "Duplicate event type constants found"
    assert all(isinstance(c, str) and c for c in constants)


# ── Persistence tests (stub DB) ───────────────────────────────────────────────

class _StubDB:
    """In-memory stub matching the asyncpg interface subset we use."""

    def __init__(self, *, raise_on_execute: bool = False, rows: list | None = None) -> None:
        self._raise = raise_on_execute
        self._rows = rows or []
        self.executed: list = []

    async def execute(self, query: str, *args) -> None:
        if self._raise:
            raise RuntimeError("db_error")
        self.executed.append((query, args))

    async def fetch(self, query: str, *args) -> list:
        if self._raise:
            raise RuntimeError("db_error")
        return self._rows


@pytest.mark.asyncio
async def test_st_38_append_event_returns_true_on_success():
    """ST-38: append_event returns True when DB.execute succeeds."""
    db = _StubDB()
    store = SettlementPersistence(db)
    evt = _event()
    result = await store.append_event(evt)
    assert result is True
    assert len(db.executed) == 1


@pytest.mark.asyncio
async def test_st_38b_load_events_returns_empty_on_db_error():
    """ST-38b: load_events_for_workflow returns [] when DB raises."""
    db = _StubDB(raise_on_execute=True)
    store = SettlementPersistence(db)
    events = await store.load_events_for_workflow("stl_aaa")
    assert events == []


@pytest.mark.asyncio
async def test_st_38c_append_retry_record_returns_false_on_db_error():
    """ST-38c: append_retry_record returns False when DB raises."""
    db = _StubDB(raise_on_execute=True)
    store = SettlementPersistence(db)
    record = RetryAttemptRecord(
        workflow_id="stl_aaa",
        attempt_number=1,
        outcome=RETRY_OUTCOME_EXHAUSTED,
    )
    result = await store.append_retry_record(record)
    assert result is False
