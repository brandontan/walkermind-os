"""Phase 7 — ExecutionFeedback.

Tracks expected vs actual order fills and slippage per execution.
Closes the feedback loop between the Phase 6.6 fill probability model
and real market outcomes, enabling continuous calibration.

Feedback Output schema:
    {
        "expected_fill_prob": float,    # from ExecutionEnginePatch
        "actual_fill": bool,            # True if any fill occurred
        "fill_error": float,            # expected_fill_prob - (1.0 if filled else 0.0)
        "expected_slippage": float,     # derived from spread at submission
        "actual_slippage": float,       # |avg_fill_price - limit_price|
        "latency_ms": float,            # API RTT at time of execution
    }

Usage::

    feedback = ExecutionFeedbackTracker()
    # At order submission:
    feedback.record_expected(order_id, expected_fill_prob, expected_slippage, latency_ms)
    # After fill confirmed (via poll or WS):
    result = feedback.record_actual(order_id, actual_fill, avg_fill_price, limit_price, correlation_id)
    print(result)
"""
from __future__ import annotations

import statistics
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import structlog

log = structlog.get_logger()

# ── Constants ─────────────────────────────────────────────────────────────────

_WINDOW_SIZE: int = 500     # rolling feedback samples kept


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class ExpectedOutcome:
    """What we predicted at order submission."""

    order_id: str
    market_id: str
    expected_fill_prob: float
    expected_slippage: float    # |spread| * 0.5 as proxy
    limit_price: float
    latency_ms: float
    submitted_at: float
    correlation_id: str


@dataclass
class FeedbackRecord:
    """Complete feedback entry after actual outcome is known."""

    order_id: str
    market_id: str
    correlation_id: str

    # Model prediction
    expected_fill_prob: float
    expected_slippage: float

    # Actual outcome
    actual_fill: bool
    actual_fill_size: float
    avg_fill_price: float
    actual_slippage: float      # |avg_fill_price - limit_price|

    # Error metrics
    fill_error: float           # expected_fill_prob - (1.0 if filled else 0.0)
    slippage_error: float       # expected_slippage - actual_slippage

    # Timing
    latency_ms: float
    submitted_at: float
    resolved_at: float
    time_to_fill_ms: float      # ms from submission to fill confirmation


# ── ExecutionFeedbackTracker ──────────────────────────────────────────────────

