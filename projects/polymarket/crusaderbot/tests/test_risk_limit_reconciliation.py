"""Hermetic tests for WARP/ROOT/risk-limit-reconciliation (C-5 + C-6).

Closes the dual-evaluation drift between the Track-D `validate_risk_caps`
layer (gate step 0) and the profile-aware gates (steps 5 + 8). The historical
shape was:
  * step 0 cap 2 enforced ``settings.MAX_TOTAL_EXPOSURE_PCT`` (0.60)
  * step 8 enforced ``MAX_CORRELATED_EXPOSURE`` (0.40)
  * step 0 cap 3 enforced ``settings.MAX_DAILY_LOSS_USD`` (−$50)
  * step 5 enforced ``effective_daily_loss(profile)`` (−$200 / −$500 / −$1000)
Step 0 always fired first, so the profile cap + the operator env cap fought
twice and the UI-displayed limit was a lie under LIVE. Reconciliation:
  * step 0 keeps Cap 0 (balance), Cap 1 (single-position %), Cap 4 (open count)
  * step 5 now passes ``MAX_DAILY_LOSS_USD`` as ``system_floor`` to
    ``effective_daily_loss``
  * step 8 now consumes ``effective_exposure_cap(MAX_TOTAL_EXPOSURE_PCT)``
Behaviour preserved (most-restrictive still wins); duplicate evaluations removed.

No DB, no broker, no Telegram. All DB helpers patched.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from projects.polymarket.crusaderbot.domain.risk import gate as gate_mod
from projects.polymarket.crusaderbot.domain.risk.constants import (
    DAILY_LOSS_HARD_STOP,
    MAX_CORRELATED_EXPOSURE,
    effective_daily_loss,
    effective_exposure_cap,
)
from projects.polymarket.crusaderbot.domain.risk.gate import (
    GateContext,
    evaluate,
    validate_risk_caps,
)

_USER = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
_MARKET = "market-recon-001"


# --------------------------------------------------------------------------- helpers


def _settings(
    *,
    max_daily_loss_usd: float = -50.0,
    max_total_exposure_pct: float = 0.60,
    max_single_position_pct: float = 0.05,
    max_open_positions: int = 20,
):
    """Minimal settings stub matching the attrs gate.py reads."""
    return SimpleNamespace(
        MAX_DAILY_LOSS_USD=max_daily_loss_usd,
        MAX_TOTAL_EXPOSURE_PCT=max_total_exposure_pct,
        MAX_SINGLE_POSITION_PCT=max_single_position_pct,
        MAX_OPEN_POSITIONS=max_open_positions,
        # live-mode guard attrs the gate touches in step 13 / _passes_live_guards.
        ENABLE_LIVE_TRADING=False,
        EXECUTION_PATH_VALIDATED=False,
        CAPITAL_MODE_CONFIRMED=False,
        RISK_CONTROLS_VALIDATED=False,
        SECURITY_HARDENING_VALIDATED=False,
        USE_REAL_CLOB=False,
    )


def _patch_clear(
    monkeypatch,
    *,
    balance=1000.0,
    pnl=0.0,
    dd=False,
    open_count=0,
    open_exp=0.0,
    kill_switch=False,
    settings_kwargs=None,
):
    """Patch every gate DB helper + settings to a clear (passing) baseline."""
    monkeypatch.setattr(gate_mod, "_log", AsyncMock(return_value=None))
    monkeypatch.setattr(gate_mod, "daily_pnl", AsyncMock(return_value=Decimal(str(pnl))))
    monkeypatch.setattr(gate_mod, "get_balance", AsyncMock(return_value=Decimal(str(balance))))
    monkeypatch.setattr(gate_mod, "_max_drawdown_breached", AsyncMock(return_value=dd))
    monkeypatch.setattr(gate_mod, "_open_position_count", AsyncMock(return_value=open_count))
    monkeypatch.setattr(gate_mod, "_open_exposure", AsyncMock(return_value=Decimal(str(open_exp))))
    monkeypatch.setattr(gate_mod, "kill_switch_is_active",
                        AsyncMock(return_value=kill_switch))
    monkeypatch.setattr(gate_mod, "_record_idempotency", AsyncMock(return_value=None))
    monkeypatch.setattr(gate_mod, "_idempotent_already_seen", AsyncMock(return_value=False))
    monkeypatch.setattr(gate_mod, "_recent_dup_market_trade", AsyncMock(return_value=False))
    # check_market_impact is sync — replace with a stub that accepts any size/liq.
    monkeypatch.setattr(
        gate_mod, "check_market_impact",
        lambda size, liq: SimpleNamespace(accepted=True, reason="ok", impact_pct=0.01),
    )

    s = _settings(**(settings_kwargs or {}))
    import projects.polymarket.crusaderbot.config as _cfg
    monkeypatch.setattr(_cfg, "get_settings", lambda: s)


def _ctx(
    *,
    risk_profile="balanced",
    proposed_size=Decimal("10"),     # below 5% single-position cap (50 on balance 1000)
    trading_mode="paper",
    daily_loss_override=None,
) -> GateContext:
    from datetime import datetime, timezone
    return GateContext(
        user_id=_USER,
        telegram_user_id=42,
        role="user",
        auto_trade_on=True,
        paused=False,
        market_id=_MARKET,
        side="yes",
        proposed_size_usdc=proposed_size,
        proposed_price=0.55,
        market_liquidity=50_000.0,
        market_status="active",
        edge_bps=400.0,
        signal_ts=datetime.now(timezone.utc),
        idempotency_key="idem-recon-1",
        strategy_type="late_entry_v3",
        risk_profile=risk_profile,
        daily_loss_override=daily_loss_override,
        trading_mode=trading_mode,
    )


# --------------------------------------------------------------------------- C-5 unit


def test_effective_daily_loss_picks_system_floor_when_tighter():
    # profile=balanced=-500, floor=-50 → -50 (most restrictive)
    assert effective_daily_loss("balanced", system_floor=-50.0) == -50.0


def test_effective_daily_loss_picks_profile_when_floor_permissive():
    # profile=balanced=-500, floor=-2000 → -500 (profile is tighter)
    assert effective_daily_loss("balanced", system_floor=-2000.0) == -500.0


def test_effective_daily_loss_none_floor_matches_legacy_behaviour():
    assert effective_daily_loss("balanced") == -500.0
    assert effective_daily_loss("aggressive") == -1_000.0
    assert effective_daily_loss("conservative") == -200.0


def test_effective_daily_loss_user_override_can_only_tighten():
    # override tighter than profile → override wins
    assert effective_daily_loss("balanced", user_override=-100.0,
                                system_floor=-2000.0) == -100.0
    # override looser than profile → profile wins
    assert effective_daily_loss("balanced", user_override=-9_000.0,
                                system_floor=-2000.0) == -500.0


def test_effective_daily_loss_overly_permissive_override_yields_profile_cap():
    # An override looser than the profile cap (more negative) MUST NOT loosen the
    # cap — most-restrictive semantics keep the profile cap. Hard-stop only wins
    # when every contributor (incl. override) is looser than it, which is a
    # degenerate config the audit_risk_constants check catches at boot.
    assert effective_daily_loss("aggressive", user_override=-10_000.0) == -1_000.0


# --------------------------------------------------------------------------- C-6 unit


def test_effective_exposure_cap_picks_smaller():
    # system_cap 0.60 > MAX_CORRELATED_EXPOSURE 0.40 → constant wins
    assert effective_exposure_cap(system_cap=0.60) == MAX_CORRELATED_EXPOSURE
    # operator tightens to 0.20 → operator wins
    assert effective_exposure_cap(system_cap=0.20) == 0.20


def test_effective_exposure_cap_none_uses_constant_only():
    assert effective_exposure_cap() == MAX_CORRELATED_EXPOSURE


# --------------------------------------------------------------------------- C-5/C-6 integration: validate_risk_caps no longer rejects on these


def test_validate_risk_caps_no_longer_rejects_on_daily_loss(monkeypatch):
    # pnl breaches the −$50 settings floor; cap 3 USED to reject here.
    # After reconciliation the daily-loss check lives only at gate step 5.
    _patch_clear(monkeypatch, pnl=-100.0)
    res = asyncio.run(validate_risk_caps(_USER, Decimal("10")))
    assert res.approved is True
    assert res.reason == "caps_ok"


def test_validate_risk_caps_no_longer_rejects_on_total_exposure(monkeypatch):
    # open_exp 700 + proposed 50 = 750 / 1000 = 0.75 > 0.60 settings cap;
    # USED to reject at cap 2. Now reconciled into step 8.
    _patch_clear(monkeypatch, open_exp=700.0)
    res = asyncio.run(validate_risk_caps(_USER, Decimal("50")))
    assert res.approved is True


def test_validate_risk_caps_still_rejects_on_single_position_pct(monkeypatch):
    # proposed 100 vs MAX_SINGLE_POSITION_PCT=0.05 * balance 1000 = 50 → reject
    _patch_clear(monkeypatch)
    res = asyncio.run(validate_risk_caps(_USER, Decimal("100")))
    assert res.approved is False
    assert "position_size" in res.reason


def test_validate_risk_caps_still_rejects_on_open_position_count(monkeypatch):
    _patch_clear(monkeypatch, open_count=20)
    res = asyncio.run(validate_risk_caps(_USER, Decimal("10")))
    assert res.approved is False
    assert res.reason.startswith("max_open_positions_")


def test_validate_risk_caps_still_rejects_on_zero_balance(monkeypatch):
    _patch_clear(monkeypatch, balance=0.0)
    res = asyncio.run(validate_risk_caps(_USER, Decimal("10")))
    assert res.approved is False
    assert res.reason == "balance_zero_or_negative"


# --------------------------------------------------------------------------- gate step 5 + 8 still enforce, now with reconciled cap


def test_step_5_enforces_reconciled_cap_with_system_floor(monkeypatch):
    # pnl -75 vs settings floor -50 (tighter than balanced -500) → reject
    _patch_clear(monkeypatch, pnl=-75.0,
                 settings_kwargs={"max_daily_loss_usd": -50.0})
    res = asyncio.run(evaluate(_ctx()))
    assert res.approved is False
    assert res.reason == "daily_loss_cap_hit"
    assert res.failed_step == 5


def test_step_5_uses_profile_cap_when_operator_relaxes_system_floor(monkeypatch):
    # operator sets floor permissive (-2000); balanced profile cap -500 wins;
    # pnl -300 should now be allowed where it was previously blocked at cap 3.
    _patch_clear(monkeypatch, pnl=-300.0,
                 settings_kwargs={"max_daily_loss_usd": -2000.0})
    res = asyncio.run(evaluate(_ctx()))
    assert res.approved is True


def test_step_5_profile_cap_fires_when_pnl_breaches_profile(monkeypatch):
    # operator relaxed floor; pnl -700 breaches balanced profile -500 → reject at step 5
    _patch_clear(monkeypatch, pnl=-700.0,
                 settings_kwargs={"max_daily_loss_usd": -2000.0})
    res = asyncio.run(evaluate(_ctx()))
    assert res.approved is False
    assert res.failed_step == 5


def test_step_8_uses_reconciled_exposure_cap_constant_when_tighter(monkeypatch):
    # open 395 + proposed 10 = 405/1000 = 0.405 > 0.40 system constant → reject step 8.
    _patch_clear(monkeypatch, open_exp=395.0,
                 settings_kwargs={"max_total_exposure_pct": 0.60})
    res = asyncio.run(evaluate(_ctx(proposed_size=Decimal("10"))))
    assert res.approved is False
    assert res.failed_step == 8


def test_step_8_uses_operator_cap_when_tighter(monkeypatch):
    # operator tightens cap to 0.20; open 195 + proposed 10 = 205/1000 = 0.205 → reject step 8.
    _patch_clear(monkeypatch, open_exp=195.0,
                 settings_kwargs={"max_total_exposure_pct": 0.20})
    res = asyncio.run(evaluate(_ctx(proposed_size=Decimal("10"))))
    assert res.approved is False
    assert res.failed_step == 8


def test_step_8_passes_when_under_reconciled_cap(monkeypatch):
    # 390 + 10 = 400/1000 = 0.40 exactly, not >, so passes step 8.
    _patch_clear(monkeypatch, open_exp=390.0)
    res = asyncio.run(evaluate(_ctx(proposed_size=Decimal("10"))))
    assert res.approved is True
