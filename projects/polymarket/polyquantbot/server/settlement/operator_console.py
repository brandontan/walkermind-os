"""Operator Console — Priority 7 section 47.

Read-only status surfaces plus admin intervention paths.
Receives all data pre-loaded from the service layer — never touches storage.
Every admin intervention is logged for audit.

Allowed admin actions:
  force_cancel   — move any non-terminal workflow to CANCELLED
  force_retry    — re-open a FAILED workflow as PENDING (blocked on fatal)
  force_complete — mark a workflow COMPLETED (blocked if already terminal)
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from .schemas import (
    BATCH_STATUS_FAILED,
    BATCH_STATUS_PARTIAL,
    RETRY_OUTCOME_FATAL,
    SETTLEMENT_STATUS_BLOCKED,
    SETTLEMENT_STATUS_CANCELLED,
    SETTLEMENT_STATUS_COMPLETED,
    SETTLEMENT_STATUS_FAILED,
    SETTLEMENT_STATUS_PENDING,
    AdminInterventionRequest,
    AdminInterventionResult,
    FailedBatchView,
    RetryAttemptRecord,
    RetryPolicy,
    RetryStatusView,
    SettlementBatchResult,
    SettlementStatusView,
    SettlementWorkflowResult,
    _utc_now,
)

log = structlog.get_logger(__name__)

_TERMINAL_STATUSES = frozenset({
    SETTLEMENT_STATUS_COMPLETED,
    SETTLEMENT_STATUS_CANCELLED,
})

_FORCE_RETRY_BLOCKED_STATUSES = frozenset({
    SETTLEMENT_STATUS_COMPLETED,
    SETTLEMENT_STATUS_CANCELLED,
})


class OperatorConsole:
    """Async read-only status surfaces and admin intervention paths.

    Injected alert_policy is used to classify events emitted by interventions.
    """

    def __init__(self, *, alert_policy: Any) -> None:
        self._alert_policy = alert_policy

    async def get_settlement_status(
        self,
        workflow_id: str,
        workflow_result: SettlementWorkflowResult | None,
        retry_history: Sequence[RetryAttemptRecord],
        request_created_at: datetime | None = None,
    ) -> SettlementStatusView:
        if workflow_result is None:
            return SettlementStatusView(
                workflow_id=workflow_id,
                status="NOT_FOUND",
                amount=0.0,
                currency="USD",
                wallet_id="",
                mode="paper",
                retry_attempt_count=0,
                created_at=_utc_now(),
                updated_at=_utc_now(),
            )

        now = _utc_now()
        return SettlementStatusView(
            workflow_id=workflow_id,
            settlement_id=workflow_result.settlement_id,
            status=workflow_result.status,
            amount=workflow_result.fund_result.amount if workflow_result.fund_result else 0.0,
            currency=workflow_result.fund_result.currency if workflow_result.fund_result else "USD",
            wallet_id=workflow_result.fund_result.wallet_id if workflow_result.fund_result else "",
            mode="live" if (workflow_result.fund_result and not workflow_result.fund_result.simulated) else "paper",
            retry_attempt_count=len(retry_history),
            last_blocked_reason=workflow_result.blocked_reason,
            created_at=request_created_at or now,
            updated_at=workflow_result.completed_at or now,
        )

    async def get_retry_status(
        self,
        workflow_id: str,
        retry_history: Sequence[RetryAttemptRecord],
        policy: RetryPolicy,
    ) -> RetryStatusView:
        if not retry_history:
            return RetryStatusView(
                workflow_id=workflow_id,
                current_attempt=0,
                max_attempts=policy.max_attempts,
                last_outcome="none",
                is_exhausted=False,
                is_fatal=False,
            )

        last = retry_history[-1]
        is_exhausted = len(retry_history) >= policy.max_attempts
        is_fatal = last.outcome == RETRY_OUTCOME_FATAL

        next_retry_at: datetime | None = None
        if last.delay_before_next_s is not None and not is_exhausted and not is_fatal:
            next_retry_at = last.attempted_at + timedelta(seconds=last.delay_before_next_s)

        return RetryStatusView(
            workflow_id=workflow_id,
            current_attempt=len(retry_history),
            max_attempts=policy.max_attempts,
            last_outcome=last.outcome,
            is_exhausted=is_exhausted,
            is_fatal=is_fatal,
            next_retry_at=next_retry_at,
        )

    async def get_failed_batches(
        self,
        batch_results: Sequence[SettlementBatchResult],
    ) -> Sequence[FailedBatchView]:
        failed = []
        for br in batch_results:
            if br.batch_status in (BATCH_STATUS_FAILED, BATCH_STATUS_PARTIAL):
                failed_ids = tuple(
                    r.workflow_id for r in br.item_results if not r.success
                )
                failed.append(FailedBatchView(
                    batch_id=br.batch_id,
                    batch_status=br.batch_status,
                    total_items=br.total_items,
                    failed_count=br.failed_count,
                    queued_at=br.processed_at,
                    failed_workflow_ids=failed_ids,
                ))
        return failed

    async def apply_admin_intervention(
        self,
        intervention: AdminInterventionRequest,
        current_result: SettlementWorkflowResult,
    ) -> AdminInterventionResult:
        bound = log.bind(
            workflow_id=intervention.workflow_id,
            action=intervention.action,
            admin_user_id=intervention.admin_user_id,
        )
        bound.info("operator_console_intervention_start")

        action = intervention.action
        prev_status = current_result.status

        if action == "force_cancel":
            if prev_status in _TERMINAL_STATUSES:
                bound.warning("operator_console_intervention_blocked_terminal")
                return AdminInterventionResult(
                    workflow_id=intervention.workflow_id,
                    action=action,
                    success=False,
                    previous_status=prev_status,
                    blocked_reason="already_terminal",
                )
            bound.info("operator_console_force_cancel_applied")
            return AdminInterventionResult(
                workflow_id=intervention.workflow_id,
                action=action,
                success=True,
                previous_status=prev_status,
                new_status=SETTLEMENT_STATUS_CANCELLED,
            )

        if action == "force_retry":
            if prev_status in _FORCE_RETRY_BLOCKED_STATUSES:
                bound.warning("operator_console_intervention_blocked_terminal_retry")
                return AdminInterventionResult(
                    workflow_id=intervention.workflow_id,
                    action=action,
                    success=False,
                    previous_status=prev_status,
                    blocked_reason="already_terminal",
                )
            from .retry_engine import RetryEngine
            if RetryEngine.is_fatal(current_result.blocked_reason):
                bound.warning(
                    "operator_console_intervention_blocked_fatal",
                    blocked_reason=current_result.blocked_reason,
                )
                return AdminInterventionResult(
                    workflow_id=intervention.workflow_id,
                    action=action,
                    success=False,
                    previous_status=prev_status,
                    blocked_reason="fatal_block_no_retry",
                )
            bound.info("operator_console_force_retry_applied")
            return AdminInterventionResult(
                workflow_id=intervention.workflow_id,
                action=action,
                success=True,
                previous_status=prev_status,
                new_status=SETTLEMENT_STATUS_PENDING,
            )

        if action == "force_complete":
            if prev_status in _TERMINAL_STATUSES:
                bound.warning("operator_console_intervention_blocked_already_complete")
                return AdminInterventionResult(
                    workflow_id=intervention.workflow_id,
                    action=action,
                    success=False,
                    previous_status=prev_status,
                    blocked_reason="already_terminal",
                )
            bound.info("operator_console_force_complete_applied")
            return AdminInterventionResult(
                workflow_id=intervention.workflow_id,
                action=action,
                success=True,
                previous_status=prev_status,
                new_status=SETTLEMENT_STATUS_COMPLETED,
            )

        bound.warning("operator_console_unknown_action", action=action)
        return AdminInterventionResult(
            workflow_id=intervention.workflow_id,
            action=action,
            success=False,
            previous_status=prev_status,
            blocked_reason=f"unknown_action: {action}",
        )
