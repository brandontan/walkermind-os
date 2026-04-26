"""Priority 7 — Retry Engine — Tests.

Test IDs: ST-09 .. ST-16

Coverage:
  ST-09  SKIPPED when previous result is COMPLETED
  ST-10  SKIPPED when previous result is CANCELLED
  ST-11  FATAL for each constant in FATAL_BLOCK_REASONS
  ST-12  EXHAUSTED when attempt_number >= budget
  ST-13  Backoff doubles each attempt: 2 -> 4 -> 8 -> 16 -> 32
  ST-14  Backoff capped at max_delay_s
  ST-15  is_fatal returns False for None blocked_reason
  ST-16  is_retryable returns True for INSUFFICIENT_BALANCE
"""
from __future__ import annotations

import pytest

from projects.polymarket.polyquantbot.platform.execution.fund_settlement import (
    FUND_SETTLEMENT_BLOCK_CAPITAL_NOT_AUTHORIZED,
    FUND_SETTLEMENT_BLOCK_INSUFFICIENT_BALANCE,
    FUND_SETTLEMENT_BLOCK_IRREVERSIBLE_ACK_MISSING,
    FUND_SETTLEMENT_BLOCK_REAL_SETTLEMENT_NOT_ALLOWED,
    FUND_SETTLEMENT_BLOCK_SETTLEMENT_DISABLED,
    FUND_SETTLEMENT_BLOCK_WALLET_ACCESS_DENIED,
    FUND_SETTLEMENT_HALT_MONITORING_ANOMALY,
)
from projects.polymarket.polyquantbot.server.settlement.schemas import (
    RETRY_MAX_BUDGET,
    RETRY_OUTCOME_ACCEPTED,
    RETRY_OUTCOME_EXHAUSTED,
    RETRY_OUTCOME_FATAL,
    RETRY_OUTCOME_SKIPPED,
    SETTLEMENT_STATUS_CANCELLED,
    SETTLEMENT_STATUS_COMPLETED,
    SETTLEMENT_STATUS_FAILED,
    RetryDecision,
    RetryPolicy,
    SettlementWorkflowResult,
)
from projects.polymarket.polyquantbot.server.settlement.retry_engine import (
    FATAL_BLOCK_REASONS,
    RETRYABLE_BLOCK_REASONS,
    RetryEngine,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _failed_result(
    workflow_id: str = "stl_aaa",
    blocked_reason: str | None = None,
    status: str = SETTLEMENT_STATUS_FAILED,
) -> SettlementWorkflowResult:
    return SettlementWorkflowResult(
        workflow_id=workflow_id,
        status=status,
        success=False,
        blocked_reason=blocked_reason,
    )


def _completed_result(workflow_id: str = "stl_aaa") -> SettlementWorkflowResult:
    return SettlementWorkflowResult(
        workflow_id=workflow_id,
        status=SETTLEMENT_STATUS_COMPLETED,
        success=True,
    )


def _cancelled_result(workflow_id: str = "stl_aaa") -> SettlementWorkflowResult:
    return SettlementWorkflowResult(
        workflow_id=workflow_id,
        status=SETTLEMENT_STATUS_CANCELLED,
        success=False,
        blocked_reason="operator_cancel",
    )


_engine = RetryEngine()


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_st_09_skipped_when_completed():
    """ST-09: SKIPPED outcome when previous result is COMPLETED."""
    decision = _engine.evaluate(
        workflow_id="stl_aaa",
        previous_result=_completed_result(),
        attempt_number=1,
    )
    assert decision.outcome == RETRY_OUTCOME_SKIPPED
    assert decision.is_fatal is False
    assert decision.is_exhausted is False


def test_st_10_skipped_when_cancelled():
    """ST-10: SKIPPED outcome when previous result is CANCELLED."""
    decision = _engine.evaluate(
        workflow_id="stl_aaa",
        previous_result=_cancelled_result(),
        attempt_number=1,
    )
    assert decision.outcome == RETRY_OUTCOME_SKIPPED


def test_st_11_fatal_for_all_fatal_block_reasons():
    """ST-11: FATAL outcome for every reason in FATAL_BLOCK_REASONS."""
    for reason in FATAL_BLOCK_REASONS:
        decision = _engine.evaluate(
            workflow_id="stl_aaa",
            previous_result=_failed_result(blocked_reason=reason),
            attempt_number=1,
        )
        assert decision.outcome == RETRY_OUTCOME_FATAL, f"Expected FATAL for {reason!r}"
        assert decision.is_fatal is True


def test_st_11b_fatal_reasons_and_retryable_reasons_are_disjoint():
    """ST-11b: FATAL_BLOCK_REASONS and RETRYABLE_BLOCK_REASONS share no elements."""
    overlap = FATAL_BLOCK_REASONS & RETRYABLE_BLOCK_REASONS
    assert not overlap, f"Overlap found: {overlap}"


def test_st_12_exhausted_when_attempt_meets_budget():
    """ST-12: EXHAUSTED when attempt_number == budget (no more retries left)."""
    decision = _engine.evaluate(
        workflow_id="stl_aaa",
        previous_result=_failed_result(blocked_reason=FUND_SETTLEMENT_BLOCK_INSUFFICIENT_BALANCE),
        attempt_number=RETRY_MAX_BUDGET,
    )
    assert decision.outcome == RETRY_OUTCOME_EXHAUSTED
    assert decision.is_exhausted is True
    assert decision.next_delay_s is None


def test_st_12b_exhausted_when_attempt_exceeds_budget():
    """ST-12b: EXHAUSTED when attempt_number > budget (safety net)."""
    decision = _engine.evaluate(
        workflow_id="stl_aaa",
        previous_result=_failed_result(),
        attempt_number=RETRY_MAX_BUDGET + 10,
    )
    assert decision.outcome == RETRY_OUTCOME_EXHAUSTED


def test_st_13_backoff_doubles_each_attempt():
    """ST-13: Exponential backoff: 2 -> 4 -> 8 -> 16 -> 32 seconds."""
    policy = RetryPolicy(base_delay_s=2.0, backoff_multiplier=2.0, max_delay_s=9999.0)
    engine = RetryEngine(policy=policy)
    expected = [2.0, 4.0, 8.0, 16.0, 32.0]
    for attempt, exp in enumerate(expected, start=1):
        assert engine.compute_delay(attempt) == exp, f"attempt {attempt}: expected {exp}"


def test_st_14_backoff_capped_at_max_delay():
    """ST-14: Backoff never exceeds max_delay_s regardless of attempt count."""
    policy = RetryPolicy(base_delay_s=2.0, backoff_multiplier=2.0, max_delay_s=10.0)
    engine = RetryEngine(policy=policy)
    assert engine.compute_delay(10) == 10.0
    assert engine.compute_delay(100) == 10.0


def test_st_15_is_fatal_returns_false_for_none():
    """ST-15: is_fatal returns False when blocked_reason is None."""
    assert RetryEngine.is_fatal(None) is False


def test_st_15b_is_fatal_returns_false_for_unknown_reason():
    """ST-15b: is_fatal returns False for an unknown reason string."""
    assert RetryEngine.is_fatal("some_unknown_reason") is False


def test_st_16_insufficient_balance_is_retryable():
    """ST-16: INSUFFICIENT_BALANCE is classified as retryable."""
    assert RetryEngine.is_retryable(FUND_SETTLEMENT_BLOCK_INSUFFICIENT_BALANCE) is True


def test_st_16b_is_retryable_returns_false_for_none():
    """ST-16b: is_retryable returns False when blocked_reason is None."""
    assert RetryEngine.is_retryable(None) is False


def test_st_16c_accepted_outcome_has_next_delay():
    """ST-16c: ACCEPTED decision includes a positive next_delay_s."""
    decision = _engine.evaluate(
        workflow_id="stl_aaa",
        previous_result=_failed_result(blocked_reason=FUND_SETTLEMENT_BLOCK_INSUFFICIENT_BALANCE),
        attempt_number=1,
        retry_budget=5,
    )
    assert decision.outcome == RETRY_OUTCOME_ACCEPTED
    assert decision.next_delay_s is not None
    assert decision.next_delay_s > 0


def test_st_16d_retry_decision_is_frozen():
    """ST-16d: RetryDecision is a frozen dataclass."""
    from dataclasses import FrozenInstanceError
    d = RetryDecision(
        workflow_id="stl_x",
        outcome=RETRY_OUTCOME_ACCEPTED,
        attempt_number=1,
        is_fatal=False,
        is_exhausted=False,
    )
    with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
        d.outcome = "changed"  # type: ignore[misc]
