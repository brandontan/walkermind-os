"""Retry Engine — Priority 7 section 44.

Stateless, synchronous — the caller is responsible for honouring next_delay_s.
This keeps the engine fully unit-testable without asyncio.sleep and matches the
WalletReconciliationRetryWorkerBoundary pattern from wallet_lifecycle_foundation.

Fatal block reasons are imported directly from fund_settlement so that file
remains the authoritative source of truth for block classification.
"""
from __future__ import annotations

import math
from typing import Any

import structlog

from projects.polymarket.polyquantbot.platform.execution.fund_settlement import (
    FUND_SETTLEMENT_BLOCK_CAPITAL_NOT_AUTHORIZED,
    FUND_SETTLEMENT_BLOCK_IRREVERSIBLE_ACK_MISSING,
    FUND_SETTLEMENT_BLOCK_REAL_SETTLEMENT_NOT_ALLOWED,
    FUND_SETTLEMENT_BLOCK_SETTLEMENT_DISABLED,
    FUND_SETTLEMENT_BLOCK_WALLET_ACCESS_DENIED,
    FUND_SETTLEMENT_HALT_MONITORING_ANOMALY,
    FUND_SETTLEMENT_BLOCK_INSUFFICIENT_BALANCE,
    FUND_SETTLEMENT_BLOCK_SETTLEMENT_LIMIT_EXCEEDED,
    FUND_SETTLEMENT_BLOCK_MONITORING_EVALUATION_REQUIRED,
    FUND_SETTLEMENT_BLOCK_MONITORING_ANOMALY,
    FUND_SETTLEMENT_BLOCK_FINAL_CONFIRMATION_MISSING,
)

from .schemas import (
    RETRY_MAX_BUDGET,
    RETRY_OUTCOME_ACCEPTED,
    RETRY_OUTCOME_EXHAUSTED,
    RETRY_OUTCOME_FATAL,
    RETRY_OUTCOME_SKIPPED,
    SETTLEMENT_STATUS_COMPLETED,
    SETTLEMENT_STATUS_CANCELLED,
    RetryDecision,
    RetryPolicy,
    SettlementWorkflowResult,
)

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Block reason classification — authoritative source is fund_settlement.py
# ---------------------------------------------------------------------------

FATAL_BLOCK_REASONS: frozenset[str] = frozenset({
    FUND_SETTLEMENT_BLOCK_REAL_SETTLEMENT_NOT_ALLOWED,
    FUND_SETTLEMENT_BLOCK_SETTLEMENT_DISABLED,
    FUND_SETTLEMENT_BLOCK_CAPITAL_NOT_AUTHORIZED,
    FUND_SETTLEMENT_BLOCK_WALLET_ACCESS_DENIED,
    FUND_SETTLEMENT_BLOCK_IRREVERSIBLE_ACK_MISSING,
    FUND_SETTLEMENT_HALT_MONITORING_ANOMALY,
})

RETRYABLE_BLOCK_REASONS: frozenset[str] = frozenset({
    FUND_SETTLEMENT_BLOCK_INSUFFICIENT_BALANCE,
    FUND_SETTLEMENT_BLOCK_SETTLEMENT_LIMIT_EXCEEDED,
    FUND_SETTLEMENT_BLOCK_MONITORING_EVALUATION_REQUIRED,
    FUND_SETTLEMENT_BLOCK_MONITORING_ANOMALY,
    FUND_SETTLEMENT_BLOCK_FINAL_CONFIRMATION_MISSING,
})

_DEFAULT_POLICY = RetryPolicy()


class RetryEngine:
    """Stateless retry decision engine.

    Computes retry decisions without performing I/O or sleeping.
    The caller (worker/scheduler) is responsible for honouring next_delay_s.
    """

    def __init__(self, *, policy: RetryPolicy | None = None) -> None:
        self._policy = policy or _DEFAULT_POLICY

    def evaluate(
        self,
        *,
        workflow_id: str,
        previous_result: SettlementWorkflowResult,
        attempt_number: int,
        retry_budget: int | None = None,
    ) -> RetryDecision:
        """Return a RetryDecision for the given workflow state.

        attempt_number is the number of attempts already completed (1-based for
        the last completed attempt).  next_delay_s is None when terminal.
        """
        budget = min(retry_budget or RETRY_MAX_BUDGET, RETRY_MAX_BUDGET)
        bound = log.bind(workflow_id=workflow_id, attempt_number=attempt_number, budget=budget)

        if previous_result.status in (SETTLEMENT_STATUS_COMPLETED, SETTLEMENT_STATUS_CANCELLED):
            bound.info("retry_engine_skipped_terminal")
            return RetryDecision(
                workflow_id=workflow_id,
                outcome=RETRY_OUTCOME_SKIPPED,
                attempt_number=attempt_number,
                is_fatal=False,
                is_exhausted=False,
            )

        if self.is_fatal(previous_result.blocked_reason):
            bound.info(
                "retry_engine_fatal",
                blocked_reason=previous_result.blocked_reason,
            )
            return RetryDecision(
                workflow_id=workflow_id,
                outcome=RETRY_OUTCOME_FATAL,
                attempt_number=attempt_number,
                is_fatal=True,
                is_exhausted=False,
                blocked_reason=previous_result.blocked_reason,
            )

        if attempt_number >= budget:
            bound.info("retry_engine_exhausted")
            return RetryDecision(
                workflow_id=workflow_id,
                outcome=RETRY_OUTCOME_EXHAUSTED,
                attempt_number=attempt_number,
                is_fatal=False,
                is_exhausted=True,
                blocked_reason=previous_result.blocked_reason,
            )

        next_delay = self.compute_delay(attempt_number)
        bound.info("retry_engine_accepted", next_delay_s=next_delay)
        return RetryDecision(
            workflow_id=workflow_id,
            outcome=RETRY_OUTCOME_ACCEPTED,
            attempt_number=attempt_number,
            is_fatal=False,
            is_exhausted=False,
            next_delay_s=next_delay,
            blocked_reason=previous_result.blocked_reason,
        )

    def compute_delay(self, attempt_number: int) -> float:
        """Exponential backoff: base * multiplier^(attempt-1), capped at max_delay_s."""
        raw = self._policy.base_delay_s * (self._policy.backoff_multiplier ** (attempt_number - 1))
        return min(raw, self._policy.max_delay_s)

    @staticmethod
    def is_fatal(blocked_reason: str | None) -> bool:
        if blocked_reason is None:
            return False
        return blocked_reason in FATAL_BLOCK_REASONS

    @staticmethod
    def is_retryable(blocked_reason: str | None) -> bool:
        if blocked_reason is None:
            return False
        return blocked_reason in RETRYABLE_BLOCK_REASONS
