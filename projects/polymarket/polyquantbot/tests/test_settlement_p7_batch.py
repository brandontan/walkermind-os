"""Priority 7 — Batch Processor — Tests.

Test IDs: ST-17 .. ST-23

Coverage:
  ST-17  Single item batch succeeds end-to-end
  ST-18  All items succeed -> COMPLETED status
  ST-19  All items fail -> FAILED status
  ST-20  Mixed results -> PARTIAL status + partial flag
  ST-21  Batch exceeding BATCH_MAX_SIZE returns FAILED immediately
  ST-22  process_partial re-runs only the failed items, not all items
  ST-23  classify_batch_status static method is correct for all cases
"""
from __future__ import annotations

import pytest

from projects.polymarket.polyquantbot.server.settlement.batch_processor import (
    BatchProcessor,
    _build_batch_result,
)
from projects.polymarket.polyquantbot.server.settlement.schemas import (
    BATCH_MAX_SIZE,
    BATCH_STATUS_COMPLETED,
    BATCH_STATUS_FAILED,
    BATCH_STATUS_PARTIAL,
    BatchItemResult,
    SettlementBatchRequest,
    SettlementBatchResult,
    SettlementWorkflowRequest,
    SettlementWorkflowResult,
    SETTLEMENT_STATUS_COMPLETED,
    SETTLEMENT_STATUS_BLOCKED,
    SETTLEMENT_STATUS_FAILED,
    _utc_now,
)
from projects.polymarket.polyquantbot.server.settlement.settlement_workflow import (
    SettlementWorkflowPolicy,
)


# ── Stubs ─────────────────────────────────────────────────────────────────────

def _req(wallet_id: str = "wlc_001", workflow_id: str | None = None) -> SettlementWorkflowRequest:
    r = SettlementWorkflowRequest(
        wallet_id=wallet_id,
        amount=50.0,
        currency="USDC",
        method="polygon",
        mode="paper",
    )
    if workflow_id is not None:
        # Use object.__setattr__ only during construction stub — frozen after
        object.__setattr__(r, "workflow_id", workflow_id)
    return r


def _workflow_result(
    workflow_id: str,
    success: bool = True,
    status: str = SETTLEMENT_STATUS_COMPLETED,
    blocked_reason: str | None = None,
) -> SettlementWorkflowResult:
    return SettlementWorkflowResult(
        workflow_id=workflow_id,
        status=status,
        success=success,
        blocked_reason=blocked_reason,
    )


class StubWorkflowEngine:
    """Returns pre-configured results keyed by workflow_id."""

    def __init__(self, results: dict[str, SettlementWorkflowResult]) -> None:
        self._results = results

    async def execute(self, request, execution_input, policy_input) -> SettlementWorkflowResult:
        wid = request.workflow_id
        if wid in self._results:
            return self._results[wid]
        return _workflow_result(wid, success=False, status=SETTLEMENT_STATUS_FAILED)


def _make_batch(
    workflow_ids: list[str],
    mode: str = "paper",
) -> tuple[SettlementBatchRequest, dict, dict]:
    items = tuple(_req(workflow_id=wid) for wid in workflow_ids)
    batch = SettlementBatchRequest(items=items, mode=mode)
    exec_inputs = {wid: object() for wid in workflow_ids}
    pol_inputs = {wid: object() for wid in workflow_ids}
    return batch, exec_inputs, pol_inputs


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_st_17_single_item_batch_succeeds():
    """ST-17: A single-item batch with a successful result returns COMPLETED."""
    wid = "stl_single"
    engine = StubWorkflowEngine({wid: _workflow_result(wid, success=True)})
    processor = BatchProcessor(workflow_engine=engine)
    batch, exec_in, pol_in = _make_batch([wid])

    result = await processor.process_batch(batch, exec_in, pol_in)

    assert result.batch_status == BATCH_STATUS_COMPLETED
    assert result.completed_count == 1
    assert result.failed_count == 0
    assert result.partial is False
    assert len(result.item_results) == 1
    assert result.item_results[0].success is True


@pytest.mark.asyncio
async def test_st_18_all_succeed_returns_completed():
    """ST-18: All items succeed -> batch_status=COMPLETED."""
    wids = ["stl_a", "stl_b", "stl_c"]
    results = {wid: _workflow_result(wid, success=True) for wid in wids}
    processor = BatchProcessor(workflow_engine=StubWorkflowEngine(results))
    batch, exec_in, pol_in = _make_batch(wids)

    result = await processor.process_batch(batch, exec_in, pol_in)

    assert result.batch_status == BATCH_STATUS_COMPLETED
    assert result.completed_count == 3
    assert result.failed_count == 0
    assert result.partial is False


