"""Phase 24 — ValidationEngine maps metrics to HEALTHY/WARNING/CRITICAL."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ValidationState(Enum):
    HEALTHY = "HEALTHY"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(slots=True)
class ValidationResult:
    state: ValidationState
    reasons: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "reasons": list(self.reasons),
        }


class ValidationEngine:
    """Applies validation thresholds to a metrics snapshot."""

    _MIN_WIN_RATE: float = 0.70
    _MIN_PROFIT_FACTOR: float = 1.50
    _MAX_DRAWDOWN_WARNING: float = 0.06
    _MAX_DRAWDOWN_CRITICAL: float = 0.08

    def evaluate(self, metrics: dict[str, float]) -> ValidationResult:
        trade_count = metrics.get("trade_count", 0)
        if trade_count < 30:
            return ValidationResult(
                state=ValidationState.INSUFFICIENT_DATA,
                reasons=["minimum 30 trades required"],
            )

        reasons: list[str] = []
        violations = 0

        win_rate = float(metrics.get("win_rate", 0.0))
        if win_rate < self._MIN_WIN_RATE:
            violations += 1
            reasons.append(f"win_rate below minimum: {win_rate:.2f} < {self._MIN_WIN_RATE:.2f}")

        profit_factor = float(metrics.get("profit_factor", 0.0))
        if profit_factor < self._MIN_PROFIT_FACTOR:
            violations += 1
            reasons.append(
                f"profit_factor below minimum: {profit_factor:.2f} < {self._MIN_PROFIT_FACTOR:.2f}"
            )

        max_drawdown = float(metrics.get("max_drawdown", 0.0))
        if max_drawdown > self._MAX_DRAWDOWN_CRITICAL:
            reasons.append(
                f"max_drawdown exceeds hard limit: {max_drawdown:.2%} > {self._MAX_DRAWDOWN_CRITICAL:.2%}"
            )
            return ValidationResult(state=ValidationState.CRITICAL, reasons=reasons)

        if max_drawdown > self._MAX_DRAWDOWN_WARNING:
            violations += 1
            reasons.append(
                f"max_drawdown above warning: {max_drawdown:.2%} > {self._MAX_DRAWDOWN_WARNING:.2%}"
            )

        if violations == 0:
            return ValidationResult(state=ValidationState.HEALTHY, reasons=[])
        if violations == 1:
            return ValidationResult(state=ValidationState.WARNING, reasons=reasons)
        return ValidationResult(state=ValidationState.CRITICAL, reasons=reasons)
