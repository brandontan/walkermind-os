"""Drift detection module for PolyQuantBot intelligence layer.

Detects when a market's probability has drifted significantly from its recent
baseline, signalling a regime change that may invalidate existing strategies.

Drift is measured using a CUSUM (cumulative sum) algorithm against an EWMA baseline.
When drift exceeds a configurable threshold the detector raises an alert and
downstream strategies can reduce position sizes or skip signals.

Usage::

    from projects.polymarket.polyquantbot.intelligence.drift import DriftDetector

    detector = DriftDetector(threshold=0.10)
    result = detector.update(mid_price)

    if result.drift_detected:
        # Reduce confidence or skip signal
        pass
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import structlog

log = structlog.get_logger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_DEFAULT_THRESHOLD: float = 0.10        # 10% cumulative drift triggers alert
_DEFAULT_EWMA_ALPHA: float = 0.05       # slow-moving baseline
_DEFAULT_CUSUM_RESET_ON_DETECT: bool = True
_WARMUP_TICKS: int = 20
_DRIFT_PENALTY_FACTOR: float = 0.2  # confidence reduction per unit of drift magnitude above threshold


@dataclass
class DriftResult:
    """Result of a single drift-detector update."""

    mid: float
    baseline: float
    cusum_pos: float        # positive cumulative sum (upward drift)
    cusum_neg: float        # negative cumulative sum (downward drift)
    drift_detected: bool
    drift_direction: Optional[str]  # "up" | "down" | None
    confidence_multiplier: float    # 1.0 when no drift, < 1.0 when drifting


class DriftDetector:
    """CUSUM-based market drift detector.

    Maintains a slow EWMA baseline and two CUSUM accumulators (positive and
    negative). When either CUSUM exceeds ``threshold``, drift is flagged and
    a reduced ``confidence_multiplier`` is returned.

    Args:
        threshold: Cumulative drift magnitude that triggers detection.
        ewma_alpha: EWMA smoothing factor for the baseline (lower = slower).
        reset_on_detect: Whether to reset CUSUM accumulators on detection.
        min_confidence: Minimum confidence multiplier emitted when drift detected.
    """

    def __init__(
        self,
        threshold: float = _DEFAULT_THRESHOLD,
        ewma_alpha: float = _DEFAULT_EWMA_ALPHA,
        reset_on_detect: bool = _DEFAULT_CUSUM_RESET_ON_DETECT,
        min_confidence: float = 0.3,
    ) -> None:
        self._threshold = threshold
        self._alpha = max(1e-4, min(1.0, ewma_alpha))
        self._reset_on_detect = reset_on_detect
        self._min_confidence = min_confidence
        self._baseline: Optional[float] = None
        self._cusum_pos: float = 0.0
        self._cusum_neg: float = 0.0
        self._tick_count: int = 0

    @property
    def is_ready(self) -> bool:
        """Return True once the baseline has been established."""
        return self._tick_count >= _WARMUP_TICKS

    def update(self, mid: float) -> DriftResult:
        """Update the detector with a new mid price and return the drift result.

        Args:
            mid: Current market mid price (0 < mid < 1 for Polymarket).

        Returns:
            DriftResult with drift flag and confidence multiplier.
        """
        # Initialise baseline on first tick
        if self._baseline is None:
            self._baseline = mid
            self._tick_count += 1
            return DriftResult(
                mid=mid,
                baseline=mid,
                cusum_pos=0.0,
                cusum_neg=0.0,
                drift_detected=False,
                drift_direction=None,
                confidence_multiplier=1.0,
            )

        # Update EWMA baseline
        self._baseline = self._alpha * mid + (1.0 - self._alpha) * self._baseline
        baseline = self._baseline
        self._tick_count += 1

        # CUSUM update
        deviation = mid - baseline
        self._cusum_pos = max(0.0, self._cusum_pos + deviation)
        self._cusum_neg = max(0.0, self._cusum_neg - deviation)

        # Drift detection
        drift_detected = False
        drift_direction: Optional[str] = None

        if not self.is_ready:
            return DriftResult(
                mid=round(mid, 4),
                baseline=round(baseline, 4),
                cusum_pos=round(self._cusum_pos, 4),
                cusum_neg=round(self._cusum_neg, 4),
                drift_detected=False,
                drift_direction=None,
                confidence_multiplier=1.0,
            )

        if self._cusum_pos >= self._threshold:
            drift_detected = True
            drift_direction = "up"
            log.warning(
                "drift.detected",
                direction="up",
                cusum=round(self._cusum_pos, 4),
                threshold=self._threshold,
                mid=round(mid, 4),
                baseline=round(baseline, 4),
            )
            if self._reset_on_detect:
                self._cusum_pos = 0.0

        elif self._cusum_neg >= self._threshold:
            drift_detected = True
            drift_direction = "down"
            log.warning(
                "drift.detected",
                direction="down",
                cusum=round(self._cusum_neg, 4),
                threshold=self._threshold,
                mid=round(mid, 4),
                baseline=round(baseline, 4),
            )
            if self._reset_on_detect:
                self._cusum_neg = 0.0

        # Confidence multiplier: full confidence when no drift; reduced on drift
        if drift_detected:
            magnitude = max(self._cusum_pos, self._cusum_neg) / max(self._threshold, 1e-6)
            confidence_multiplier = max(
                self._min_confidence,
                1.0 - min(1.0 - self._min_confidence, magnitude * _DRIFT_PENALTY_FACTOR),
            )
        else:
            confidence_multiplier = 1.0

        return DriftResult(
            mid=round(mid, 4),
            baseline=round(baseline, 4),
            cusum_pos=round(self._cusum_pos, 4),
            cusum_neg=round(self._cusum_neg, 4),
            drift_detected=drift_detected,
            drift_direction=drift_direction,
            confidence_multiplier=round(confidence_multiplier, 4),
        )

    def reset(self) -> None:
        """Reset CUSUM accumulators (preserve baseline)."""
        self._cusum_pos = 0.0
        self._cusum_neg = 0.0
        log.info("drift.reset")

    def to_dict(self) -> dict:
        """Serialise state for logging or persistence."""
        return {
            "baseline": round(self._baseline, 4) if self._baseline is not None else None,
            "cusum_pos": round(self._cusum_pos, 4),
            "cusum_neg": round(self._cusum_neg, 4),
            "threshold": self._threshold,
            "tick_count": self._tick_count,
            "is_ready": self.is_ready,
        }
