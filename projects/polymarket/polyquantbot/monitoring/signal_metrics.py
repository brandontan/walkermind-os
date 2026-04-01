"""Phase 10.8 — SignalMetrics: per-run signal counter accumulation.

Tracks:
  - total_signals_generated
  - total_signals_skipped
  - reason breakdown: low_edge | low_liquidity | risk_block | duplicate

Thread-safety: all mutations are done within a single asyncio event loop;
no locking is required as long as callers do not share an instance across
threads.  For multi-threaded use, wrap in asyncio.Lock externally.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict

import structlog

log = structlog.get_logger()


class SkipReason(str, Enum):
    """Reason why a signal tick was not executed."""

    LOW_EDGE = "low_edge"
    LOW_LIQUIDITY = "low_liquidity"
    RISK_BLOCK = "risk_block"
    DUPLICATE = "duplicate"


@dataclass
class SignalMetricsSnapshot:
    """Point-in-time snapshot of all signal counters.

    Attributes:
        total_generated: Signals accepted for execution.
        total_skipped: Signals that did not pass the gate.
        skipped_low_edge: Skips due to insufficient model-vs-market edge.
        skipped_low_liquidity: Skips due to insufficient orderbook depth.
        skipped_risk_block: Skips blocked by RiskGuard / kill switch.
        skipped_duplicate: Skips because OrderGuard detected a duplicate.
        snapshot_ts: Unix timestamp when this snapshot was taken.
    """

    total_generated: int = 0
    total_skipped: int = 0
    skipped_low_edge: int = 0
    skipped_low_liquidity: int = 0
    skipped_risk_block: int = 0
    skipped_duplicate: int = 0
    snapshot_ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        """Return a JSON-serialisable representation."""
        return {
            "total_generated": self.total_generated,
            "total_skipped": self.total_skipped,
            "skipped_breakdown": {
                SkipReason.LOW_EDGE.value: self.skipped_low_edge,
                SkipReason.LOW_LIQUIDITY.value: self.skipped_low_liquidity,
                SkipReason.RISK_BLOCK.value: self.skipped_risk_block,
                SkipReason.DUPLICATE.value: self.skipped_duplicate,
            },
            "snapshot_ts": self.snapshot_ts,
        }


class SignalMetrics:
    """Accumulator for signal-level counters.

    All methods are synchronous and O(1).  Call ``snapshot()`` at any time
    to obtain a frozen view of the current state.
    """

    def __init__(self) -> None:
        self._generated: int = 0
        self._skip_counts: Dict[SkipReason, int] = {r: 0 for r in SkipReason}

    # ── Mutation ──────────────────────────────────────────────────────────────

    def record_generated(self) -> None:
        """Increment the total-generated counter."""
        self._generated += 1
        log.debug("signal_metrics_generated", total=self._generated)

    def record_skip(self, reason: SkipReason) -> None:
        """Increment the skipped counter for the given reason.

        Args:
            reason: Why the signal was not executed.
        """
        self._skip_counts[reason] += 1
        log.debug(
            "signal_metrics_skipped",
            reason=reason.value,
            total_skipped=self.total_skipped,
        )

    # ── Query ─────────────────────────────────────────────────────────────────

    @property
    def total_generated(self) -> int:
        """Total signals accepted for execution."""
        return self._generated

    @property
    def total_skipped(self) -> int:
        """Total signal ticks that were not executed."""
        return sum(self._skip_counts.values())

    def snapshot(self) -> SignalMetricsSnapshot:
        """Return a frozen point-in-time snapshot of all counters."""
        return SignalMetricsSnapshot(
            total_generated=self._generated,
            total_skipped=self.total_skipped,
            skipped_low_edge=self._skip_counts[SkipReason.LOW_EDGE],
            skipped_low_liquidity=self._skip_counts[SkipReason.LOW_LIQUIDITY],
            skipped_risk_block=self._skip_counts[SkipReason.RISK_BLOCK],
            skipped_duplicate=self._skip_counts[SkipReason.DUPLICATE],
        )

    def log_summary(self) -> None:
        """Emit a structured info log with the current counter snapshot."""
        snap = self.snapshot()
        log.info(
            "signal_metrics_summary",
            **snap.to_dict(),
        )
