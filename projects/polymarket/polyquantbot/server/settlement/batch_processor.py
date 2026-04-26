"""Batch Processor — Priority 7 section 45.

Sequential async processing (no concurrent settlements — capital safety
constraint: concurrent settlements on the same wallet would require
distributed locking on the balance).

Observability: structured log per batch with batch_id, size, total_usd,
partial flag, duration_ms, and failed_workflow_ids.
"""
from __future__ import annotations

import time
from typing import Any

import structlog

from projects.polymarket.polyquantbot.platform.execution.fund_settlement import (
    FundSettlementExecutionInput,
    FundSettlementPolicyInput,
)

from .schemas import (
    BATCH_MAX_SIZE,
    BATCH_STATUS_COMPLETED,
    BATCH_STATUS_FAILED,
    BATCH_STATUS_PARTIAL,
    SETTLEMENT_STATUS_COMPLETED,
    SETTLEMENT_STATUS_SIMULATED,
    BatchItemResult,
    SettlementBatchRequest,
    SettlementBatchResult,
    _utc_now,
)
from .settlement_workflow import SettlementWorkflowEngine

log = structlog.get_logger(__name__)


class BatchProcessor:
    """Async, stateless batch coordinator.

    Items are processed sequentially — never concurrently — to avoid
    competing balance writes on the same wallet.
    """

    def __init__(self, *, workflow_engine: SettlementWorkflowEngine) -> None:
        self._engine = workflow_engine

    async def process_batch(
        self,
        batch_request: SettlementBatchRequest,
        execution_inputs: dict[str, FundSettlementExecutionInput],
        policy_inputs: dict[str, FundSettlementPolicyInput],
    ) -> SettlementBatchResult:
        """Process all items in the batch sequentially."""
        bound = log.bind(
            batch_id=batch_request.batch_id,
            total_items=len(batch_request.items),
            mode=batch_request.mode,
        )

        if len(batch_request.items) > BATCH_MAX_SIZE:
            bound.warning(
                "batch_processor_size_exceeded",
                max_size=BATCH_MAX_SIZE,
                actual=len(batch_request.items),
            )
            return SettlementBatchResult(
                batch_id=batch_request.batch_id,
                batch_status=BATCH_STATUS_FAILED,
                total_items=len(batch_request.items),
                completed_count=0,
                failed_count=len(batch_request.items),
                blocked_count=0,
                partial=False,
                item_results=(),
                trace_refs={"blocked_reason": "batch_size_exceeded", "max": BATCH_MAX_SIZE},
            )

        bound.info("batch_processor_start")
        t0 = time.monotonic()
        item_results: list[BatchItemResult] = []

        for item in batch_request.items:
            exec_input = execution_inputs.get(item.workflow_id)
            pol_input = policy_inputs.get(item.workflow_id)

            if exec_input is None or pol_input is None:
                item_results.append(BatchItemResult(
                    workflow_id=item.workflow_id,
                    status="FAILED",
                    success=False,
                    blocked_reason="missing_inputs",
                ))
                continue

            try:
                result = await self._engine.execute(item, exec_input, pol_input)
                item_results.append(BatchItemResult(
                    workflow_id=item.workflow_id,
                    status=result.status,
                    success=result.success,
                    settlement_id=result.settlement_id,
                    blocked_reason=result.blocked_reason,
                    simulated=result.simulated,
                ))
            except Exception as exc:
                log.error(
                    "batch_processor_item_error",
                    workflow_id=item.workflow_id,
                    error=str(exc),
                )
                item_results.append(BatchItemResult(
                    workflow_id=item.workflow_id,
                    status="FAILED",
                    success=False,
                    blocked_reason=f"processor_error: {exc}",
                ))

        result_tuple = tuple(item_results)
        batch_result = _build_batch_result(batch_request.batch_id, result_tuple, batch_request.mode)
        duration_ms = int((time.monotonic() - t0) * 1000)

        bound.info(
            "batch_processor_done",
            batch_status=batch_result.batch_status,
            completed=batch_result.completed_count,
            failed=batch_result.failed_count,
            partial=batch_result.partial,
            duration_ms=duration_ms,
        )
        return batch_result

    async def process_partial(
        self,
        batch_result: SettlementBatchResult,
        execution_inputs: dict[str, FundSettlementExecutionInput],
        policy_inputs: dict[str, FundSettlementPolicyInput],
    ) -> SettlementBatchResult:
        """Re-process only the failed/blocked items from a prior batch result."""
        failed_items = tuple(
            r for r in batch_result.item_results if not r.success
        )
        if not failed_items:
            return batch_result

        from .schemas import SettlementBatchRequest, _utc_now, new_batch_id

        partial_request = SettlementBatchRequest(
            batch_id=batch_result.batch_id,
            items=_failed_items_as_requests(failed_items, execution_inputs, policy_inputs, batch_result),
            mode=batch_result.mode,
            queued_at=_utc_now(),
        )

        return await self.process_batch(
            partial_request,
            execution_inputs,
            policy_inputs,
        )

    @staticmethod
    def classify_batch_status(result: SettlementBatchResult) -> str:
        if result.completed_count > 0 and result.failed_count > 0:
            return BATCH_STATUS_PARTIAL
        if result.failed_count == result.total_items:
            return BATCH_STATUS_FAILED
        return BATCH_STATUS_COMPLETED


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_batch_result(
    batch_id: str,
    item_results: tuple[BatchItemResult, ...],
    mode: str = "paper",
) -> SettlementBatchResult:
    completed = sum(1 for r in item_results if r.success)
    failed = sum(1 for r in item_results if not r.success and r.blocked_reason is None)
    blocked = sum(1 for r in item_results if not r.success and r.blocked_reason is not None)
    total = len(item_results)
    partial = completed > 0 and (failed + blocked) > 0

    if partial:
        status = BATCH_STATUS_PARTIAL
    elif completed == total:
        status = BATCH_STATUS_COMPLETED
    else:
        status = BATCH_STATUS_FAILED

    return SettlementBatchResult(
        batch_id=batch_id,
        batch_status=status,
        total_items=total,
        completed_count=completed,
        failed_count=failed + blocked,
        blocked_count=blocked,
        partial=partial,
        item_results=item_results,
        mode=mode,
    )


def _failed_items_as_requests(
    failed_items: tuple[BatchItemResult, ...],
    execution_inputs: dict,
    policy_inputs: dict,
    original_batch: SettlementBatchResult,
) -> tuple:
    from .schemas import SettlementWorkflowRequest, _utc_now

    requests = []
    for item in failed_items:
        pol = policy_inputs.get(item.workflow_id)
        if pol is None:
            continue
        requests.append(SettlementWorkflowRequest(
            workflow_id=item.workflow_id,
            wallet_id=pol.wallet_id,
            amount=pol.amount,
            currency=pol.currency,
            method=pol.settlement_method,
            mode=original_batch.mode,
            settlement_id=item.settlement_id,
        ))
    return tuple(requests)