@pytest.mark.asyncio
async def test_st_19_all_fail_returns_failed():
    """ST-19: All items fail -> batch_status=FAILED."""
    wids = ["stl_x", "stl_y"]
    results = {
        wid: _workflow_result(wid, success=False, status=SETTLEMENT_STATUS_FAILED)
        for wid in wids
    }
    processor = BatchProcessor(workflow_engine=StubWorkflowEngine(results))
    batch, exec_in, pol_in = _make_batch(wids)

    result = await processor.process_batch(batch, exec_in, pol_in)

    assert result.batch_status == BATCH_STATUS_FAILED
    assert result.completed_count == 0
    assert result.failed_count == 2
    assert result.partial is False


@pytest.mark.asyncio
async def test_st_20_mixed_returns_partial():
    """ST-20: Mixed success/failure -> PARTIAL status and partial=True."""
    wids = ["stl_ok", "stl_bad"]
    results = {
        "stl_ok":  _workflow_result("stl_ok",  success=True),
        "stl_bad": _workflow_result("stl_bad", success=False, status=SETTLEMENT_STATUS_FAILED),
    }
    processor = BatchProcessor(workflow_engine=StubWorkflowEngine(results))
    batch, exec_in, pol_in = _make_batch(wids)

    result = await processor.process_batch(batch, exec_in, pol_in)

    assert result.batch_status == BATCH_STATUS_PARTIAL
    assert result.partial is True
    assert result.completed_count == 1
    assert result.failed_count == 1


@pytest.mark.asyncio
async def test_st_21_batch_size_exceeded_returns_failed_immediately():
    """ST-21: Batch with more than BATCH_MAX_SIZE items returns FAILED without processing."""
    wids = [f"stl_{i}" for i in range(BATCH_MAX_SIZE + 1)]
    processor = BatchProcessor(workflow_engine=StubWorkflowEngine({}))
    batch, exec_in, pol_in = _make_batch(wids)

    result = await processor.process_batch(batch, exec_in, pol_in)

    assert result.batch_status == BATCH_STATUS_FAILED
    assert result.completed_count == 0
    assert result.item_results == ()


@pytest.mark.asyncio
async def test_st_22_process_partial_reruns_only_failed_items():
    """ST-22: process_partial only re-processes items that previously failed."""
    call_log: list[str] = []

    class TrackingEngine:
        async def execute(self, request, exec_input, pol_input) -> SettlementWorkflowResult:
            call_log.append(request.workflow_id)
            return _workflow_result(request.workflow_id, success=True)

    processor = BatchProcessor(workflow_engine=TrackingEngine())

    # Build a prior partial batch result: stl_ok succeeded, stl_bad failed
    prior = SettlementBatchResult(
        batch_id="bat_prior",
        batch_status=BATCH_STATUS_PARTIAL,
        total_items=2,
        completed_count=1,
        failed_count=1,
        blocked_count=0,
        partial=True,
        item_results=(
            BatchItemResult(workflow_id="stl_ok",  status=SETTLEMENT_STATUS_COMPLETED, success=True),
            BatchItemResult(workflow_id="stl_bad", status=SETTLEMENT_STATUS_FAILED,    success=False,
                            blocked_reason="insufficient_balance"),
        ),
    )

    exec_in = {"stl_ok": object(), "stl_bad": object()}
    pol_in = {
        "stl_ok":  _make_stub_policy("stl_ok"),
        "stl_bad": _make_stub_policy("stl_bad"),
    }

    await processor.process_partial(prior, exec_in, pol_in)

    # Only the failed item should have been re-processed
    assert "stl_bad" in call_log
    assert "stl_ok" not in call_log


def test_st_23_classify_batch_status_all_cases():
    """ST-23: classify_batch_status static method covers all three outcomes."""
    def _result(completed: int, failed: int, total: int) -> SettlementBatchResult:
        return SettlementBatchResult(
            batch_id="bat_x",
            batch_status="",  # not used by classify
            total_items=total,
            completed_count=completed,
            failed_count=failed,
            blocked_count=0,
            partial=(completed > 0 and failed > 0),
            item_results=(),
        )

    assert BatchProcessor.classify_batch_status(_result(3, 0, 3)) == BATCH_STATUS_COMPLETED
    assert BatchProcessor.classify_batch_status(_result(0, 3, 3)) == BATCH_STATUS_FAILED
    assert BatchProcessor.classify_batch_status(_result(2, 1, 3)) == BATCH_STATUS_PARTIAL


# ── Internal helper for ST-22 ──────────────────────────────────────────────────

class _StubPolicyInput:
    """Minimal policy_input stub with wallet_id, amount, currency, settlement_method."""
    def __init__(self, wallet_id: str) -> None:
        self.wallet_id = wallet_id
        self.amount = 50.0
        self.currency = "USDC"
        self.settlement_method = "polygon"


def _make_stub_policy(wallet_id: str) -> _StubPolicyInput:
    return _StubPolicyInput(wallet_id)
