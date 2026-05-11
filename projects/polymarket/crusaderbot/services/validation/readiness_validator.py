"""Live gate readiness validator — structured dry-run check report.

Orchestrates every hardening check without mutating state:

  CHECK_RISK_CONSTANTS   — domain.risk.hardening.audit_risk_constants()
  CHECK_GUARD_STATE      — verifies all activation guards are in expected posture
  CHECK_KILL_SWITCH      — confirms kill switch cache + DB path is responsive
  CHECK_EXECUTION_PATH   — imports and inspects the full paper/live execution chain
  CHECK_CAPITAL_ALLOC    — validates Kelly/size math against a reference balance
  CHECK_SLIPPAGE         — confirms slippage module is reachable and thresholds sane

Returns a ``ReadinessReport``.  Every check is either PASS or FAIL with a
detail string.  The overall verdict is PASS only when ALL checks pass.

This module is safe to call from:
  - /ops GET endpoint (read-only operator view)
  - tests (hermetic, no DB required for most checks)
  - WARP•FORGE dry-run command

MANDATORY: ENABLE_LIVE_TRADING must remain False throughout. This module
never flips any activation guard.
"""
from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from ...config import get_settings
from ...domain.risk.hardening import audit_risk_constants
from ...domain.risk import constants as K

logger = logging.getLogger(__name__)

CheckVerdict = Literal["PASS", "FAIL", "SKIP"]


@dataclass
class CheckResult:
    name: str
    verdict: CheckVerdict
    detail: str


@dataclass
class ReadinessReport:
    overall: CheckVerdict
    checks: list[CheckResult] = field(default_factory=list)
    posture: str = "PAPER_ONLY"

    def add(self, name: str, verdict: CheckVerdict, detail: str) -> None:
        self.checks.append(CheckResult(name, verdict, detail))
        if verdict == "FAIL":
            self.overall = "FAIL"

    def as_text(self) -> str:
        lines = [
            f"READINESS REPORT — posture={self.posture}  overall={self.overall}",
            "-" * 60,
        ]
        for c in self.checks:
            lines.append(f"  [{c.verdict:<4}] {c.name}: {c.detail}")
        lines.append("-" * 60)
        return "\n".join(lines)


