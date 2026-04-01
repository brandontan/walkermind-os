"""Phase 7 — LatencyTracker.

Measures and stores API round-trip latency per order execution.
Provides percentile stats, spike detection, and per-market summaries.

Latency is recorded by LiveExecutor after each order submission.
Phase66Integrator reads latency via Phase7MarketCache.

Usage::

    tracker = LatencyTracker()
    tracker.record(market_id="0xabc", order_id="ord_1", latency_ms=142.3, correlation_id=cid)
    stats = tracker.stats("0xabc")
    print(stats.p50_ms, stats.p95_ms)
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

_WINDOW_SIZE: int = 200             # max samples per market
_SPIKE_MULTIPLIER: float = 3.0      # latency spike = > 3x rolling mean
_SPIKE_ABS_THRESHOLD_MS: float = 500.0   # always flag if > 500ms


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class LatencySample:
    """Single latency measurement."""

    order_id: str
    market_id: str
    latency_ms: float
    timestamp: float
    correlation_id: str
    is_spike: bool = False


@dataclass
class LatencyStats:
    """Statistical summary of latency for a market or globally."""

    market_id: str
    sample_count: int
    mean_ms: float
    median_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float
    spike_count: int
    last_ms: float
    window_size: int


# ── LatencyTracker ─────────────────────────────────────────────────────────────

class LatencyTracker:
    """Records and analyzes API execution latency per market.

    Thread-safety: single asyncio event loop only.
    """

    def __init__(
        self,
        window_size: int = _WINDOW_SIZE,
        spike_multiplier: float = _SPIKE_MULTIPLIER,
        spike_abs_threshold_ms: float = _SPIKE_ABS_THRESHOLD_MS,
    ) -> None:
        """Initialise the tracker.

        Args:
            window_size: Rolling window for latency samples per market.
            spike_multiplier: Flag as spike if latency > multiplier * rolling mean.
            spike_abs_threshold_ms: Always flag as spike above this value.
        """
        self._window = window_size
        self._spike_mult = spike_multiplier
        self._spike_abs = spike_abs_threshold_ms

        # market_id → rolling deque of LatencySample
        self._samples: dict[str, deque] = {}
        # Global ring buffer for cross-market stats
        self._global: deque = deque(maxlen=window_size * 4)

    def record(
        self,
        market_id: str,
        order_id: str,
        latency_ms: float,
        correlation_id: str,
    ) -> LatencySample:
        """Record a new latency measurement.

        Args:
            market_id: Market where order was placed.
            order_id: Exchange order ID.
            latency_ms: Measured API RTT in milliseconds.
            correlation_id: Request ID for tracing.

        Returns:
            LatencySample with spike flag.
        """
        if market_id not in self._samples:
            self._samples[market_id] = deque(maxlen=self._window)

        # Spike detection
        is_spike = self._is_spike(market_id, latency_ms)

        sample = LatencySample(
            order_id=order_id,
            market_id=market_id,
            latency_ms=round(latency_ms, 3),
            timestamp=time.time(),
            correlation_id=correlation_id,
            is_spike=is_spike,
        )
        self._samples[market_id].append(sample)
        self._global.append(sample)

        level = log.warning if is_spike else log.info
        level(
            "latency_recorded",
            correlation_id=correlation_id,
            market_id=market_id,
            order_id=order_id,
            latency_ms=round(latency_ms, 2),
            is_spike=is_spike,
        )

        return sample

    def stats(self, market_id: str) -> Optional[LatencyStats]:
        """Return latency statistics for a specific market.

        Returns None if no samples recorded yet.
        """
        buf = self._samples.get(market_id)
        if not buf:
            return None
        return self._compute_stats(market_id, list(buf))

    def global_stats(self) -> Optional[LatencyStats]:
        """Return global latency statistics across all markets."""
        if not self._global:
            return None
        return self._compute_stats("*", list(self._global))

    def last_latency_ms(self, market_id: str) -> float:
        """Return the most recent latency for a market, or default 50ms."""
        buf = self._samples.get(market_id)
        if not buf:
            return 50.0
        return buf[-1].latency_ms

    def spike_rate(self, market_id: str) -> float:
        """Return fraction of samples that were latency spikes ∈ [0, 1]."""
        buf = self._samples.get(market_id)
        if not buf:
            return 0.0
        spikes = sum(1 for s in buf if s.is_spike)
        return round(spikes / len(buf), 4)

    def recent_samples(self, market_id: str, n: int = 10) -> list[LatencySample]:
        """Return the N most recent samples for a market."""
        buf = self._samples.get(market_id)
        if not buf:
            return []
        return list(buf)[-n:]

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _is_spike(self, market_id: str, latency_ms: float) -> bool:
        """Detect a latency spike against rolling mean."""
        if latency_ms >= self._spike_abs:
            return True
        buf = self._samples.get(market_id)
        if not buf or len(buf) < 5:
            return False
        mean = statistics.mean(s.latency_ms for s in buf)
        return latency_ms > mean * self._spike_mult

    @staticmethod
    def _compute_stats(market_id: str, samples: list[LatencySample]) -> LatencyStats:
        """Compute percentile stats from a list of samples."""
        vals = sorted(s.latency_ms for s in samples)
        n = len(vals)

        def percentile(p: float) -> float:
            idx = max(0, min(n - 1, int(p / 100 * n)))
            return round(vals[idx], 3)

        spike_count = sum(1 for s in samples if s.is_spike)

        return LatencyStats(
            market_id=market_id,
            sample_count=n,
            mean_ms=round(statistics.mean(vals), 3),
            median_ms=round(statistics.median(vals), 3),
            p95_ms=percentile(95),
            p99_ms=percentile(99),
            min_ms=round(vals[0], 3),
            max_ms=round(vals[-1], 3),
            spike_count=spike_count,
            last_ms=round(vals[-1], 3),
            window_size=n,
        )
