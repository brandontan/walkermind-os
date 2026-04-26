"""Priority 7 — Operator Console — Tests.

Test IDs: ST-29 .. ST-32

Coverage:
  ST-29  get_settlement_status returns correct view from pre-loaded result
  ST-30  get_retry_status shows is_exhausted when attempts == max
  ST-30b get_retry_status shows is_fatal when last outcome is FATAL
  ST-31  get_failed_batches filters only FAILED and PARTIAL batches
  ST-32  force_cancel succeeds on non-terminal workflow
  ST-32b force_cancel blocked on already-terminal (COMPLETED) workflow
  ST-32c force_retry blocked on fatal workflow
  ST-32d force_retry succeeds on retryable FAILED workflow
  ST-32e force_complete succeeds on non-terminal workflow
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from projects.polymarket.polyquantbot.server.settlement.operator_console import (
    OperatorConsole,
)
from projects.polymarket.polyquantbot.server.settlement.schemas import (
    BATCH_STATUS_COMPLETED,
    BATCH_STATUS_FAILED,
    BATCH_STATUS_PARTIAL,
    RETRY_OUTCOME_EXHAUSTED,
    RETRY_OUTCOME_FATAL,
    SETTLEMENT_STATUS_BLOCKED,
    SETTLEMENT_STATUS_CANCELLED,
    SETTLEMENT_STATUS_COMPLETED,
    SETTLEMENT_STATUS_FAILED,
    SETTLEMENT_STATUS_PROCESSING,
    AdminInterventionRequest,
    BatchItemResult,
    RetryAttemptRecord,
    RetryPolicy,
    SettlementBatchResult,
    SettlementWorkflowResult,
    _utc_now,
)
from projects.polymarket.polyquantbot.platform.execution.fund_settlement import (
    FUND_SETTLEMENT_BLOCK_CAPITAL_NOT_AUTHORIZED,
)


# ── Stub alert policy (no-op) ──────────────────────────────────────────────────

class _NullAlertPolicy:
    pass


_console = OperatorConsole(alert_policy=_NullAlertPolicy())
_now = _utc_now()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _wf_result(
    workflow_id: str = "stl_aaa",
    status: str = SETTLEMENT_STATUS_COMPLETED,
    success: bool = True,
    blocked_reason: str | None = None,
    simulated: bool = False,
) -> SettlementWorkflowResult:
    return SettlementWorkflowResult(
        workflow_id=workflow_id,
        status=status,
        success=success,
        blocked_reason=blocked_reason,
        simulated=simulated,
    )


def _retry_record(
    workflow_id: str = "stl_aaa",
    attempt_number: int = 1,
    outcome: str = RETRY_OUTCOME_EXHAUSTED,
    delay: float | None = None,
) -> RetryAttemptRecord:
    return RetryAttemptRecord(
        workflow_id=workflow_id,
        attempt_number=attempt_number,
        outcome=outcome,
        delay_before_next_s=delay,
    )


def _batch_result(
    batch_id: str = "bat_x",
    status: str = BATCH_STATUS_FAILED,
    total: int = 2,
    failed: int = 2,
) -> SettlementBatchResult:
    failed_items = tuple(
        BatchItemResult(workflow_id=f"stl_{i}", status=SETTLEMENT_STATUS_FAILED, success=False)
        for i in range(failed)
    )
    ok_items = tuple(
        BatchItemResult(workflow_id=f"stl_ok_{i}", status=SETTLEMENT_STATUS_COMPLETED, success=True)
        for i in range(total - failed)
    )
    return SettlementBatchResult(
        batch_id=batch_id,
        batch_status=status,
        total_items=total,
        completed_count=total - failed,
        failed_count=failed,
        blocked_count=0,
        partial=(status == BATCH_STATUS_PARTIAL),
        item_results=failed_items + ok_items,
    )


def _intervention(
    workflow_id: str = "stl_aaa",
    action: str = "force_cancel",
    admin: str = "admin_001",
) -> AdminInterventionRequest:
    return AdminInterventionRequest(
        workflow_id=workflow_id,
        action=action,
        admin_user_id=admin,
        reason="test",
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_st_29_settlement_status_view_populated():
    """ST-29: get_settlement_status returns a SettlementStatusView with correct fields."""
    result = _wf_result(workflow_id="stl_aaa", status=SETTLEMENT_STATUS_COMPLETED)
    view = await _console.get_settlement_status("stl_aaa", result, [], _now)

    assert view.workflow_id == "stl_aaa"
    assert view.status == SETTLEMENT_STATUS_COMPLETED
    assert view.retry_attempt_count == 0


@pytest.mark.asyncio
async def test_st_29b_settlement_status_not_found_when_no_result():
    """ST-29b: get_settlement_status returns NOT_FOUND when workflow_result is None."""
    view = await _console.get_settlement_status("stl_missing", None, [])
    assert view.status == "NOT_FOUND"


@pytest.mark.asyncio
async def test_st_30_retry_status_exhausted_flag():
    """ST-30: is_exhausted is True when attempt count equals max_attempts."""
    policy = RetryPolicy(max_attempts=3)
    history = [
        _retry_record(attempt_number=1, outcome=RETRY_OUTCOME_EXHAUSTED),
        _retry_record(attempt_number=2, outcome=RETRY_OUTCOME_EXHAUSTED),
        _retry_record(attempt_number=3, outcome=RETRY_OUTCOME_EXHAUSTED),
    ]
    view = await _console.get_retry_status("stl_aaa", history, policy)

    assert view.is_exhausted is True
    assert view.current_attempt == 3
    assert view.max_attempts == 3


@pytest.mark.asyncio
async def test_st_30b_retry_status_fatal_flag():
    """ST-30b: is_fatal is True when last record has FATAL outcome."""
    policy = RetryPolicy(max_attempts=5)
    history = [_retry_record(attempt_number=1, outcome=RETRY_OUTCOME_FATAL)]
    view = await _console.get_retry_status("stl_aaa", history, policy)

    assert view.is_fatal is True
    assert view.is_exhausted is False


@pytest.mark.asyncio
async def test_st_30c_retry_status_empty_history():
    """ST-30c: Empty retry history returns zero attempt count and not exhausted."""
    view = await _console.get_retry_status("stl_aaa", [], RetryPolicy())
    assert view.current_attempt == 0
    assert view.is_exhausted is False
    assert view.is_fatal is False


@pytest.mark.asyncio
async def test_st_31_failed_batches_filters_correctly():
    """ST-31: get_failed_batches returns only FAILED and PARTIAL batches."""
    batches = [
        _batch_result("bat_ok",      status=BATCH_STATUS_COMPLETED, total=2, failed=0),
        _batch_result("bat_fail",    status=BATCH_STATUS_FAILED,    total=2, failed=2),
        _batch_result("bat_partial", status=BATCH_STATUS_PARTIAL,   total=2, failed=1),
    ]
    views = await _console.get_failed_batches(batches)
    batch_ids = {v.batch_id for v in views}

    assert "bat_fail"    in batch_ids
    assert "bat_partial" in batch_ids
    assert "bat_ok" not in batch_ids


@pytest.mark.asyncio
async def test_st_32_force_cancel_succeeds_on_processing():
    """ST-32: force_cancel returns success=True for a PROCESSING workflow."""
    current = _wf_result(status=SETTLEMENT_STATUS_PROCESSING, success=False)
    result = await _console.apply_admin_intervention(
        _intervention(action="force_cancel"), current
    )
    assert result.success is True
    assert result.new_status == SETTLEMENT_STATUS_CANCELLED
    assert result.previous_status == SETTLEMENT_STATUS_PROCESSING


@pytest.mark.asyncio
async def test_st_32b_force_cancel_blocked_on_completed():
    """ST-32b: force_cancel returns success=False when workflow is already COMPLETED."""
    current = _wf_result(status=SETTLEMENT_STATUS_COMPLETED, success=True)
    result = await _console.apply_admin_intervention(
        _intervention(action="force_cancel"), current
    )
    assert result.success is False
    assert result.blocked_reason == "already_terminal"


@pytest.mark.asyncio
async def test_st_32c_force_retry_blocked_on_fatal():
    """ST-32c: force_retry returns success=False when blocked_reason is fatal."""
    current = _wf_result(
        status=SETTLEMENT_STATUS_FAILED,
        success=False,
        blocked_reason=FUND_SETTLEMENT_BLOCK_CAPITAL_NOT_AUTHORIZED,
    )
    result = await _console.apply_admin_intervention(
        _intervention(action="force_retry"), current
    )
    assert result.success is False
    assert result.blocked_reason == "fatal_block_no_retry"


@pytest.mark.asyncio
async def test_st_32d_force_retry_succeeds_on_retryable_failed():
    """ST-32d: force_retry succeeds when workflow is FAILED with retryable reason."""
    current = _wf_result(
        status=SETTLEMENT_STATUS_FAILED,
        success=False,
        blocked_reason="insufficient_balance",
    )
    result = await _console.apply_admin_intervention(
        _intervention(action="force_retry"), current
    )
    assert result.success is True
    from projects.polymarket.polyquantbot.server.settlement.schemas import SETTLEMENT_STATUS_PENDING
    assert result.new_status == SETTLEMENT_STATUS_PENDING


@pytest.mark.asyncio
async def test_st_32e_force_complete_succeeds_on_non_terminal():
    """ST-32e: force_complete transitions BLOCKED workflow to COMPLETED."""
    current = _wf_result(
        status=SETTLEMENT_STATUS_BLOCKED,
        success=False,
        blocked_reason="monitoring_evaluation_required",
    )
    result = await _console.apply_admin_intervention(
        _intervention(action="force_complete"), current
    )
    assert result.success is True
    assert result.new_status == SETTLEMENT_STATUS_COMPLETED
