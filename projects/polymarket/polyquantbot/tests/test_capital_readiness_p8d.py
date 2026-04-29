"""Priority 8-D — Day-scoped daily_loss_limit: PublicBetaState + CapitalRiskGate.

Test IDs: CR-23 .. CR-28

Coverage:
  CR-23  PublicBetaState.daily_realized_pnl is 0.0 on fresh state (before any sync)
  CR-24  daily_realized_pnl reflects same-day gains/losses relative to open baseline
  CR-25  reset_daily_pnl_if_needed() rolls baseline at Jakarta midnight, not lifetime pnl
  CR-26  CapitalRiskGate.evaluate() trips daily_loss_limit on day-scoped loss, not lifetime
  CR-27  Lifetime realized_pnl is unaffected by the daily baseline reset
  CR-28  Gate allows when daily_realized_pnl is above limit even if lifetime pnl is deeply negative
"""
from __future__ import annotations

import os
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from projects.polymarket.polyquantbot.server.config.capital_mode_config import CapitalModeConfig
from projects.polymarket.polyquantbot.server.core.public_beta_state import PublicBetaState
from projects.polymarket.polyquantbot.server.integrations.falcon_gateway import CandidateSignal
from projects.polymarket.polyquantbot.server.risk.capital_risk_gate import CapitalRiskGate

# ── Shared env fixtures ────────────────────────────────────────────────────────

_PAPER_ENV = {
    "TRADING_MODE": "PAPER",
    "ENABLE_LIVE_TRADING": "false",
    "CAPITAL_MODE_CONFIRMED": "false",
    "RISK_CONTROLS_VALIDATED": "false",
    "EXECUTION_PATH_VALIDATED": "false",
    "SECURITY_HARDENING_VALIDATED": "false",
}

_DAY_1 = date(2026, 4, 28)
_DAY_2 = date(2026, 4, 29)

_MODULE = "projects.polymarket.polyquantbot.server.core.public_beta_state._dt"


def _make_dt_mock(day: date) -> MagicMock:
    """Return a mock for _dt that returns *day* for .now().date()."""
    mock = MagicMock()
    mock.now.return_value.date.return_value = day
    return mock


def _good_signal() -> CandidateSignal:
    return CandidateSignal(
        signal_id="sig-cr23-001",
        condition_id="mkt-abc",
        side="YES",
        price=0.45,
        edge=0.12,
        liquidity=20000.0,
    )


# ── CR-23 ─────────────────────────────────────────────────────────────────────


def test_cr23_fresh_state_daily_pnl_is_zero() -> None:
    """CR-23: fresh PublicBetaState has daily_realized_pnl == 0.0."""
    state = PublicBetaState()
    assert state.daily_realized_pnl == 0.0
    assert state.daily_reset_date is None
    assert state.daily_open_realized_pnl == 0.0


# ── CR-24 ─────────────────────────────────────────────────────────────────────


def test_cr24_daily_pnl_reflects_intraday_changes() -> None:
    """CR-24: daily_realized_pnl tracks gains/losses relative to day-open baseline."""
    state = PublicBetaState()
    # First sync: lifetime realized = -500 → baseline set to -500, daily = 0
    state.realized_pnl = -500.0
    with patch(_MODULE, _make_dt_mock(_DAY_1)):
        state.reset_daily_pnl_if_needed()
    assert state.daily_open_realized_pnl == -500.0
    assert state.daily_realized_pnl == 0.0

    # Second trade closes: lifetime realized = -700 → daily = -200
    state.realized_pnl = -700.0
    assert round(state.daily_realized_pnl, 4) == -200.0

    # Third trade closes profitably: lifetime = -600 → daily = -100
    state.realized_pnl = -600.0
    assert round(state.daily_realized_pnl, 4) == -100.0


# ── CR-25 ─────────────────────────────────────────────────────────────────────


def test_cr25_reset_rolls_baseline_at_midnight() -> None:
    """CR-25: reset_daily_pnl_if_needed() updates baseline on calendar day change."""
    state = PublicBetaState()
    state.realized_pnl = -700.0

    with patch(_MODULE, _make_dt_mock(_DAY_1)):
        state.reset_daily_pnl_if_needed()

    assert state.daily_reset_date == _DAY_1
    assert state.daily_open_realized_pnl == -700.0

    # More losses accumulate on day 1
    state.realized_pnl = -900.0
    assert round(state.daily_realized_pnl, 4) == -200.0

    # Day rolls over
    with patch(_MODULE, _make_dt_mock(_DAY_2)):
        state.reset_daily_pnl_if_needed()

    assert state.daily_reset_date == _DAY_2
    assert state.daily_open_realized_pnl == -900.0  # new baseline is day-2 open
    assert state.daily_realized_pnl == 0.0           # fresh slate for day 2


