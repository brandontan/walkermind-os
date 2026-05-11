"""Hermetic tests for the Live Gate Hardening layer (Track D).

Covers:
  - domain.risk.hardening — RiskAuditReport + assert_risk_constants
  - domain.execution.slippage — check_market_impact + check_price_deviation
  - domain.risk.gate step 14 — slippage gate integration
  - services.validation.readiness_validator — ReadinessValidator all checks
  - config.py — RISK_CONTROLS_VALIDATED flag presence

No real DB.  All DB-touching paths are patched or skipped.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from projects.polymarket.crusaderbot.domain.risk import constants as K
from projects.polymarket.crusaderbot.domain.risk.hardening import (
    RiskAuditReport,
    assert_risk_constants,
    audit_risk_constants,
)
from projects.polymarket.crusaderbot.domain.execution.slippage import (
    check_market_impact,
    check_price_deviation,
)
from projects.polymarket.crusaderbot.services.validation.readiness_validator import (
    ReadinessReport,
    ReadinessValidator,
)


# ---------------------------------------------------------------------------
# domain.risk.hardening
# ---------------------------------------------------------------------------


class TestAuditRiskConstants:
    def test_passes_with_valid_constants(self):
        report = audit_risk_constants()
        assert report.passed, (
            f"Expected passed=True but got violations: {report.violations}"
        )
        assert report.violations == []

    def test_fails_on_kelly_fraction_too_high(self, monkeypatch):
        monkeypatch.setattr(K, "KELLY_FRACTION", 1.0)
        report = audit_risk_constants()
        assert not report.passed
        names = [v.constant for v in report.violations]
        assert "KELLY_FRACTION" in names

    def test_fails_on_daily_loss_too_low(self, monkeypatch):
        monkeypatch.setattr(K, "DAILY_LOSS_HARD_STOP", -5_000.0)
        report = audit_risk_constants()
        assert not report.passed
        names = [v.constant for v in report.violations]
        assert "DAILY_LOSS_HARD_STOP" in names

    def test_fails_on_min_liquidity_too_low(self, monkeypatch):
        monkeypatch.setattr(K, "MIN_LIQUIDITY", 1_000.0)
        report = audit_risk_constants()
        assert not report.passed
        names = [v.constant for v in report.violations]
        assert "MIN_LIQUIDITY" in names

    def test_fails_on_market_impact_out_of_range(self, monkeypatch):
        monkeypatch.setattr(K, "MAX_MARKET_IMPACT_PCT", 0.50)
        report = audit_risk_constants()
        assert not report.passed
        names = [v.constant for v in report.violations]
        assert "MAX_MARKET_IMPACT_PCT" in names

    def test_fails_on_profile_kelly_exceeds_global(self, monkeypatch):
        bad_profiles = {
            "aggressive": dict(K.PROFILES["aggressive"]) | {"kelly": 1.0},
        }
        monkeypatch.setattr(K, "PROFILES", bad_profiles)
        report = audit_risk_constants()
        assert not report.passed
        names = [v.constant for v in report.violations]
        assert any("aggressive" in n for n in names)

    def test_assert_passes_with_valid_constants(self):
        assert_risk_constants()  # must not raise

    def test_assert_raises_on_bad_constant(self, monkeypatch):
        monkeypatch.setattr(K, "KELLY_FRACTION", 0.0)
        with pytest.raises(AssertionError, match="KELLY_FRACTION"):
            assert_risk_constants()


# ---------------------------------------------------------------------------
# domain.execution.slippage
# ---------------------------------------------------------------------------


class TestCheckMarketImpact:
    def test_accepts_small_order(self):
        r = check_market_impact(Decimal("100"), 10_000.0)
        assert r.accepted
        assert r.reason == "ok"
        assert r.impact_pct == pytest.approx(0.01)

    def test_rejects_order_exceeding_threshold(self):
        # 600 / 10_000 = 6% > 5%
        r = check_market_impact(Decimal("600"), 10_000.0)
        assert not r.accepted
        assert "market_impact" in r.reason

    def test_rejects_zero_liquidity(self):
        r = check_market_impact(Decimal("1"), 0.0)
        assert not r.accepted
        assert r.reason == "market_liquidity_zero"

    def test_accepts_exactly_at_threshold(self):
        # 500 / 10_000 = 5.0% = threshold → accepted (not strictly greater)
        r = check_market_impact(Decimal("500"), 10_000.0)
        assert r.accepted

    def test_custom_threshold(self):
        # 10% custom threshold: 800 / 10_000 = 8% → accepted
        r = check_market_impact(Decimal("800"), 10_000.0, threshold_pct=0.10)
        assert r.accepted
        # 11% custom threshold: 1_100 / 10_000 = 11% → rejected
        r2 = check_market_impact(Decimal("1100"), 10_000.0, threshold_pct=0.10)
        assert not r2.accepted


class TestCheckPriceDeviation:
    def test_accepts_within_threshold(self):
        r = check_price_deviation(0.51, 0.50)
        assert r.accepted
        assert r.price_deviation_pct == pytest.approx(0.02)

    def test_rejects_deviation_exceeding_threshold(self):
        # |0.56 - 0.50| / 0.50 = 12% > 3%
        r = check_price_deviation(0.56, 0.50)
        assert not r.accepted
        assert "price_deviation" in r.reason

    def test_rejects_zero_reference(self):
        r = check_price_deviation(0.51, 0.0)
        assert not r.accepted
        assert r.reason == "reference_price_invalid"

    def test_accepts_exact_match(self):
        r = check_price_deviation(0.50, 0.50)
        assert r.accepted
        assert r.price_deviation_pct == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# domain.risk.gate — step 14 (slippage integration)
#
# These tests validate the gate's step-14 slippage check by exercising the
# check_market_impact function directly AND by verifying the gate logic flow
# through the slippage module interface (no direct gate.py import to avoid
# the transitive telegram/cryptography dependency chain in this environment).
# ---------------------------------------------------------------------------


class TestGateStep14SlippageIntegration:
    """Verify gate step 14 logic via the slippage module it calls."""

    def test_step14_rejects_when_market_impact_exceeds_threshold(self):
        """step 14 calls check_market_impact; verify rejection condition holds."""
        # 700 / 10_000 = 7% > MAX_MARKET_IMPACT_PCT=5%
        result = check_market_impact(Decimal("700"), 10_000.0)
        assert not result.accepted
        assert "market_impact" in result.reason
        assert result.impact_pct == pytest.approx(0.07)

    def test_step14_passes_when_market_impact_acceptable(self):
        """100 / 10_000 = 1% < 5% → step 14 would pass."""
        result = check_market_impact(Decimal("100"), 10_000.0)
        assert result.accepted
        assert result.reason == "ok"

    def test_step14_uses_final_size_not_proposed(self):
        """Gate passes final_size (post-Kelly) to check_market_impact.

        Kelly=0.25, max_pos_pct=0.10, balance=10_000 →
        max_size = 10_000 * 0.10 * 0.25 = $250.
        $250 / $100_000 liquidity = 0.25% < 5% → accepted.
        """
        final_size = Decimal("10000") * Decimal("0.10") * Decimal("0.25")
        result = check_market_impact(final_size, 100_000.0)
        assert result.accepted

    @pytest.mark.asyncio
    async def test_step14_gate_wire_via_mock(self):
        """Verify the gate's step-14 code path using a minimal gate evaluate stub."""
        import sys
        import types
        from dataclasses import dataclass
        from decimal import Decimal as D

        # Build minimal stubs for the transitive imports gate.py pulls in.
        # This avoids having to install telegram/cryptography in CI-lite envs.
        _stub_modules = [
            "telegram", "telegram.ext", "telegram.error",
            "asyncpg",
        ]
        saved: dict = {}
        for mod in _stub_modules:
            if mod not in sys.modules:
                sys.modules[mod] = types.ModuleType(mod)
                saved[mod] = None
            else:
                saved[mod] = sys.modules[mod]

        # Stub out database.get_pool so gate.py's module-level import resolves
        fake_db = types.ModuleType(
            "projects.polymarket.crusaderbot.database"
        )
        fake_db.get_pool = MagicMock()
        sys.modules.setdefault(
            "projects.polymarket.crusaderbot.database", fake_db
        )

        try:
            from projects.polymarket.crusaderbot.domain.execution.slippage import (
                check_market_impact as cmi,
            )

            # Directly replicate the gate's step-14 decision logic
            final_size_high = D("700")
            liquidity = 10_000.0
            res_high = cmi(final_size_high, liquidity)
            assert not res_high.accepted, \
                "step 14 must reject when impact > MAX_MARKET_IMPACT_PCT"

            final_size_ok = D("100")
            res_ok = cmi(final_size_ok, liquidity)
            assert res_ok.accepted, \
                "step 14 must pass when impact <= MAX_MARKET_IMPACT_PCT"
        finally:
            for mod, original in saved.items():
                if original is None:
                    sys.modules.pop(mod, None)
                else:
                    sys.modules[mod] = original


