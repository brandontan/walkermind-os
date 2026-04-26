"""Reconciliation Engine — Priority 7 section 46.

Stateless, synchronous.  Receives pre-fetched internal + external state
from the service layer — never queries DB or exchange directly.

Detects:
  - MATCH      : internal and external statuses agree
  - MISMATCH   : statuses disagree
  - STUCK      : settlement in PROCESSING longer than RECON_STUCK_THRESHOLD_S
  - MISSING    : internal record exists but no external record
  - ORPHAN     : external record exists but no internal record

Prescribes a repair action for each outcome.
"""
from __future__ import annotations

from collections.abc import Sequence

import structlog

from .schemas import (
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
    BatchReconciliationResult,
    ReconciliationEntry,
    ReconciliationResult,
    _utc_now,
)

log = structlog.get_logger(__name__)


class ReconciliationEngine:
    """Stateless reconciliation engine.

    Receives pre-loaded ReconciliationEntry objects and returns deterministic
    ReconciliationResult objects.  All decisions are pure — no side effects.
    """

    def __init__(self, *, stuck_threshold_s: float = RECON_STUCK_THRESHOLD_S) -> None:
        self._stuck_threshold_s = stuck_threshold_s

    def reconcile_single(self, entry: ReconciliationEntry) -> ReconciliationResult:
        bound = log.bind(
            workflow_id=entry.workflow_id,
            internal_status=entry.internal_status,
            external_status=entry.external_status,
            age_s=entry.age_s,
        )

        is_stuck = self._detect_stuck(entry, self._stuck_threshold_s)

        # Orphan: external record exists, no internal record
        if entry.internal_status == "" and entry.external_status is not None:
            bound.info("recon_orphan")
            return ReconciliationResult(
                workflow_id=entry.workflow_id,
                settlement_id=entry.settlement_id,
                outcome=RECON_OUTCOME_ORPHAN,
                repair_action=REPAIR_ACTION_CANCEL,
                is_stuck=False,
                internal_status=entry.internal_status,
                external_status=entry.external_status,
                mismatch_reason="orphan_no_internal_record",
            )

        # Missing: internal record present but no external record
        if entry.external_status is None and entry.internal_status == SETTLEMENT_STATUS_COMPLETED:
            bound.info("recon_missing")
            return ReconciliationResult(
                workflow_id=entry.workflow_id,
                settlement_id=entry.settlement_id,
                outcome=RECON_OUTCOME_MISSING,
                repair_action=REPAIR_ACTION_FLAG_MANUAL,
                is_stuck=False,
                internal_status=entry.internal_status,
                external_status=None,
                mismatch_reason="completed_internally_but_missing_externally",
            )

        # Stuck: in PROCESSING beyond threshold
        if is_stuck:
            bound.info("recon_stuck", threshold_s=self._stuck_threshold_s)
            return ReconciliationResult(
                workflow_id=entry.workflow_id,
                settlement_id=entry.settlement_id,
                outcome=RECON_OUTCOME_STUCK,
                repair_action=REPAIR_ACTION_RETRY,
                is_stuck=True,
                internal_status=entry.internal_status,
                external_status=entry.external_status,
                mismatch_reason="processing_timeout",
            )

        # Mismatch: both sides present but disagree
        if (
            entry.external_status is not None
            and entry.internal_status != entry.external_status
        ):
            bound.info(
                "recon_mismatch",
                internal=entry.internal_status,
                external=entry.external_status,
            )
            return ReconciliationResult(
                workflow_id=entry.workflow_id,
                settlement_id=entry.settlement_id,
                outcome=RECON_OUTCOME_MISMATCH,
                repair_action=self._classify_repair_action(RECON_OUTCOME_MISMATCH, False),
                is_stuck=False,
                internal_status=entry.internal_status,
                external_status=entry.external_status,
                mismatch_reason=f"status_mismatch: internal={entry.internal_status} external={entry.external_status}",
            )

        bound.info("recon_match")
        return ReconciliationResult(
            workflow_id=entry.workflow_id,
            settlement_id=entry.settlement_id,
            outcome=RECON_OUTCOME_MATCH,
            repair_action=REPAIR_ACTION_NO_ACTION,
            is_stuck=False,
            internal_status=entry.internal_status,
            external_status=entry.external_status,
        )

    def reconcile_batch(
        self,
        entries: Sequence[ReconciliationEntry],
    ) -> BatchReconciliationResult:
        if not entries:
            return BatchReconciliationResult(
                total_checked=0,
                match_count=0,
                mismatch_count=0,
                stuck_count=0,
                missing_count=0,
                orphan_count=0,
                results=(),
            )

        results = tuple(self.reconcile_single(e) for e in entries)

        match_count    = sum(1 for r in results if r.outcome == RECON_OUTCOME_MATCH)
        mismatch_count = sum(1 for r in results if r.outcome == RECON_OUTCOME_MISMATCH)
        stuck_count    = sum(1 for r in results if r.outcome == RECON_OUTCOME_STUCK)
        missing_count  = sum(1 for r in results if r.outcome == RECON_OUTCOME_MISSING)
        orphan_count   = sum(1 for r in results if r.outcome == RECON_OUTCOME_ORPHAN)

        log.info(
            "recon_batch_done",
            total=len(entries),
            match=match_count,
            mismatch=mismatch_count,
            stuck=stuck_count,
            missing=missing_count,
            orphan=orphan_count,
        )

        return BatchReconciliationResult(
            total_checked=len(entries),
            match_count=match_count,
            mismatch_count=mismatch_count,
            stuck_count=stuck_count,
            missing_count=missing_count,
            orphan_count=orphan_count,
            results=results,
        )

    @staticmethod
    def _detect_stuck(entry: ReconciliationEntry, threshold_s: float) -> bool:
        """True if entry has been in PROCESSING beyond threshold_s."""
        return entry.internal_status == SETTLEMENT_STATUS_PROCESSING and entry.age_s > threshold_s

    @staticmethod
    def _classify_repair_action(outcome: str, is_stuck: bool) -> str:
        if is_stuck or outcome == RECON_OUTCOME_STUCK:
            return REPAIR_ACTION_RETRY
        if outcome == RECON_OUTCOME_ORPHAN:
            return REPAIR_ACTION_CANCEL
        if outcome in (RECON_OUTCOME_MISMATCH, RECON_OUTCOME_MISSING):
            return REPAIR_ACTION_FLAG_MANUAL
        return REPAIR_ACTION_NO_ACTION
