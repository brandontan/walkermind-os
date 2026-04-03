"""monitoring.alpha_metrics — Alpha model debug metrics accumulator.

Tracks per-tick alpha model outputs and derives aggregate statistics:

  - Average edge across all recorded ticks
  - Edge distribution buckets (zero, weak, moderate, strong)
  - Zero-edge count (edge ≤ 0)
  - Signal success rate (ticks that produced a signal vs total evaluated)

``AlphaOutput`` is the canonical typed container for a single alpha
computation result, matching the ``AlphaOutput`` interface required by the
problem specification: ``{p_model, p_market, edge, confidence}``.

Thread-safety: designed for single asyncio event loop use.  Callers must
not share an instance across threads without external locking.

Usage::

    from monitoring.alpha_metrics import AlphaMetrics, AlphaOutput

    metrics = AlphaMetrics()

    # After each alpha computation:
    metrics.record(AlphaOutput(
        market_id="0xabc",
        p_model=0.55,
        p_market=0.50,
        edge=0.05,
        confidence=1.25,
        signal_generated=True,
    ))

    snap = metrics.snapshot()
    print(snap.avg_edge, snap.signal_success_rate)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

import structlog

log = structlog.get_logger(__name__)

# ── Edge bucket thresholds ─────────────────────────────────────────────────────

_EDGE_WEAK_THRESHOLD: float = 0.02      # 2 % — minimum qualifying edge
_EDGE_MODERATE_THRESHOLD: float = 0.05  # 5 %
_EDGE_STRONG_THRESHOLD: float = 0.10    # 10 %


# ── AlphaOutput ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AlphaOutput:
    """Single alpha computation result.

    Attributes:
        market_id:        Polymarket condition ID.
        p_model:          Model-estimated probability.
        p_market:         Market-implied probability (bid-ask mid).
        edge:             ``p_model - p_market`` (may be negative).
        confidence:       ``edge / volatility`` — signal-to-noise ratio.
        signal_generated: True when this output passed all filters and
                          triggered an actual trading signal.
    """

    market_id: str
    p_model: float
    p_market: float
    edge: float
    confidence: float
    signal_generated: bool = False


# ── AlphaSnapshot ─────────────────────────────────────────────────────────────


@dataclass
class AlphaSnapshot:
    """Point-in-time statistics snapshot for alpha model outputs.

    Attributes:
        total_ticks:          Total alpha computations recorded.
        zero_edge_count:      Ticks where edge ≤ 0.
        weak_edge_count:      Ticks with 0 < edge ≤ 2 % (below threshold).
        moderate_edge_count:  Ticks with 2 % < edge ≤ 5 %.
        strong_edge_count:    Ticks with edge > 5 %.
        avg_edge:             Mean edge across *all* ticks (may be ≤ 0).
        avg_positive_edge:    Mean edge across ticks where edge > 0; 0.0 if none.
        signal_success_rate:  Fraction of ticks that generated a signal.
        signals_generated:    Total ticks where ``signal_generated=True``.
        last_p_model:         Most-recent p_model value (None if no ticks).
        last_p_market:        Most-recent p_market value (None if no ticks).
        last_edge:            Most-recent edge value (None if no ticks).
        last_confidence:      Most-recent confidence score (None if no ticks).
        snapshot_ts:          Unix timestamp when this snapshot was taken.
    """

    total_ticks: int = 0
    zero_edge_count: int = 0
    weak_edge_count: int = 0
    moderate_edge_count: int = 0
    strong_edge_count: int = 0
    avg_edge: float = 0.0
    avg_positive_edge: float = 0.0
    signal_success_rate: float = 0.0
    signals_generated: int = 0
    last_p_model: Optional[float] = None
    last_p_market: Optional[float] = None
    last_edge: Optional[float] = None
    last_confidence: Optional[float] = None
    snapshot_ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        """Return a JSON-serialisable representation."""
        return {
            "total_ticks": self.total_ticks,
            "zero_edge_count": self.zero_edge_count,
            "edge_distribution": {
                "zero_or_negative": self.zero_edge_count,
                "weak_0_to_2pct": self.weak_edge_count,
                "moderate_2_to_5pct": self.moderate_edge_count,
                "strong_above_5pct": self.strong_edge_count,
            },
            "avg_edge": round(self.avg_edge, 6),
            "avg_positive_edge": round(self.avg_positive_edge, 6),
            "signal_success_rate": round(self.signal_success_rate, 4),
            "signals_generated": self.signals_generated,
            "last": {
                "p_model": self.last_p_model,
                "p_market": self.last_p_market,
                "edge": self.last_edge,
                "confidence": self.last_confidence,
            },
            "snapshot_ts": self.snapshot_ts,
        }


# ── AlphaMetrics ──────────────────────────────────────────────────────────────


class AlphaMetrics:
    """Accumulator for per-tick alpha model debug statistics.

    All mutation methods are synchronous and O(1).  Call ``snapshot()``
    at any time to obtain a frozen view of the current state.

    Call ``record()`` after every ``compute_p_model()`` invocation:

    .. code-block:: python

        output = AlphaOutput(
            market_id=market_id,
            p_model=p_model,
            p_market=p_market,
            edge=edge,
            confidence=confidence,
            signal_generated=True,
        )
        alpha_metrics.record(output)
    """

    def __init__(self) -> None:
        self._total: int = 0
        self._zero_edge: int = 0
        self._weak_edge: int = 0
        self._moderate_edge: int = 0
        self._strong_edge: int = 0
        self._edge_sum: float = 0.0
        self._positive_edge_sum: float = 0.0
        self._positive_edge_count: int = 0
        self._signals_generated: int = 0
        self._last: Optional[AlphaOutput] = None

    # ── Mutation ──────────────────────────────────────────────────────────────

    def record(self, output: AlphaOutput) -> None:
        """Record a single alpha computation result.

        Args:
            output: Typed alpha output for one market tick.
        """
        self._total += 1
        self._edge_sum += output.edge
        self._last = output

        if output.signal_generated:
            self._signals_generated += 1

        if output.edge <= 0.0:
            self._zero_edge += 1
            log.debug(
                "alpha_metrics_zero_edge",
                market_id=output.market_id,
                p_model=round(output.p_model, 4),
                p_market=round(output.p_market, 4),
                edge=round(output.edge, 6),
            )
        elif output.edge <= _EDGE_WEAK_THRESHOLD:
            self._weak_edge += 1
        elif output.edge <= _EDGE_MODERATE_THRESHOLD:
            self._moderate_edge += 1
            self._positive_edge_sum += output.edge
            self._positive_edge_count += 1
        else:
            self._strong_edge += 1
            self._positive_edge_sum += output.edge
            self._positive_edge_count += 1

        if output.edge > 0.0:
            if output.edge > _EDGE_WEAK_THRESHOLD:
                pass  # already counted above
            else:
                self._positive_edge_sum += output.edge
                self._positive_edge_count += 1

    def record_signal_generated(self) -> None:
        """Increment the signals-generated counter (lightweight; no tick recorded).

        Call this once per market tick that passes all signal filters, in
        addition to a prior :meth:`record` call for the same tick, to correctly
        track the signal success rate without double-counting edge statistics.
        """
        self._signals_generated += 1
        log.debug("alpha_metrics_signal_generated", total_signals=self._signals_generated)

    # ── Query ─────────────────────────────────────────────────────────────────

    def snapshot(self) -> AlphaSnapshot:
        """Return a frozen point-in-time snapshot of all alpha counters."""
        avg_edge = self._edge_sum / self._total if self._total > 0 else 0.0
        avg_pos_edge = (
            self._positive_edge_sum / self._positive_edge_count
            if self._positive_edge_count > 0
            else 0.0
        )
        success_rate = (
            self._signals_generated / self._total if self._total > 0 else 0.0
        )

        last = self._last
        return AlphaSnapshot(
            total_ticks=self._total,
            zero_edge_count=self._zero_edge,
            weak_edge_count=self._weak_edge,
            moderate_edge_count=self._moderate_edge,
            strong_edge_count=self._strong_edge,
            avg_edge=avg_edge,
            avg_positive_edge=avg_pos_edge,
            signal_success_rate=success_rate,
            signals_generated=self._signals_generated,
            last_p_model=round(last.p_model, 6) if last else None,
            last_p_market=round(last.p_market, 6) if last else None,
            last_edge=round(last.edge, 6) if last else None,
            last_confidence=round(last.confidence, 6) if last else None,
        )

    def log_summary(self) -> None:
        """Emit a structured info log with the current alpha metrics snapshot."""
        snap = self.snapshot()
        log.info("alpha_metrics_summary", **snap.to_dict())
