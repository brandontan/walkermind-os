"""Phase 10.2 — FillTracker: Real fill tracking with slippage and latency.

Captures every fill received from the exchange, computes per-trade slippage
(in basis points), fill latency, and maintains aggregate statistics.

Tracked per trade:
    order_id          — exchange order ID
    market_id         — Polymarket condition ID
    side              — "YES" | "NO"
    expected_price    — limit price at order submission
    executed_price    — VWAP of actual fills received
    size_usd          — filled size in USD
    slippage_bps      — (executed - expected) / expected * 10_000
    fill_latency_ms   — ms from order submission to fill confirmation
    submitted_at      — Unix timestamp of order submission
    filled_at         — Unix timestamp of fill confirmation
    status            — "filled" | "partial" | "missed"

Aggregate statistics:
    avg_slippage_bps  — average slippage across all fills
    worst_slippage_bps — largest absolute slippage observed
    p95_slippage_bps  — 95th-percentile slippage
    fill_accuracy_pct — fraction of orders within slippage_threshold_bps
    execution_success_rate — fraction of submitted orders that were filled

Alerts are triggered when:
    - slippage > slippage_threshold_bps (default 50 bps)
    - fill latency > latency_threshold_ms (default 1 000 ms)

Usage::

    tracker = FillTracker(slippage_threshold_bps=50.0, latency_threshold_ms=1000.0)
    tracker.record_submission(order_id="0xabc", market_id="0xdef",
                              side="YES", expected_price=0.62, size_usd=100.0)
    tracker.record_fill(order_id="0xabc", executed_price=0.625, filled_size=100.0)
    stats = tracker.aggregate()
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import structlog

log = structlog.get_logger()

# ── Constants ─────────────────────────────────────────────────────────────────

_DEFAULT_SLIPPAGE_THRESHOLD_BPS: float = 50.0   # flag if slippage > 50 bps
_DEFAULT_LATENCY_THRESHOLD_MS: float = 1_000.0  # flag if latency > 1 s


# ── Data types ────────────────────────────────────────────────────────────────

class FillStatus(str, Enum):
    """Lifecycle status of a tracked fill."""
    PENDING  = "pending"    # submission registered; fill not yet received
    FILLED   = "filled"     # fully filled
    PARTIAL  = "partial"    # partially filled
    MISSED   = "missed"     # order expired/cancelled without any fill


@dataclass
class FillRecord:
    """Immutable record for a single tracked order fill.

    Attributes:
        order_id: Exchange-assigned order ID.
        market_id: Polymarket condition ID.
        side: "YES" | "NO".
        expected_price: Limit price at order submission.
        executed_price: VWAP of actual fills (0.0 while pending).
        size_usd: Filled size in USD (0.0 while pending).
        slippage_bps: (executed - expected) / expected * 10 000.
                      Positive = filled worse than expected.
        fill_latency_ms: ms from submission to fill confirmation.
        submitted_at: Unix timestamp of order submission.
        filled_at: Unix timestamp of fill confirmation (0.0 while pending).
        status: Current fill lifecycle status.
    """
    order_id: str
    market_id: str
    side: str
    expected_price: float
    executed_price: float = 0.0
    size_usd: float = 0.0
    slippage_bps: float = 0.0
    fill_latency_ms: float = 0.0
    submitted_at: float = field(default_factory=time.time)
    filled_at: float = 0.0
    status: FillStatus = FillStatus.PENDING


@dataclass
class FillAggregate:
    """Aggregate slippage and execution statistics across all fills.

    Attributes:
        total_submitted: Number of orders submitted.
        total_filled: Orders with status FILLED or PARTIAL.
        total_missed: Orders with status MISSED.
        execution_success_rate: total_filled / total_submitted.
        avg_slippage_bps: Mean slippage across all filled orders.
        p95_slippage_bps: 95th-percentile slippage.
        worst_slippage_bps: Largest absolute slippage observed.
        avg_latency_ms: Mean fill latency across all filled orders.
        fill_accuracy_pct: Fraction of fills within slippage threshold.
        threshold_bps: Slippage threshold used for fill_accuracy_pct.
    """
    total_submitted: int
    total_filled: int
    total_missed: int
    execution_success_rate: float
    avg_slippage_bps: float
    p95_slippage_bps: float
    worst_slippage_bps: float
    avg_latency_ms: float
    fill_accuracy_pct: float
    threshold_bps: float


# ── FillTracker ───────────────────────────────────────────────────────────────

class FillTracker:
    """Tracks actual fills from the exchange and computes slippage metrics.

    Thread-safety: single asyncio event loop only.
    All methods are synchronous (in-memory updates).

    Args:
        slippage_threshold_bps: Alert threshold for per-trade slippage.
        latency_threshold_ms: Alert threshold for fill latency (ms).
    """

    def __init__(
        self,
        slippage_threshold_bps: float = _DEFAULT_SLIPPAGE_THRESHOLD_BPS,
        latency_threshold_ms: float = _DEFAULT_LATENCY_THRESHOLD_MS,
    ) -> None:
        self._slippage_threshold_bps = slippage_threshold_bps
        self._latency_threshold_ms = latency_threshold_ms
        self._records: dict[str, FillRecord] = {}   # keyed by order_id

        log.info(
            "fill_tracker_initialized",
            slippage_threshold_bps=slippage_threshold_bps,
            latency_threshold_ms=latency_threshold_ms,
        )

    # ── Public API ─────────────────────────────────────────────────────────────

    def record_submission(
        self,
        order_id: str,
        market_id: str,
        side: str,
        expected_price: float,
        size_usd: float,
    ) -> FillRecord:
        """Register a new order submission for fill tracking.

        Args:
            order_id: Exchange-assigned order ID.
            market_id: Polymarket condition ID.
            side: "YES" | "NO".
            expected_price: Limit price submitted to the exchange.
            size_usd: Order size in USD.

        Returns:
            The new :class:`FillRecord` in PENDING state.
        """
        if order_id in self._records:
            log.warning(
                "fill_tracker_duplicate_submission",
                order_id=order_id,
                existing_status=self._records[order_id].status,
            )
            return self._records[order_id]

        record = FillRecord(
            order_id=order_id,
            market_id=market_id,
            side=side,
            expected_price=expected_price,
            size_usd=size_usd,
            submitted_at=time.time(),
        )
        self._records[order_id] = record

        log.debug(
            "fill_tracker_submission_registered",
            order_id=order_id,
            market_id=market_id,
            side=side,
            expected_price=expected_price,
            size_usd=size_usd,
        )
        return record

    def record_fill(
        self,
        order_id: str,
        executed_price: float,
        filled_size: float,
        partial: bool = False,
    ) -> FillRecord:
        """Record a fill event for a previously submitted order.

        Computes slippage_bps and fill_latency_ms and triggers alerts when
        thresholds are exceeded.

        Args:
            order_id: Exchange-assigned order ID.
            executed_price: VWAP of the actual fill(s).
            filled_size: USD amount filled.
            partial: True if only partially filled (PARTIAL status).

        Returns:
            Updated :class:`FillRecord`.

        Raises:
            KeyError: If ``order_id`` was never registered via
                      :meth:`record_submission`.
        """
        if order_id not in self._records:
            log.error(
                "fill_tracker_unknown_order",
                order_id=order_id,
                action="record_fill",
            )
            raise KeyError(f"Unknown order_id: {order_id!r}")

        record = self._records[order_id]
        now = time.time()

        record.executed_price = executed_price
        record.size_usd = filled_size
        record.filled_at = now
        record.fill_latency_ms = (now - record.submitted_at) * 1_000.0
        record.status = FillStatus.PARTIAL if partial else FillStatus.FILLED

        # ── Slippage ─────────────────────────────────────────────────────────
        if record.expected_price > 1e-9:
            record.slippage_bps = (
                (executed_price - record.expected_price)
                / record.expected_price
                * 10_000.0
            )
        else:
            record.slippage_bps = 0.0

        # ── Alerts ───────────────────────────────────────────────────────────
        if abs(record.slippage_bps) > self._slippage_threshold_bps:
            log.warning(
                "fill_tracker_slippage_alert",
                order_id=order_id,
                market_id=record.market_id,
                side=record.side,
                expected_price=record.expected_price,
                executed_price=executed_price,
                slippage_bps=round(record.slippage_bps, 2),
                threshold_bps=self._slippage_threshold_bps,
            )

        if record.fill_latency_ms > self._latency_threshold_ms:
            log.warning(
                "fill_tracker_latency_spike",
                order_id=order_id,
                market_id=record.market_id,
                fill_latency_ms=round(record.fill_latency_ms, 1),
                threshold_ms=self._latency_threshold_ms,
            )

        log.info(
            "fill_tracker_fill_recorded",
            order_id=order_id,
            market_id=record.market_id,
            side=record.side,
            expected_price=record.expected_price,
            executed_price=executed_price,
            slippage_bps=round(record.slippage_bps, 2),
            fill_latency_ms=round(record.fill_latency_ms, 1),
            status=record.status,
        )
        return record

    def mark_missed(self, order_id: str) -> FillRecord:
        """Mark an order as missed (expired or cancelled without any fill).

        Args:
            order_id: Exchange-assigned order ID.

        Returns:
            Updated :class:`FillRecord` with MISSED status.

        Raises:
            KeyError: If ``order_id`` was never registered.
        """
        if order_id not in self._records:
            log.error(
                "fill_tracker_unknown_order",
                order_id=order_id,
                action="mark_missed",
            )
            raise KeyError(f"Unknown order_id: {order_id!r}")

        record = self._records[order_id]
        record.status = FillStatus.MISSED
        log.warning(
            "fill_tracker_fill_missed",
            order_id=order_id,
            market_id=record.market_id,
            side=record.side,
        )
        return record

    def get_record(self, order_id: str) -> Optional[FillRecord]:
        """Return the :class:`FillRecord` for *order_id*, or ``None``."""
        return self._records.get(order_id)

    def all_records(self) -> list[FillRecord]:
        """Return all tracked :class:`FillRecord` instances."""
        return list(self._records.values())

    def aggregate(self) -> FillAggregate:
        """Compute aggregate fill and slippage statistics.

        Returns:
            :class:`FillAggregate` with current session statistics.
        """
        records = list(self._records.values())
        total_submitted = len(records)
        filled = [
            r for r in records
            if r.status in (FillStatus.FILLED, FillStatus.PARTIAL)
        ]
        missed = [r for r in records if r.status == FillStatus.MISSED]

        total_filled = len(filled)
        total_missed = len(missed)
        execution_success_rate = total_filled / total_submitted if total_submitted else 1.0

        slippage_values = [r.slippage_bps for r in filled]
        latency_values = [r.fill_latency_ms for r in filled if r.fill_latency_ms > 0]

        avg_slippage = sum(slippage_values) / len(slippage_values) if slippage_values else 0.0
        worst_slippage = max((abs(s) for s in slippage_values), default=0.0)
        p95_slippage = _percentile_95(slippage_values) if slippage_values else 0.0
        avg_latency = sum(latency_values) / len(latency_values) if latency_values else 0.0

        within_threshold = sum(
            1 for s in slippage_values if abs(s) <= self._slippage_threshold_bps
        )
        fill_accuracy_pct = within_threshold / total_filled if total_filled else 1.0

        agg = FillAggregate(
            total_submitted=total_submitted,
            total_filled=total_filled,
            total_missed=total_missed,
            execution_success_rate=round(execution_success_rate, 4),
            avg_slippage_bps=round(avg_slippage, 2),
            p95_slippage_bps=round(p95_slippage, 2),
            worst_slippage_bps=round(worst_slippage, 2),
            avg_latency_ms=round(avg_latency, 2),
            fill_accuracy_pct=round(fill_accuracy_pct, 4),
            threshold_bps=self._slippage_threshold_bps,
        )

        log.info(
            "fill_tracker_aggregate",
            total_submitted=total_submitted,
            total_filled=total_filled,
            total_missed=total_missed,
            execution_success_rate=agg.execution_success_rate,
            avg_slippage_bps=agg.avg_slippage_bps,
            p95_slippage_bps=agg.p95_slippage_bps,
            worst_slippage_bps=agg.worst_slippage_bps,
            avg_latency_ms=agg.avg_latency_ms,
            fill_accuracy_pct=agg.fill_accuracy_pct,
        )
        return agg


# ── Helpers ───────────────────────────────────────────────────────────────────

def _percentile_95(values: list[float]) -> float:
    """Compute the 95th-percentile value using the nearest-rank method."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = max(0, math.ceil(len(sorted_vals) * 0.95) - 1)
    return sorted_vals[idx]