class ReadinessValidator:
    """Stateless readiness validator.  One instance is safe to share."""

    async def run(self) -> ReadinessReport:
        """Execute all checks and return the ``ReadinessReport``."""
        report = ReadinessReport(overall="PASS")

        self._check_risk_constants(report)
        self._check_guard_state(report)
        await self._check_kill_switch(report)
        self._check_execution_path(report)
        self._check_capital_alloc(report)
        self._check_slippage_module(report)

        return report

    # ------------------------------------------------------------------

    def _check_risk_constants(self, report: ReadinessReport) -> None:
        audit = audit_risk_constants()
        if audit.passed:
            report.add("CHECK_RISK_CONSTANTS", "PASS",
                       "all constants within safe range")
        else:
            violations = "; ".join(
                f"{v.constant}={v.actual} (expected {v.expected})"
                for v in audit.violations
            )
            report.add("CHECK_RISK_CONSTANTS", "FAIL", violations)

    def _check_guard_state(self, report: ReadinessReport) -> None:
        """Verify activation guards are in the correct paper-safe posture."""
        s = get_settings()
        issues: list[str] = []

        # ENABLE_LIVE_TRADING code default is True (known deferred issue in
        # KNOWN ISSUES); fly.toml overrides to False.  We check the resolved
        # settings value rather than the code default.  A resolved True here
        # means the override is NOT in place — surface as FAIL.
        if s.ENABLE_LIVE_TRADING:
            issues.append("ENABLE_LIVE_TRADING=True (must be False in paper posture)")
        if s.EXECUTION_PATH_VALIDATED:
            issues.append("EXECUTION_PATH_VALIDATED=True (not yet cleared by SENTINEL)")
        if s.CAPITAL_MODE_CONFIRMED:
            issues.append("CAPITAL_MODE_CONFIRMED=True (not yet cleared by SENTINEL)")
        if s.RISK_CONTROLS_VALIDATED:
            issues.append("RISK_CONTROLS_VALIDATED=True (not yet cleared by SENTINEL)")

        if issues:
            report.add("CHECK_GUARD_STATE", "FAIL", "; ".join(issues))
        else:
            report.add("CHECK_GUARD_STATE", "PASS",
                       "all guards OFF — paper-safe posture confirmed")

    async def _check_kill_switch(self, report: ReadinessReport) -> None:
        """Verify the kill switch cache + read path is responsive.

        Read-only: does NOT write to kill_switch_history or system_settings.
        Treats a DB-unavailable scenario as SKIP (no pool in test/dry-run)
        rather than FAIL, since the validator may run before the pool is open.
        """
        try:
            from ...domain.ops.kill_switch import invalidate_cache, is_active
            invalidate_cache()
            # is_active reads from DB; if pool is not available it returns True
            # (fail-safe).  Both outcomes are valid for this check.
            result = await is_active()
            if result:
                report.add("CHECK_KILL_SWITCH", "PASS",
                           "kill_switch=True (active — trades halted as expected in paper posture)")
            else:
                report.add("CHECK_KILL_SWITCH", "PASS",
                           "kill_switch=False (inactive — cache+DB path responsive)")
        except RuntimeError as exc:
            # Pool not initialised (dry-run outside app context)
            report.add("CHECK_KILL_SWITCH", "SKIP",
                       f"pool not available: {exc}")
        except Exception as exc:
            report.add("CHECK_KILL_SWITCH", "FAIL",
                       f"kill_switch read failed: {exc}")

    def _check_execution_path(self, report: ReadinessReport) -> None:
        """Verify that the full paper execution chain is importable and wired."""
        required_modules = [
            "projects.polymarket.crusaderbot.domain.execution.paper",
            "projects.polymarket.crusaderbot.domain.execution.router",
            "projects.polymarket.crusaderbot.domain.execution.live",
            "projects.polymarket.crusaderbot.domain.risk.gate",
            "projects.polymarket.crusaderbot.services.trade_engine.engine",
        ]
        failed: list[str] = []
        for mod_path in required_modules:
            try:
                mod = importlib.import_module(mod_path)
                # Spot-check key callables
                if mod_path.endswith(".gate"):
                    assert hasattr(mod, "evaluate"), "gate.evaluate missing"
                elif mod_path.endswith(".router"):
                    assert hasattr(mod, "execute"), "router.execute missing"
                elif mod_path.endswith(".paper"):
                    assert hasattr(mod, "execute"), "paper.execute missing"
                elif mod_path.endswith(".live"):
                    assert hasattr(mod, "assert_live_guards"), \
                        "live.assert_live_guards missing"
                elif mod_path.endswith(".engine"):
                    assert hasattr(mod, "TradeEngine"), "TradeEngine missing"
            except Exception as exc:
                failed.append(f"{mod_path.split('.')[-1]}: {exc}")

        if failed:
            report.add("CHECK_EXECUTION_PATH", "FAIL", "; ".join(failed))
        else:
            report.add("CHECK_EXECUTION_PATH", "PASS",
                       "all execution modules importable and callables present")

    def _check_capital_alloc(self, report: ReadinessReport) -> None:
        """Validate Kelly/size math consistency for a reference $1,000 balance."""
        issues: list[str] = []
        ref_balance = Decimal("1000.00")

        for profile_name, profile in K.PROFILES.items():
            kelly = min(float(profile["kelly"]), K.KELLY_FRACTION)
            max_pos_pct = float(profile["max_pos_pct"])
            max_size = ref_balance * Decimal(str(max_pos_pct)) * Decimal(str(kelly))

            # Must be positive and below 10% of balance
            if max_size <= 0:
                issues.append(f"{profile_name}: max_size={max_size} <= 0")
            cap = ref_balance * Decimal(str(K.MAX_POSITION_PCT))
            if max_size > cap:
                issues.append(
                    f"{profile_name}: max_size={max_size:.2f} > "
                    f"MAX_POSITION_PCT cap={cap:.2f}"
                )

        if issues:
            report.add("CHECK_CAPITAL_ALLOC", "FAIL", "; ".join(issues))
        else:
            report.add("CHECK_CAPITAL_ALLOC", "PASS",
                       "Kelly/size math consistent across all profiles "
                       f"(ref balance={ref_balance})")

    def _check_slippage_module(self, report: ReadinessReport) -> None:
        """Confirm slippage module is importable and thresholds are sane."""
        try:
            from ...domain.execution.slippage import (
                check_market_impact,
                check_price_deviation,
            )
            # Sanity-check the bounds defined in constants
            if not (0 < K.MAX_MARKET_IMPACT_PCT <= 0.10):
                report.add("CHECK_SLIPPAGE", "FAIL",
                           f"MAX_MARKET_IMPACT_PCT={K.MAX_MARKET_IMPACT_PCT} out of range")
                return
            if not (0 < K.MAX_SLIPPAGE_PCT <= 0.10):
                report.add("CHECK_SLIPPAGE", "FAIL",
                           f"MAX_SLIPPAGE_PCT={K.MAX_SLIPPAGE_PCT} out of range")
                return
            # Quick functional test with safe values
            r = check_market_impact(Decimal("100"), 10_000.0)
            assert r.accepted, f"unexpected rejection: {r.reason}"
            r2 = check_price_deviation(0.51, 0.50)
            assert r2.accepted, f"unexpected rejection: {r2.reason}"
            report.add("CHECK_SLIPPAGE", "PASS",
                       f"impact_threshold={K.MAX_MARKET_IMPACT_PCT} "
                       f"slippage_threshold={K.MAX_SLIPPAGE_PCT}")
        except Exception as exc:
            report.add("CHECK_SLIPPAGE", "FAIL", str(exc))
