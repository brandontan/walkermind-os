"""Priority 8-A — Capital Readiness: CapitalModeConfig + BoundaryRegistry — Tests.

Test IDs: CR-01 .. CR-12

Coverage:
  CR-01  CapitalModeConfig defaults all gates to False in clean env
  CR-02  from_env() reads each gate from correct env var
  CR-03  validate() raises CapitalModeGuardError when LIVE but any single gate off
  CR-04  validate() passes when all gates on and mode is LIVE
  CR-05  validate() passes in PAPER mode regardless of gate state
  CR-06  max_position_fraction > 0.10 raises ValueError
  CR-07  kelly_fraction != 0.25 raises ValueError
  CR-08  daily_loss_limit_usd >= 0 raises ValueError
  CR-09  drawdown_limit_pct > 0.08 raises ValueError
  CR-10  boundary_registry contains entries for all CRITICAL surfaces
  CR-11  get_capital_readiness_criteria() returns non-empty ordered checklist
  CR-12  every BLOCKED boundary has a readiness_gate assigned
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from projects.polymarket.polyquantbot.server.config.capital_mode_config import (
    KELLY_FRACTION,
    CapitalModeConfig,
    CapitalModeGuardError,
)
from projects.polymarket.polyquantbot.server.config.boundary_registry import (
    PAPER_ONLY_BOUNDARIES,
    get_boundaries_by_status,
    get_capital_readiness_criteria,
    get_critical_boundaries,
)

_ALL_GATES_ON = {
    "TRADING_MODE": "LIVE",
    "ENABLE_LIVE_TRADING": "true",
    "CAPITAL_MODE_CONFIRMED": "true",
    "RISK_CONTROLS_VALIDATED": "true",
    "EXECUTION_PATH_VALIDATED": "true",
    "SECURITY_HARDENING_VALIDATED": "true",
}

_PAPER_ENV = {
    "TRADING_MODE": "PAPER",
    "ENABLE_LIVE_TRADING": "false",
    "CAPITAL_MODE_CONFIRMED": "false",
    "RISK_CONTROLS_VALIDATED": "false",
    "EXECUTION_PATH_VALIDATED": "false",
    "SECURITY_HARDENING_VALIDATED": "false",
}


def _make_cfg(**overrides: str) -> CapitalModeConfig:
    env = {**_PAPER_ENV, **overrides}
    with patch.dict(os.environ, env, clear=False):
        return CapitalModeConfig.from_env()


# ── CR-01: all gates default False ────────────────────────────────────────────

def test_cr01_all_gates_default_false() -> None:
    safe_env = {k: "" for k in _ALL_GATES_ON}
    safe_env["TRADING_MODE"] = "PAPER"
    with patch.dict(os.environ, safe_env, clear=False):
        cfg = CapitalModeConfig.from_env()
    assert cfg.enable_live_trading is False
    assert cfg.capital_mode_confirmed is False
    assert cfg.risk_controls_validated is False
    assert cfg.execution_path_validated is False
    assert cfg.security_hardening_validated is False
    assert cfg.is_capital_mode_allowed() is False


# ── CR-02: from_env reads each gate ───────────────────────────────────────────

def test_cr02_from_env_reads_all_gates() -> None:
    with patch.dict(os.environ, _ALL_GATES_ON, clear=False):
        cfg = CapitalModeConfig.from_env()
    assert cfg.trading_mode == "LIVE"
    assert cfg.enable_live_trading is True
    assert cfg.capital_mode_confirmed is True
    assert cfg.risk_controls_validated is True
    assert cfg.execution_path_validated is True
    assert cfg.security_hardening_validated is True
    assert cfg.is_capital_mode_allowed() is True


# ── CR-03: validate raises when any single gate off ───────────────────────────

@pytest.mark.parametrize("missing_gate", [
    "ENABLE_LIVE_TRADING",
    "CAPITAL_MODE_CONFIRMED",
    "RISK_CONTROLS_VALIDATED",
    "EXECUTION_PATH_VALIDATED",
    "SECURITY_HARDENING_VALIDATED",
])
def test_cr03_validate_raises_when_gate_off(missing_gate: str) -> None:
    env = {**_ALL_GATES_ON, missing_gate: "false"}
    with patch.dict(os.environ, env, clear=False):
        cfg = CapitalModeConfig.from_env()
    with pytest.raises(CapitalModeGuardError) as exc_info:
        cfg.validate()
    assert missing_gate in str(exc_info.value)


# ── CR-04: validate passes when all gates on ──────────────────────────────────

def test_cr04_validate_passes_all_gates_on() -> None:
    with patch.dict(os.environ, _ALL_GATES_ON, clear=False):
        cfg = CapitalModeConfig.from_env()
    cfg.validate()  # must not raise


# ── CR-05: validate passes in PAPER regardless of gates ───────────────────────

def test_cr05_validate_passes_paper_mode() -> None:
    with patch.dict(os.environ, _PAPER_ENV, clear=False):
        cfg = CapitalModeConfig.from_env()
    cfg.validate()  # must not raise in PAPER mode


# ── CR-06: max_position_fraction > 0.10 raises ────────────────────────────────

def test_cr06_max_position_fraction_cap() -> None:
    env = {**_PAPER_ENV, "CAPITAL_MAX_POSITION_FRACTION": "0.15"}
    with patch.dict(os.environ, env, clear=False):
        cfg = CapitalModeConfig.from_env()
    with pytest.raises(ValueError, match="max_position_fraction"):
        cfg.validate()


# ── CR-07: kelly_fraction must be 0.25 ────────────────────────────────────────

def test_cr07_kelly_fraction_locked() -> None:
    with patch.dict(os.environ, _PAPER_ENV, clear=False):
        cfg = CapitalModeConfig.from_env()
    assert cfg.kelly_fraction == KELLY_FRACTION
    # Construct manually with wrong kelly to verify the guard
    bad_cfg = CapitalModeConfig(
        trading_mode="PAPER",
        enable_live_trading=False,
        capital_mode_confirmed=False,
        risk_controls_validated=False,
        execution_path_validated=False,
        security_hardening_validated=False,
        kelly_fraction=1.0,
        max_position_fraction=0.02,
        daily_loss_limit_usd=-2000.0,
        drawdown_limit_pct=0.08,
        min_liquidity_usd=10_000.0,
    )
    with pytest.raises(ValueError, match="kelly_fraction"):
        bad_cfg.validate()


# ── CR-08: daily_loss_limit_usd >= 0 raises ───────────────────────────────────

def test_cr08_daily_loss_limit_must_be_negative() -> None:
    env = {**_PAPER_ENV, "CAPITAL_DAILY_LOSS_LIMIT_USD": "0"}
    with patch.dict(os.environ, env, clear=False):
        cfg = CapitalModeConfig.from_env()
    with pytest.raises(ValueError, match="daily_loss_limit_usd"):
        cfg.validate()


# ── CR-09: drawdown_limit_pct > 0.08 raises ───────────────────────────────────

def test_cr09_drawdown_limit_cap() -> None:
    env = {**_PAPER_ENV, "CAPITAL_DRAWDOWN_LIMIT_PCT": "0.15"}
    with patch.dict(os.environ, env, clear=False):
        cfg = CapitalModeConfig.from_env()
    with pytest.raises(ValueError, match="drawdown_limit_pct"):
        cfg.validate()


# ── CR-10: registry has CRITICAL entries ──────────────────────────────────────

def test_cr10_registry_has_critical_entries() -> None:
    critical = get_critical_boundaries()
    assert len(critical) >= 3, "Expected at least 3 CRITICAL boundaries in registry"
    surfaces = {b.surface for b in critical}
    assert "PaperExecutionEngine" in surfaces
    assert "SettlementWorkflow.allow_real_settlement" in surfaces
    assert "WalletCandidate.financial_fields_zero" in surfaces


# ── CR-11: readiness criteria non-empty ───────────────────────────────────────

def test_cr11_readiness_criteria_non_empty() -> None:
    criteria = get_capital_readiness_criteria()
    assert len(criteria) >= 20, "Expected at least 20 readiness criteria items"
    gates_covered = {c.split("-")[0] + "-" + c.split("-")[1] for c in criteria if c[0] == "P"}
    assert "P8-B" in gates_covered
    assert "P8-C" in gates_covered
    assert "P8-D" in gates_covered
    assert "P8-E" in gates_covered


# ── CR-12: every BLOCKED boundary has a readiness_gate ────────────────────────

def test_cr12_blocked_boundaries_have_gate() -> None:
    blocked = get_boundaries_by_status("BLOCKED")
    assert len(blocked) >= 1
    for b in blocked:
        assert b.readiness_gate, f"BLOCKED boundary '{b.surface}' missing readiness_gate"
        assert b.readiness_gate.startswith("P8-"), (
            f"BLOCKED boundary '{b.surface}' has invalid gate '{b.readiness_gate}'"
        )
