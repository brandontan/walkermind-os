"""Priority 7 — Reconciliation Engine — Tests.

Test IDs: ST-24 .. ST-28

Coverage:
  ST-24  MATCH outcome when internal and external statuses agree
  ST-25  MISMATCH outcome when statuses disagree
  ST-26  STUCK detection: PROCESSING beyond threshold
  ST-27  MISSING outcome: completed internally, no external record
  ST-28  ORPHAN outcome: external record exists, no internal record
  ST-28b Repair action classification for each outcome
  ST-28c reconcile_batch aggregates counts correctly
  ST-28d reconcile_batch returns empty result on zero entries
"""
from __future__ import annotations

import pytest

from projects.polymarket.polyquantbot.server.settlement.reconciliation_engine import (
    ReconciliationEngine,
)
from projects.polymarket.polyquantbot.server.settlement.schemas import (
    RECON_OUTCOME_MATCH,
    RECON_OUTCOME_MISMATCH,
    RECON_OUTCOME_MISSING,
    RECON_OUTCOME_ORPHAN,
    RECON_OUTCOME_STUCK,
    RECON_STUCK_THRESHOLD_S,
    REPAIR_ACTION_CANCEL,
    REPAIR_ACTION_FLAG_MANUAL,
    REPAIR_ACTION_NO_ACTION,
    REPAIR_ACTION_RETRY,
    SETTLEMENT_STATUS_COMPLETED,
    SETTLEMENT_STATUS_PROCESSING,
    ReconciliationEntry,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _entry(
    workflow_id: str = "stl_aaa",
    internal_status: str = SETTLEMENT_STATUS_COMPLETED,
    external_status: str | None = SETTLEMENT_STATUS_COMPLETED,
    age_s: float = 0.0,
    internal_amount: float = 100.0,
    external_amount: float | None = 100.0,
) -> ReconciliationEntry:
    return ReconciliationEntry(
        workflow_id=workflow_id,
        internal_status=internal_status,
        external_status=external_status,
        age_s=age_s,
        internal_amount=internal_amount,
        external_amount=external_amount,
    )


_engine = ReconciliationEngine()


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_st_24_match_when_statuses_agree():
    """ST-24: MATCH outcome when internal and external statuses are identical."""
    result = _engine.reconcile_single(_entry(
        internal_status=SETTLEMENT_STATUS_COMPLETED,
        external_status=SETTLEMENT_STATUS_COMPLETED,
    ))
    assert result.outcome == RECON_OUTCOME_MATCH
    assert result.is_stuck is False
    assert result.repair_action == REPAIR_ACTION_NO_ACTION
    assert result.mismatch_reason is None


def test_st_25_mismatch_when_statuses_differ():
    """ST-25: MISMATCH outcome when internal and external statuses disagree."""
    result = _engine.reconcile_single(_entry(
        internal_status=SETTLEMENT_STATUS_COMPLETED,
        external_status="FAILED",
    ))
    assert result.outcome == RECON_OUTCOME_MISMATCH
    assert result.mismatch_reason is not None
    assert "mismatch" in result.mismatch_reason


def test_st_26_stuck_when_processing_beyond_threshold():
    """ST-26: STUCK when PROCESSING and age_s exceeds RECON_STUCK_THRESHOLD_S."""
    result = _engine.reconcile_single(_entry(
        internal_status=SETTLEMENT_STATUS_PROCESSING,
        external_status=SETTLEMENT_STATUS_PROCESSING,
        age_s=RECON_STUCK_THRESHOLD_S + 1.0,
    ))
    assert result.outcome == RECON_OUTCOME_STUCK
    assert result.is_stuck is True
    assert result.repair_action == REPAIR_ACTION_RETRY


def test_st_26b_not_stuck_below_threshold():
    """ST-26b: NOT stuck when PROCESSING but age_s <= threshold."""
    result = _engine.reconcile_single(_entry(
        internal_status=SETTLEMENT_STATUS_PROCESSING,
        external_status=SETTLEMENT_STATUS_PROCESSING,
        age_s=RECON_STUCK_THRESHOLD_S - 1.0,
    ))
    assert result.outcome != RECON_OUTCOME_STUCK
    assert result.is_stuck is False


def test_st_26c_stuck_exactly_at_threshold_is_not_stuck():
    """ST-26c: age_s == threshold is NOT stuck (boundary uses strict >)."""
    result = _engine.reconcile_single(_entry(
        internal_status=SETTLEMENT_STATUS_PROCESSING,
        external_status=SETTLEMENT_STATUS_PROCESSING,
        age_s=RECON_STUCK_THRESHOLD_S,
    ))
    assert result.is_stuck is False


def test_st_27_missing_when_completed_internally_no_external():
    """ST-27: MISSING when internal=COMPLETED and external_status is None."""
    result = _engine.reconcile_single(_entry(
        internal_status=SETTLEMENT_STATUS_COMPLETED,
        external_status=None,
    ))
    assert result.outcome == RECON_OUTCOME_MISSING
    assert result.repair_action == REPAIR_ACTION_FLAG_MANUAL


def test_st_28_orphan_when_external_exists_no_internal():
    """ST-28: ORPHAN when internal_status is empty string but external exists."""
    result = _engine.reconcile_single(_entry(
        internal_status="",
        external_status=SETTLEMENT_STATUS_COMPLETED,
    ))
    assert result.outcome == RECON_OUTCOME_ORPHAN
    assert result.repair_action == REPAIR_ACTION_CANCEL


def test_st_28b_repair_action_classification():
    """ST-28b: _classify_repair_action returns correct action for each outcome."""
    assert ReconciliationEngine._classify_repair_action(RECON_OUTCOME_STUCK,    True)  == REPAIR_ACTION_RETRY
    assert ReconciliationEngine._classify_repair_action(RECON_OUTCOME_ORPHAN,   False) == REPAIR_ACTION_CANCEL
    assert ReconciliationEngine._classify_repair_action(RECON_OUTCOME_MISMATCH, False) == REPAIR_ACTION_FLAG_MANUAL
    assert ReconciliationEngine._classify_repair_action(RECON_OUTCOME_MISSING,  False) == REPAIR_ACTION_FLAG_MANUAL
    assert ReconciliationEngine._classify_repair_action(RECON_OUTCOME_MATCH,    False) == REPAIR_ACTION_NO_ACTION


def test_st_28c_batch_aggregates_counts():
    """ST-28c: reconcile_batch counts match/mismatch/stuck/missing/orphan correctly."""
    entries = [
        _entry("stl_1", SETTLEMENT_STATUS_COMPLETED, SETTLEMENT_STATUS_COMPLETED),  # match
        _entry("stl_2", SETTLEMENT_STATUS_COMPLETED, "FAILED"),                     # mismatch
        _entry("stl_3", SETTLEMENT_STATUS_PROCESSING, SETTLEMENT_STATUS_PROCESSING,
               age_s=RECON_STUCK_THRESHOLD_S + 1),                                  # stuck
        _entry("stl_4", SETTLEMENT_STATUS_COMPLETED, None),                         # missing
        _entry("stl_5", "", SETTLEMENT_STATUS_COMPLETED),                           # orphan
    ]
    batch = _engine.reconcile_batch(entries)

    assert batch.total_checked == 5
    assert batch.match_count    == 1
    assert batch.mismatch_count == 1
    assert batch.stuck_count    == 1
    assert batch.missing_count  == 1
    assert batch.orphan_count   == 1
    assert len(batch.results)   == 5


def test_st_28d_batch_empty_entries_returns_zero_counts():
    """ST-28d: reconcile_batch with zero entries returns all-zero counts."""
    batch = _engine.reconcile_batch([])
    assert batch.total_checked == 0
    assert batch.match_count   == 0
    assert batch.results       == ()