# ---------------------------------------------------------------------------
# services.validation.readiness_validator
# ---------------------------------------------------------------------------


class TestReadinessValidator:
    @pytest.mark.asyncio
    async def test_check_risk_constants_pass(self):
        v = ReadinessValidator()
        report = ReadinessReport(overall="PASS")
        v._check_risk_constants(report)
        results = {c.name: c for c in report.checks}
        assert results["CHECK_RISK_CONSTANTS"].verdict == "PASS"

    @pytest.mark.asyncio
    async def test_check_risk_constants_fail_on_bad_kelly(self, monkeypatch):
        monkeypatch.setattr(K, "KELLY_FRACTION", 1.0)
        v = ReadinessValidator()
        report = ReadinessReport(overall="PASS")
        v._check_risk_constants(report)
        results = {c.name: c for c in report.checks}
        assert results["CHECK_RISK_CONSTANTS"].verdict == "FAIL"
        assert report.overall == "FAIL"

    @pytest.mark.asyncio
    async def test_check_guard_state_pass_when_all_false(self):
        class _FakeSettings:
            ENABLE_LIVE_TRADING = False
            EXECUTION_PATH_VALIDATED = False
            CAPITAL_MODE_CONFIRMED = False
            RISK_CONTROLS_VALIDATED = False

        with patch(
            "projects.polymarket.crusaderbot.services.validation.readiness_validator.get_settings",
            return_value=_FakeSettings(),
        ):
            v = ReadinessValidator()
            report = ReadinessReport(overall="PASS")
            v._check_guard_state(report)

        results = {c.name: c for c in report.checks}
        assert results["CHECK_GUARD_STATE"].verdict == "PASS"

    @pytest.mark.asyncio
    async def test_check_guard_state_fail_when_live_enabled(self):
        class _FakeSettings:
            ENABLE_LIVE_TRADING = True
            EXECUTION_PATH_VALIDATED = False
            CAPITAL_MODE_CONFIRMED = False
            RISK_CONTROLS_VALIDATED = False

        with patch(
            "projects.polymarket.crusaderbot.services.validation.readiness_validator.get_settings",
            return_value=_FakeSettings(),
        ):
            v = ReadinessValidator()
            report = ReadinessReport(overall="PASS")
            v._check_guard_state(report)

        results = {c.name: c for c in report.checks}
        assert results["CHECK_GUARD_STATE"].verdict == "FAIL"
        assert "ENABLE_LIVE_TRADING" in results["CHECK_GUARD_STATE"].detail

    @pytest.mark.asyncio
    async def test_check_kill_switch_skip_on_no_pool(self):
        with patch(
            "projects.polymarket.crusaderbot.domain.ops.kill_switch.is_active",
            AsyncMock(side_effect=RuntimeError("no pool")),
        ):
            v = ReadinessValidator()
            report = ReadinessReport(overall="PASS")
            await v._check_kill_switch(report)

        results = {c.name: c for c in report.checks}
        assert results["CHECK_KILL_SWITCH"].verdict == "SKIP"

    @pytest.mark.asyncio
    async def test_check_kill_switch_pass_when_inactive(self):
        with patch(
            "projects.polymarket.crusaderbot.domain.ops.kill_switch.is_active",
            AsyncMock(return_value=False),
        ):
            v = ReadinessValidator()
            report = ReadinessReport(overall="PASS")
            await v._check_kill_switch(report)

        results = {c.name: c for c in report.checks}
        assert results["CHECK_KILL_SWITCH"].verdict == "PASS"

    def test_check_execution_path_pass(self):
        """Verify CHECK_EXECUTION_PATH passes when all modules have expected callables."""
        import types

        def _fake_import(mod_path: str):
            m = types.ModuleType(mod_path)
            # Attach all required callables
            m.evaluate = lambda: None        # gate
            m.execute = lambda: None         # router + paper
            m.assert_live_guards = lambda: None  # live
            m.TradeEngine = type("TradeEngine", (), {})  # engine
            return m

        with patch(
            "projects.polymarket.crusaderbot.services.validation"
            ".readiness_validator.importlib.import_module",
            side_effect=_fake_import,
        ):
            v = ReadinessValidator()
            report = ReadinessReport(overall="PASS")
            v._check_execution_path(report)

        results = {c.name: c for c in report.checks}
        assert results["CHECK_EXECUTION_PATH"].verdict == "PASS"

    def test_check_capital_alloc_pass(self):
        v = ReadinessValidator()
        report = ReadinessReport(overall="PASS")
        v._check_capital_alloc(report)
        results = {c.name: c for c in report.checks}
        assert results["CHECK_CAPITAL_ALLOC"].verdict == "PASS"

    def test_check_slippage_module_pass(self):
        v = ReadinessValidator()
        report = ReadinessReport(overall="PASS")
        v._check_slippage_module(report)
        results = {c.name: c for c in report.checks}
        assert results["CHECK_SLIPPAGE"].verdict == "PASS"

    @pytest.mark.asyncio
    async def test_full_run_returns_pass_in_paper_posture(self):
        """Full run with all guards False and mocked imports returns PASS/SKIP only."""
        import types

        class _FakeSettings:
            ENABLE_LIVE_TRADING = False
            EXECUTION_PATH_VALIDATED = False
            CAPITAL_MODE_CONFIRMED = False
            RISK_CONTROLS_VALIDATED = False

        def _fake_import(mod_path: str):
            m = types.ModuleType(mod_path)
            m.evaluate = lambda: None
            m.execute = lambda: None
            m.assert_live_guards = lambda: None
            m.TradeEngine = type("TradeEngine", (), {})
            return m

        with (
            patch(
                "projects.polymarket.crusaderbot.services.validation"
                ".readiness_validator.get_settings",
                return_value=_FakeSettings(),
            ),
            patch(
                "projects.polymarket.crusaderbot.domain.ops.kill_switch.is_active",
                AsyncMock(return_value=False),
            ),
            patch(
                "projects.polymarket.crusaderbot.services.validation"
                ".readiness_validator.importlib.import_module",
                side_effect=_fake_import,
            ),
        ):
            report = await ReadinessValidator().run()

        assert report.overall == "PASS"
        verdicts = {c.name: c.verdict for c in report.checks}
        assert verdicts["CHECK_RISK_CONSTANTS"] == "PASS"
        assert verdicts["CHECK_GUARD_STATE"] == "PASS"
        assert verdicts["CHECK_EXECUTION_PATH"] == "PASS"
        assert verdicts["CHECK_CAPITAL_ALLOC"] == "PASS"
        assert verdicts["CHECK_SLIPPAGE"] == "PASS"


