"""Risk control assertion audit layer.

Validates that every hard-wired constant and every per-profile entry in
``domain.risk.constants`` is in the correct safe range.  This module is
called by the readiness validator before any live-gate decision; it may
also be invoked directly from the /ops endpoint or from tests.

No DB reads.  No settings mutations.  Returns a typed ``RiskAuditReport``
so callers can surface issues without raising an exception.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import constants as K


@dataclass(frozen=True)
class RiskAuditViolation:
    constant: str
    expected: str
    actual: str


@dataclass
class RiskAuditReport:
    passed: bool
    violations: list[RiskAuditViolation] = field(default_factory=list)

    def add(self, constant: str, expected: str, actual: str) -> None:
        self.violations.append(RiskAuditViolation(constant, expected, actual))
        self.passed = False


def audit_risk_constants() -> RiskAuditReport:
    """Assert every hard-wired constant is in a valid, safe range.

    Returns a ``RiskAuditReport``.  ``passed=True`` means every assertion
    held; ``passed=False`` lists each violation so the operator can see
    exactly what is misconfigured.
    """
    report = RiskAuditReport(passed=True)

    # Kelly fraction: 0 < a <= 0.25 (full Kelly=1.0 is FORBIDDEN per CLAUDE.md)
    if not (0 < K.KELLY_FRACTION <= 0.25):
        report.add("KELLY_FRACTION", "0 < v <= 0.25", str(K.KELLY_FRACTION))

    # Max position pct: must be <= 10% per system spec
    if not (0 < K.MAX_POSITION_PCT <= 0.10):
        report.add("MAX_POSITION_PCT", "0 < v <= 0.10", str(K.MAX_POSITION_PCT))

    # Correlated exposure cap: 20%–60% is the sensible operating range
    if not (0.20 <= K.MAX_CORRELATED_EXPOSURE <= 0.60):
        report.add("MAX_CORRELATED_EXPOSURE", "0.20 <= v <= 0.60",
                   str(K.MAX_CORRELATED_EXPOSURE))

    # Daily loss hard stop: must be negative, at most -$2,000
    if not (-10_000 <= K.DAILY_LOSS_HARD_STOP < 0):
        report.add("DAILY_LOSS_HARD_STOP", "-10000 <= v < 0",
                   str(K.DAILY_LOSS_HARD_STOP))
    if K.DAILY_LOSS_HARD_STOP < -2_000.0:
        report.add("DAILY_LOSS_HARD_STOP", ">= -2000 (system max loss cap)",
                   str(K.DAILY_LOSS_HARD_STOP))

    # Max drawdown halt: 5%–15% is the safe design band
    if not (0.05 <= K.MAX_DRAWDOWN_HALT <= 0.15):
        report.add("MAX_DRAWDOWN_HALT", "0.05 <= v <= 0.15",
                   str(K.MAX_DRAWDOWN_HALT))

    # Min liquidity: must be >= $10,000
    if K.MIN_LIQUIDITY < 10_000.0:
        report.add("MIN_LIQUIDITY", ">= 10000", str(K.MIN_LIQUIDITY))

    # Slippage constants
    if not (0 < K.MAX_MARKET_IMPACT_PCT <= 0.10):
        report.add("MAX_MARKET_IMPACT_PCT", "0 < v <= 0.10",
                   str(K.MAX_MARKET_IMPACT_PCT))
    if not (0 < K.MAX_SLIPPAGE_PCT <= 0.10):
        report.add("MAX_SLIPPAGE_PCT", "0 < v <= 0.10", str(K.MAX_SLIPPAGE_PCT))

    # Profile audit
    for profile_name, profile in K.PROFILES.items():
        prefix = f"PROFILES[{profile_name!r}]"

        kelly = profile.get("kelly", 0)
        if not (0 < kelly <= K.KELLY_FRACTION):
            report.add(f"{prefix}.kelly",
                       f"0 < v <= KELLY_FRACTION={K.KELLY_FRACTION}",
                       str(kelly))

        max_pos = profile.get("max_pos_pct", 0)
        if not (0 < max_pos <= K.MAX_POSITION_PCT):
            report.add(f"{prefix}.max_pos_pct",
                       f"0 < v <= MAX_POSITION_PCT={K.MAX_POSITION_PCT}",
                       str(max_pos))

        daily_loss = profile.get("daily_loss", 0)
        if not (K.DAILY_LOSS_HARD_STOP <= daily_loss < 0):
            report.add(f"{prefix}.daily_loss",
                       f"DAILY_LOSS_HARD_STOP <= v < 0",
                       str(daily_loss))

        min_liq = profile.get("min_liquidity", 0)
        if min_liq < K.MIN_LIQUIDITY:
            report.add(f"{prefix}.min_liquidity",
                       f">= MIN_LIQUIDITY={K.MIN_LIQUIDITY}",
                       str(min_liq))

    return report


def assert_risk_constants() -> None:
    """Raise ``AssertionError`` if any constant is outside the safe range.

    Used as a boot-time gate; the readiness validator uses
    ``audit_risk_constants()`` for non-fatal reporting.
    """
    report = audit_risk_constants()
    if not report.passed:
        details = "; ".join(
            f"{v.constant}: expected {v.expected}, got {v.actual}"
            for v in report.violations
        )
        raise AssertionError(f"Risk constant violations: {details}")