def test_cr25b_same_day_reset_is_noop() -> None:
    """CR-25b: calling reset_daily_pnl_if_needed() twice on same day is idempotent."""
    state = PublicBetaState()
    state.realized_pnl = -300.0
    with patch(_MODULE, _make_dt_mock(_DAY_1)):
        state.reset_daily_pnl_if_needed()
        state.realized_pnl = -500.0  # trade closes
        state.reset_daily_pnl_if_needed()  # same day — no-op

    assert state.daily_open_realized_pnl == -300.0  # baseline unchanged
    assert round(state.daily_realized_pnl, 4) == -200.0


# ── CR-26 ─────────────────────────────────────────────────────────────────────


@patch("os.environ", {**_PAPER_ENV})
def test_cr26_gate_trips_on_day_scoped_loss() -> None:
    """CR-26: daily_loss_limit gate trips on day-scoped loss, not lifetime."""
    state = PublicBetaState()
    # Yesterday ended at -3000 lifetime
    state.realized_pnl = -3000.0
    with patch(_MODULE, _make_dt_mock(_DAY_1)):
        state.reset_daily_pnl_if_needed()

    # Today: -1900 added → daily = -1900 (above -2000 limit → gate open)
    state.realized_pnl = -4900.0
    state.daily_reset_date = _DAY_2  # already set for today

    with patch("os.environ", _PAPER_ENV):
        cfg = CapitalModeConfig.from_env()
    gate = CapitalRiskGate(config=cfg)
    signal = _good_signal()

    with patch(_MODULE, _make_dt_mock(_DAY_2)):
        decision = gate.evaluate(signal, state)
    assert decision.allowed is True, decision.reason

    # Today: -2100 added → daily = -2100 (below -2000 limit → gate trips)
    state.realized_pnl = -5100.0
    with patch(_MODULE, _make_dt_mock(_DAY_2)):
        decision = gate.evaluate(signal, state)
    assert decision.allowed is False
    assert decision.reason == "daily_loss_limit"


# ── CR-27 ─────────────────────────────────────────────────────────────────────


def test_cr27_lifetime_pnl_unaffected_by_daily_reset() -> None:
    """CR-27: realized_pnl (lifetime) is never modified by reset_daily_pnl_if_needed()."""
    state = PublicBetaState()
    state.realized_pnl = -5000.0
    with patch(_MODULE, _make_dt_mock(_DAY_1)):
        state.reset_daily_pnl_if_needed()
    state.realized_pnl = -7000.0
    with patch(_MODULE, _make_dt_mock(_DAY_2)):
        state.reset_daily_pnl_if_needed()

    # Lifetime PnL is exactly what was set — reset only touched the baseline
    assert state.realized_pnl == -7000.0
    assert state.daily_realized_pnl == 0.0


# ── CR-28 ─────────────────────────────────────────────────────────────────────


@patch("os.environ", {**_PAPER_ENV})
def test_cr28_gate_allows_when_daily_above_limit_despite_deep_lifetime_loss() -> None:
    """CR-28: gate allows when today's loss is within limit, even if lifetime is deeply negative.

    This proves the FLAG-1 regression: the old code used state.realized_pnl
    (lifetime) and would have permanently blocked trading once lifetime losses
    exceeded -$2,000.  The new code uses state.daily_realized_pnl and allows
    trading on a new day with a fresh slate.
    """
    state = PublicBetaState()
    # Lifetime losses are far below the daily limit — old code would permanently block
    state.realized_pnl = -15000.0
    # Today opened at -15000 baseline → daily = 0 so far
    state.daily_open_realized_pnl = -15000.0
    state.daily_reset_date = _DAY_2

    with patch("os.environ", _PAPER_ENV):
        cfg = CapitalModeConfig.from_env()
    gate = CapitalRiskGate(config=cfg)
    signal = _good_signal()

    with patch(_MODULE, _make_dt_mock(_DAY_2)):
        decision = gate.evaluate(signal, state)

    assert decision.allowed is True, (
        f"Expected gate OPEN (daily_realized_pnl=0.0 > -2000 limit), "
        f"got: {decision.reason}"
    )
