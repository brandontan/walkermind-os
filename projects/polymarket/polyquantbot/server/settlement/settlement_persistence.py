"""Settlement Persistence — Priority 7 section 48.

Async persistence layer for settlement events, retry history, and
reconciliation results.  Uses the same fail-safe pattern as PortfolioStore:
exceptions are caught, logged, and return False rather than raised — callers
must not assume writes succeed.

All writes are idempotent: ON CONFLICT DO NOTHING on primary key.
"""
from __future__ import annotations

from typing import Any

import structlog

from .schemas import (
    ReconciliationResult,
    RetryAttemptRecord,
    SettlementEvent,
)

log = structlog.get_logger(__name__)


class SettlementPersistence:
    """Async persistence layer for the settlement domain.

    db: any async DB connection/pool that supports .execute() and .fetch().
    Follows the same interface contract as existing *Store classes in
    server/storage/.
    """

    def __init__(self, db: Any) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Write operations (idempotent)
    # ------------------------------------------------------------------

    async def append_event(self, event: SettlementEvent) -> bool:
        try:
            await self._db.execute(
                """
                INSERT INTO settlement_events
                    (event_id, event_type, workflow_id, settlement_id, payload, occurred_at)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (event_id) DO NOTHING
                """,
                event.event_id,
                event.event_type,
                event.workflow_id,
                event.settlement_id,
                event.payload,
                event.occurred_at,
            )
            return True
        except Exception as exc:
            log.error(
                "settlement_persistence_append_event_error",
                event_id=event.event_id,
                workflow_id=event.workflow_id,
                error=str(exc),
            )
            return False

    async def append_retry_record(self, record: RetryAttemptRecord) -> bool:
        try:
            await self._db.execute(
                """
                INSERT INTO settlement_retry_history
                    (workflow_id, attempt_number, outcome, settlement_id,
                     blocked_reason, delay_before_next_s, attempted_at, trace_refs)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (workflow_id, attempt_number) DO NOTHING
                """,
                record.workflow_id,
                record.attempt_number,
                record.outcome,
                record.settlement_id,
                record.blocked_reason,
                record.delay_before_next_s,
                record.attempted_at,
                record.trace_refs,
            )
            return True
        except Exception as exc:
            log.error(
                "settlement_persistence_append_retry_error",
                workflow_id=record.workflow_id,
                attempt_number=record.attempt_number,
                error=str(exc),
            )
            return False

    async def append_reconciliation_result(self, result: ReconciliationResult) -> bool:
        try:
            await self._db.execute(
                """
                INSERT INTO settlement_reconciliation_results
                    (workflow_id, settlement_id, outcome, mismatch_reason,
                     repair_action, is_stuck, internal_status, external_status,
                     trace_refs)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (workflow_id) DO UPDATE SET
                    outcome = EXCLUDED.outcome,
                    mismatch_reason = EXCLUDED.mismatch_reason,
                    repair_action = EXCLUDED.repair_action,
                    is_stuck = EXCLUDED.is_stuck,
                    internal_status = EXCLUDED.internal_status,
                    external_status = EXCLUDED.external_status,
                    trace_refs = EXCLUDED.trace_refs
                """,
                result.workflow_id,
                result.settlement_id,
                result.outcome,
                result.mismatch_reason,
                result.repair_action,
                result.is_stuck,
                result.internal_status,
                result.external_status,
                result.trace_refs,
            )
            return True
        except Exception as exc:
            log.error(
                "settlement_persistence_append_recon_error",
                workflow_id=result.workflow_id,
                error=str(exc),
            )
            return False

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def load_events_for_workflow(
        self,
        workflow_id: str,
        limit: int = 50,
    ) -> list[SettlementEvent]:
        try:
            rows = await self._db.fetch(
                """
                SELECT event_id, event_type, workflow_id, settlement_id, payload, occurred_at
                FROM settlement_events
                WHERE workflow_id = $1
                ORDER BY occurred_at ASC
                LIMIT $2
                """,
                workflow_id,
                limit,
            )
            return [_row_to_event(r) for r in rows]
        except Exception as exc:
            log.error(
                "settlement_persistence_load_events_error",
                workflow_id=workflow_id,
                error=str(exc),
            )
            return []

    async def load_retry_history(self, workflow_id: str) -> list[RetryAttemptRecord]:
        try:
            rows = await self._db.fetch(
                """
                SELECT workflow_id, attempt_number, outcome, settlement_id,
                       blocked_reason, delay_before_next_s, attempted_at, trace_refs
                FROM settlement_retry_history
                WHERE workflow_id = $1
                ORDER BY attempt_number ASC
                """,
                workflow_id,
            )
            return [_row_to_retry_record(r) for r in rows]
        except Exception as exc:
            log.error(
                "settlement_persistence_load_retry_error",
                workflow_id=workflow_id,
                error=str(exc),
            )
            return []

    async def load_reconciliation_results(
        self,
        workflow_id: str,
    ) -> list[ReconciliationResult]:
        try:
            rows = await self._db.fetch(
                """
                SELECT workflow_id, settlement_id, outcome, mismatch_reason,
                       repair_action, is_stuck, internal_status, external_status,
                       trace_refs
                FROM settlement_reconciliation_results
                WHERE workflow_id = $1
                """,
                workflow_id,
            )
            return [_row_to_recon_result(r) for r in rows]
        except Exception as exc:
            log.error(
                "settlement_persistence_load_recon_error",
                workflow_id=workflow_id,
                error=str(exc),
            )
            return []


# ---------------------------------------------------------------------------
# Row mappers
# ---------------------------------------------------------------------------

def _row_to_event(row: Any) -> SettlementEvent:
    return SettlementEvent(
        event_id=row["event_id"],
        event_type=row["event_type"],
        workflow_id=row["workflow_id"],
        settlement_id=row["settlement_id"],
        payload=row["payload"] or {},
        occurred_at=row["occurred_at"],
    )


def _row_to_retry_record(row: Any) -> RetryAttemptRecord:
    return RetryAttemptRecord(
        workflow_id=row["workflow_id"],
        attempt_number=row["attempt_number"],
        outcome=row["outcome"],
        settlement_id=row["settlement_id"],
        blocked_reason=row["blocked_reason"],
        delay_before_next_s=row["delay_before_next_s"],
        attempted_at=row["attempted_at"],
        trace_refs=row["trace_refs"] or {},
    )


def _row_to_recon_result(row: Any) -> ReconciliationResult:
    return ReconciliationResult(
        workflow_id=row["workflow_id"],
        settlement_id=row["settlement_id"],
        outcome=row["outcome"],
        mismatch_reason=row["mismatch_reason"],
        repair_action=row["repair_action"],
        is_stuck=row["is_stuck"],
        internal_status=row["internal_status"],
        external_status=row["external_status"],
        trace_refs=row["trace_refs"] or {},
    )
