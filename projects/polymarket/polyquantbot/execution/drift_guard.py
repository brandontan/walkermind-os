from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DriftCheckResult:
    """Result of execution price drift boundary validation."""

    allowed: bool
    drift_ratio: float
    max_drift_ratio: float


def evaluate_execution_price_drift(
    *,
    expected_price: float,
    execution_price: float,
    max_drift_ratio: float,
) -> DriftCheckResult:
    """Evaluate execution drift ratio using absolute deviation from expected price.

    This helper is intentionally narrow: it only computes and classifies drift.
    Enforcement and order lifecycle decisions are handled in engine/runtime callers.
    """
    if expected_price <= 0.0:
        raise ValueError("expected_price must be > 0")
    if max_drift_ratio < 0.0:
        raise ValueError("max_drift_ratio must be >= 0")

    drift_ratio = abs(float(execution_price) - float(expected_price)) / float(expected_price)
    return DriftCheckResult(
        allowed=drift_ratio <= float(max_drift_ratio),
        drift_ratio=drift_ratio,
        max_drift_ratio=float(max_drift_ratio),
    )