class ExecutionFeedbackTracker:
    """Track and analyze execution feedback per order.

    Stores predicted vs actual fill probability and slippage.
    Provides calibration metrics to improve the fill probability model.

    Thread-safety: single asyncio event loop only.
    """

    def __init__(self, window_size: int = _WINDOW_SIZE) -> None:
        """Initialise the feedback tracker.

        Args:
            window_size: Max rolling feedback records to retain.
        """
        self._window = window_size
        self._pending: dict[str, ExpectedOutcome] = {}   # order_id → expected
        self._records: deque = deque(maxlen=window_size)  # resolved FeedbackRecords

    def record_expected(
        self,
        order_id: str,
        market_id: str,
        expected_fill_prob: float,
        expected_slippage: float,
        limit_price: float,
        latency_ms: float,
        correlation_id: str,
    ) -> None:
        """Register expected outcome at order submission time.

        Call immediately after LiveExecutor.execute() returns with
        status='submitted' or 'partial'.

        Args:
            order_id: Exchange order ID.
            market_id: Target market.
            expected_fill_prob: Model fill probability ∈ [0, 1].
            expected_slippage: Expected slippage (e.g. half-spread).
            limit_price: Submitted limit price.
            latency_ms: API RTT at submission.
            correlation_id: Request ID.
        """
        self._pending[order_id] = ExpectedOutcome(
            order_id=order_id,
            market_id=market_id,
            expected_fill_prob=max(0.0, min(1.0, expected_fill_prob)),
            expected_slippage=max(0.0, expected_slippage),
            limit_price=limit_price,
            latency_ms=latency_ms,
            submitted_at=time.time(),
            correlation_id=correlation_id,
        )
        log.debug(
            "feedback_expected_recorded",
            order_id=order_id,
            correlation_id=correlation_id,
            expected_fill_prob=round(expected_fill_prob, 4),
            expected_slippage=round(expected_slippage, 6),
            limit_price=limit_price,
        )

    def record_actual(
        self,
        order_id: str,
        actual_fill: bool,
        avg_fill_price: float,
        actual_fill_size: float,
        correlation_id: str,
    ) -> Optional[FeedbackRecord]:
        """Record actual fill outcome and compute feedback metrics.

        Call when fill status is confirmed (via poll or WS trade event).

        Args:
            order_id: Exchange order ID.
            actual_fill: True if any fill occurred (partial or full).
            avg_fill_price: Volume-weighted average fill price (0 if no fill).
            actual_fill_size: Actual filled size in USD.
            correlation_id: Request ID.

        Returns:
            FeedbackRecord with all metrics, or None if order_id not pending.
        """
        expected = self._pending.pop(order_id, None)
        if expected is None:
            log.warning(
                "feedback_no_expected_record",
                order_id=order_id,
                correlation_id=correlation_id,
            )
            return None

        now = time.time()
        time_to_fill_ms = (now - expected.submitted_at) * 1000

        # Compute actual slippage
        if actual_fill and avg_fill_price > 0:
            actual_slippage = abs(avg_fill_price - expected.limit_price)
        else:
            actual_slippage = 0.0

        # Fill error: positive means model over-estimated fill probability
        fill_error = expected.expected_fill_prob - (1.0 if actual_fill else 0.0)
        slippage_error = expected.expected_slippage - actual_slippage

        record = FeedbackRecord(
            order_id=order_id,
            market_id=expected.market_id,
            correlation_id=correlation_id,
            expected_fill_prob=expected.expected_fill_prob,
            expected_slippage=expected.expected_slippage,
            actual_fill=actual_fill,
            actual_fill_size=actual_fill_size,
            avg_fill_price=avg_fill_price,
            actual_slippage=round(actual_slippage, 6),
            fill_error=round(fill_error, 6),
            slippage_error=round(slippage_error, 6),
            latency_ms=expected.latency_ms,
            submitted_at=expected.submitted_at,
            resolved_at=now,
            time_to_fill_ms=round(time_to_fill_ms, 2),
        )

        self._records.append(record)

        log.info(
            "feedback_actual_recorded",
            order_id=order_id,
            correlation_id=correlation_id,
            market_id=expected.market_id,
            expected_fill_prob=record.expected_fill_prob,
            actual_fill=actual_fill,
            fill_error=record.fill_error,
            expected_slippage=record.expected_slippage,
            actual_slippage=record.actual_slippage,
            slippage_error=record.slippage_error,
            latency_ms=record.latency_ms,
            time_to_fill_ms=record.time_to_fill_ms,
        )

        return record

    def as_dict(self, record: FeedbackRecord) -> dict:
        """Return FeedbackRecord as canonical output dict (matches spec schema)."""
        return {
            "expected_fill_prob": record.expected_fill_prob,
            "actual_fill": record.actual_fill,
            "fill_error": record.fill_error,
            "expected_slippage": record.expected_slippage,
            "actual_slippage": record.actual_slippage,
            "latency_ms": record.latency_ms,
        }

    # ── Calibration analytics ─────────────────────────────────────────────────

    def fill_rate(self, market_id: Optional[str] = None) -> float:
        """Compute actual fill rate ∈ [0, 1] from resolved records.

        Args:
            market_id: Filter by market (None = all markets).

        Returns:
            Fraction of orders that had any fill.
        """
        records = self._filter(market_id)
        if not records:
            return 0.0
        return round(sum(1 for r in records if r.actual_fill) / len(records), 4)

    def mean_fill_error(self, market_id: Optional[str] = None) -> float:
        """Mean fill error (expected_fill_prob - actual).

        Positive → model over-predicts fills.
        Negative → model under-predicts fills.
        """
        records = self._filter(market_id)
        if not records:
            return 0.0
        return round(statistics.mean(r.fill_error for r in records), 6)

    def mean_slippage_error(self, market_id: Optional[str] = None) -> float:
        """Mean slippage error (expected - actual)."""
        records = self._filter(market_id)
        if not records:
            return 0.0
        return round(statistics.mean(r.slippage_error for r in records), 6)

    def mean_time_to_fill_ms(self, market_id: Optional[str] = None) -> float:
        """Mean time from submission to fill confirmation (ms)."""
        records = [r for r in self._filter(market_id) if r.actual_fill]
        if not records:
            return 0.0
        return round(statistics.mean(r.time_to_fill_ms for r in records), 2)

    def calibration_summary(self, market_id: Optional[str] = None) -> dict:
        """Return a full calibration summary dict for logging / reporting."""
        records = self._filter(market_id)
        if not records:
            return {"sample_count": 0}

        return {
            "sample_count": len(records),
            "fill_rate": self.fill_rate(market_id),
            "mean_fill_error": self.mean_fill_error(market_id),
            "mean_slippage_error": self.mean_slippage_error(market_id),
            "mean_time_to_fill_ms": self.mean_time_to_fill_ms(market_id),
            "pending_orders": len(self._pending),
            "market_id": market_id or "*",
        }

    def pending_count(self) -> int:
        """Number of orders awaiting actual outcome."""
        return len(self._pending)

    def expire_pending(self, max_age_s: float = 300.0) -> int:
        """Remove pending records older than max_age_s (assume not filled).

        Returns number of expired records.
        """
        now = time.time()
        expired_ids = [
            oid for oid, exp in self._pending.items()
            if (now - exp.submitted_at) > max_age_s
        ]
        for oid in expired_ids:
            exp = self._pending.pop(oid)
            log.warning(
                "feedback_pending_expired",
                order_id=oid,
                correlation_id=exp.correlation_id,
                age_s=round(now - exp.submitted_at, 1),
            )
            # Record as not filled
            self._records.append(FeedbackRecord(
                order_id=oid,
                market_id=exp.market_id,
                correlation_id=exp.correlation_id,
                expected_fill_prob=exp.expected_fill_prob,
                expected_slippage=exp.expected_slippage,
                actual_fill=False,
                actual_fill_size=0.0,
                avg_fill_price=0.0,
                actual_slippage=0.0,
                fill_error=exp.expected_fill_prob,   # predicted fill, got nothing
                slippage_error=0.0,
                latency_ms=exp.latency_ms,
                submitted_at=exp.submitted_at,
                resolved_at=now,
                time_to_fill_ms=round((now - exp.submitted_at) * 1000, 2),
            ))
        return len(expired_ids)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _filter(self, market_id: Optional[str]) -> list[FeedbackRecord]:
        """Filter records by market_id (None = all)."""
        if market_id is None:
            return list(self._records)
        return [r for r in self._records if r.market_id == market_id]
