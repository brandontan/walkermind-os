"""Phase 24 — ValidationEngine: System-health decision layer.

Evaluates current trading metrics against hardcoded thresholds and returns
one of three states:

    HEALTHY   — all threshold conditions satisfied
    WARNING   — exactly 1 threshold violated
    CRITICAL  — 2 or more thresholds violated OR MDD exceeds hard limit

Thresholds (non-negotiable — from knowledge base):
    win_rate      ≥ 0.70
    profit_factor ≥ 1.5
    max_drawdown  ≤ 0.08

The hard MDD limit (0.08) maps directly to the system-wide 8% max drawdown
rule defined in CLAUDE.md.  Any breach always produces CRITICAL regardless of
other metrics.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

log = structlog.get_logger()

# ── Thresholds ────────────────────────────────────────────────────────────────

_MIN_WIN_RATE: float = 0.70
_MIN_PROFIT_FACTOR: float = 1.5
_MAX_DRAWDOWN: float = 0.08  # hard system limit (8%)


# ── State ────────────────────────────────────────────────────────────────────

class ValidationState(str, Enum):
    """System-health states produced by ValidationEngine."""

    HEALTHY = "HEALTHY"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass
class ValidationResult:
    """Result of a single evaluation run.

    Attributes:
        state:   Computed health state.
        reasons: Human-readable list of every violated condition.
    """

    state: ValidationState
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return {
            "state": self.state.value,
            "reasons": self.reasons,
        }


# ── Engine ────────────────────────────────────────────────────────────────────

class ValidationEngine:
    """Decision layer that maps metric values to a ValidationState.

    Usage::

        engine = ValidationEngine()
        result = engine.evaluate(metrics)
        if result.state == ValidationState.CRITICAL:
            # trigger risk response
    """

    def evaluate(self, metrics: dict[str, float]) -> ValidationResult:
        """Evaluate metrics and return the system health state.

        Args:
            metrics: Dict produced by ``MetricsEngine.compute()``.  Expected
                     keys: ``win_rate``, ``profit_factor``, ``max_drawdown``.
                     Missing keys are treated as 0.0 / threshold-violating.

        Returns:
            :class:`ValidationResult` with ``state`` and ``reasons``.
        """
        win_rate: float = float(metrics.get("win_rate", 0.0))
        profit_factor: float = float(metrics.get("profit_factor", 0.0))
        max_drawdown: float = float(metrics.get("max_drawdown", 0.0))

        reasons: list[str] = []

        # ── Check individual thresholds ───────────────────────────────────────
        if win_rate < _MIN_WIN_RATE:
            reasons.append(
                f"win_rate {win_rate:.4f} < required {_MIN_WIN_RATE:.4f}"
            )

        if profit_factor < _MIN_PROFIT_FACTOR:
            reasons.append(
                f"profit_factor {profit_factor:.4f} < required {_MIN_PROFIT_FACTOR:.4f}"
            )

        if max_drawdown > _MAX_DRAWDOWN:
            reasons.append(
                f"max_drawdown {max_drawdown:.4f} > limit {_MAX_DRAWDOWN:.4f}"
            )

        # ── Determine state ───────────────────────────────────────────────────
        # Hard MDD breach always produces CRITICAL (overrides count-based logic)
        if max_drawdown > _MAX_DRAWDOWN:
            state = ValidationState.CRITICAL
        elif len(reasons) >= 2:
            state = ValidationState.CRITICAL
        elif len(reasons) == 1:
            state = ValidationState.WARNING
        else:
            state = ValidationState.HEALTHY

        result = ValidationResult(state=state, reasons=reasons)

        log.info(
            "validation_engine_evaluated",
            state=state.value,
            violations=len(reasons),
            win_rate=round(win_rate, 6),
            profit_factor=round(profit_factor, 6),
            max_drawdown=round(max_drawdown, 6),
            reasons=reasons,
        )

        return result
