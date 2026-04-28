from __future__ import annotations

import asyncio
import structlog
from typing import Any, Sequence

from projects.polymarket.polyquantbot.server.settlement.schemas import (
    SETTLEMENT_EVENT_CANCELLED,
    SETTLEMENT_EVENT_COMPLETED,
    SETTLEMENT_EVENT_CREATED,
    SETTLEMENT_EVENT_FAILED,
    SETTLEMENT_EVENT_PROCESSING,
    SETTLEMENT_EVENT_RETRY_ATTEMPT,
    SETTLEMENT_EVENT_RETRY_QUEUED,
    AdminInterventionRequest,
    AdminInterventionResult,
    FailedBatchView,
    RetryPolicy,
    RetryStatusView,
    SettlementEvent,
    SettlementStatusView,
    SettlementWorkflowResult,
)
from projects.polymarket.polyquantbot.server.settlement.operator_console import OperatorConsole
from projects.polymarket.polyquantbot.server.settlement.settlement_persistence import SettlementPersistence

log = structlog.get_logger(__name__)

_EVENT_TYPE_TO_STATUS: dict[str, str] = {
    SETTLEMENT_EVENT_COMPLETED:    "COMPLETED",
    SETTLEMENT_EVENT_FAILED:       "FAILED",
    SETTLEMENT_EVENT_CANCELLED:    "CANCELLED",
    SETTLEMENT_EVENT_PROCESSING:   "PROCESSING",
    SETTLEMENT_EVENT_RETRY_QUEUED: "RETRY_QUEUED",
    SETTLEMENT_EVENT_RETRY_ATTEMPT: "RETRYING",
    SETTLEMENT_EVENT_CREATED:      "PENDING",
}

_TERMINAL_STATUSES = frozenset({"COMPLETED", "FAILED", "CANCELLED"})


def _build_result_from_events(
    workflow_id: str,
    events: list[SettlementEvent],
) -> SettlementWorkflowResult | None:
    if not events:
        return None
    latest = max(events, key=lambda e: e.occurred_at)
    status = _EVENT_TYPE_TO_STATUS.get(latest.event_type, "UNKNOWN")
    success = status == "COMPLETED"
    completed_at = latest.occurred_at if status in _TERMINAL_STATUSES else None
    return SettlementWorkflowResult(
        workflow_id=workflow_id,
        status=status,
        success=success,
        settlement_id=latest.settlement_id,
        blocked_reason=latest.payload.get("blocked_reason"),
        completed_at=completed_at,
    )


class SettlementOperatorService:
    """Service layer: loads from SettlementPersistence, delegates to OperatorConsole."""

    def __init__(
        self,
        *,
        persistence: SettlementPersistence,
        console: OperatorConsole,
    ) -> None:
        self._persistence = persistence
        self._console = console
        self._default_retry_policy = RetryPolicy()

    async def get_settlement_status(self, workflow_id: str) -> SettlementStatusView:
        bound = log.bind(workflow_id=workflow_id)
        bound.info("settlement_operator_service_status_request")
        try:
            events, retry_history = await asyncio.gather(
                self._persistence.load_events_for_workflow(workflow_id),
                self._persistence.load_retry_history(workflow_id),
            )
            workflow_result = _build_result_from_events(workflow_id, events)
            request_created_at = min((e.occurred_at for e in events), default=None)
            return await self._console.get_settlement_status(
                workflow_id, workflow_result, retry_history, request_created_at
            )
        except Exception:
            bound.exception("settlement_operator_service_status_error")
            raise

    async def get_retry_status(self, workflow_id: str) -> RetryStatusView:
        bound = log.bind(workflow_id=workflow_id)
        bound.info("settlement_operator_service_retry_request")
        try:
            retry_history = await self._persistence.load_retry_history(workflow_id)
            return await self._console.get_retry_status(
                workflow_id, retry_history, self._default_retry_policy
            )
        except Exception:
            bound.exception("settlement_operator_service_retry_error")
            raise

    async def get_failed_batches(self) -> Sequence[FailedBatchView]:
        # Batch results are not persisted in the current persistence layer;
        # returns empty until a batch persistence lane is added.
        log.info("settlement_operator_service_failed_batches_request")
        return await self._console.get_failed_batches([])

    async def apply_admin_intervention(
        self,
        intervention: AdminInterventionRequest,
    ) -> AdminInterventionResult | None:
        bound = log.bind(
            workflow_id=intervention.workflow_id,
            action=intervention.action,
        )
        bound.info("settlement_operator_service_intervention_request")
        try:
            events = await self._persistence.load_events_for_workflow(
                intervention.workflow_id
            )
            workflow_result = _build_result_from_events(intervention.workflow_id, events)
            if workflow_result is None:
                bound.warning("settlement_operator_service_intervention_not_found")
                return None
            return await self._console.apply_admin_intervention(
                intervention, workflow_result
            )
        except Exception:
            bound.exception("settlement_operator_service_intervention_error")
            raise