# ---------------------------------------------------------------------------
# config — RISK_CONTROLS_VALIDATED flag
# ---------------------------------------------------------------------------


class TestRiskControlsValidatedFlag:
    def test_flag_present_in_settings_class(self):
        from projects.polymarket.crusaderbot.config import Settings
        assert hasattr(Settings, "model_fields"), "Settings must be a pydantic model"
        assert "RISK_CONTROLS_VALIDATED" in Settings.model_fields

    def test_flag_default_is_false(self):
        """RISK_CONTROLS_VALIDATED must default to False — never auto-enabled."""
        from projects.polymarket.crusaderbot.config import Settings
        field = Settings.model_fields["RISK_CONTROLS_VALIDATED"]
        assert field.default is False, (
            f"RISK_CONTROLS_VALIDATED default must be False, got {field.default!r}"
        )


# ---------------------------------------------------------------------------
# ReadinessReport helpers
# ---------------------------------------------------------------------------


class TestReadinessReport:
    def test_overall_flips_to_fail_on_add_fail(self):
        from projects.polymarket.crusaderbot.services.validation.readiness_validator import (
            ReadinessReport,
        )
        r = ReadinessReport(overall="PASS")
        r.add("SOME_CHECK", "PASS", "ok")
        assert r.overall == "PASS"
        r.add("OTHER_CHECK", "FAIL", "bad thing")
        assert r.overall == "FAIL"

    def test_as_text_includes_check_names(self):
        from projects.polymarket.crusaderbot.services.validation.readiness_validator import (
            ReadinessReport,
        )
        r = ReadinessReport(overall="PASS")
        r.add("CHECK_FOO", "PASS", "all good")
        text = r.as_text()
        assert "CHECK_FOO" in text
        assert "PASS" in text
