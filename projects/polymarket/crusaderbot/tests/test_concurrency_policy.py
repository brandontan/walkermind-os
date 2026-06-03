"""Hermetic tests for the per-user open-position policy.

Open-position capacity is a PER-USER setting, not a global ceiling (WARP🔹CMD /
owner directive 2026-06-03). ``effective_max_concurrent`` returns the user's own
``max_concurrent_override`` when validly set (it may raise OR lower the limit),
otherwise the profile default (conservative 5 / balanced 12 / aggressive 20 /
custom 12). There is NO system-wide ceiling clamping the result down — the prior
``MAX_CONCURRENT_TRADES = 5`` constant was removed.

Both enforcement points consume the same per-user value:
  * gate Cap 4 (open-position count, ``validate_risk_caps``) is threaded with the
    per-user limit from ``evaluate`` via ``max_open_cap``; it precedes step 7, so
    in the full gate it is the one that fires at the count limit.
  * gate step 7 + ``resume_safety_check`` step 7 call ``effective_max_concurrent``
    directly (the resume path does not run Cap 4, so step 7 is its enforcer).

Other capital brakes (Kelly 0.25, position ≤10%, daily-loss −$2k, drawdown 8%,
correlated-exposure 40% at step 8, kill switch) are unchanged. Per-profile audit
coverage stays in ``hardening.audit_risk_constants`` (1..50 range).

No DB, no broker, no Telegram. All DB helpers patched.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from projects.polymarket.crusaderbot.domain.risk import constants as K
from projects.polymarket.crusaderbot.domain.risk import gate as gate_mod
from projects.polymarket.crusaderbot.domain.risk.constants import (
    PROFILES,
    effective_max_concurrent,
)
from projects.polymarket.crusaderbot.domain.risk.gate import (
    GateContext,
    GateResult,
    evaluate,
    resume_safety_check,
)

_USER = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
_MARKET = "market-conc-001"


# --------------------------------------------------------------------------- helpers


def _settings(
    *,
    max_daily_loss_usd: float = -2000.0,
    max_total_exposure_pct: float = 1.0,
    max_single_position_pct: float = 0.10,
    max_open_positions: int = 50,
):
    return SimpleNamespace(
        MAX_DAILY_LOSS_USD=max_daily_loss_usd,
        MAX_TOTAL_EXPOSURE_PCT=max_total_exposure_pct,
        MAX_SINGLE_POSITION_PCT=max_single_position_pct,
        MAX_OPEN_POSITIONS=max_open_positions,
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
):
    monkeypatch.setattr(gate_mod, "_log", AsyncMock(return_value=None))
    monkeypatch.setattr(gate_mod, "daily_pnl", AsyncMock(return_value=Decimal(str(pnl))))
    monkeypatch.setattr(gate_mod, "get_balance", AsyncMock(return_value=Decimal(str(balance))))
    monkeypatch.setattr(gate_mod, "_max_drawdown_breached", AsyncMock(return_value=dd))
    monkeypatch.setattr(gate_mod, "_open_position_count", AsyncMock(return_value=open_count))
    monkeypatch.setattr(gate_mod, "_open_exposure", AsyncMock(return_value=Decimal(str(open_exp))))
    monkeypatch.setattr(gate_mod, "kill_switch_is_active", AsyncMock(return_value=kill_switch))
    monkeypatch.setattr(gate_mod, "_record_idempotency", AsyncMock(return_value=None))
    monkeypatch.setattr(gate_mod, "_idempotent_already_seen", AsyncMock(return_value=False))
    monkeypatch.setattr(gate_mod, "_recent_dup_market_trade", AsyncMock(return_value=False))
    monkeypatch.setattr(
        gate_mod, "check_market_impact",
        lambda size, liq: SimpleNamespace(accepted=True, reason="ok", impact_pct=0.01),
    )

    s = _settings()
    import projects.polymarket.crusaderbot.config as _cfg
    monkeypatch.setattr(_cfg, "get_settings", lambda: s)


def _ctx(
    *,
    risk_profile="balanced",
    proposed_size=Decimal("10"),
    trading_mode="paper",
    max_concurrent_override=None,
) -> GateContext:
    from datetime import datetime, timezone
    return GateContext(
        user_id=_USER,
        telegram_user_id=99,
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
        idempotency_key="idem-conc-1",
        strategy_type="late_entry_v3",
        risk_profile=risk_profile,
        daily_loss_override=None,
        trading_mode=trading_mode,
        max_concurrent_override=max_concurrent_override,
    )


# --------------------------------------------------------------------------- effective_max_concurrent unit


def test_effective_max_concurrent_profile_defaults():
    # No override -> the user's profile default governs (no global ceiling).
    assert effective_max_concurrent("conservative") == 5
    assert effective_max_concurrent("balanced") == 12
    assert effective_max_concurrent("aggressive") == 20
    assert effective_max_concurrent("custom") == 12


def test_effective_max_concurrent_user_override_is_authoritative():
    # A validly-set override is the user's own limit — it may sit below OR above
    # the profile default; the user's setting wins either way.
    assert effective_max_concurrent("balanced", user_override=3) == 3
    assert effective_max_concurrent("aggressive", user_override=10) == 10
    assert effective_max_concurrent("conservative", user_override=2) == 2


def test_effective_max_concurrent_user_override_can_raise_above_profile():
    # No global ceiling: an override above the profile default raises the limit.
    assert effective_max_concurrent("conservative", user_override=10) == 10
    assert effective_max_concurrent("balanced", user_override=18) == 18
    # The function imposes no upper bound (the DB CHECK 1..20 bounds it at write
    # time); prove there is no in-code clamp.
    assert effective_max_concurrent("aggressive", user_override=999) == 999


def test_effective_max_concurrent_unknown_profile_falls_back_to_balanced():
    # Unknown profile -> balanced default (12); a valid override still wins.
    assert effective_max_concurrent("garbage") == 12
    assert effective_max_concurrent("garbage", user_override=4) == 4


def test_effective_max_concurrent_is_case_insensitive():
    # Profile names from UI forms may arrive title- or upper-cased. They must
    # resolve to the real profile (not silently fall through to 'balanced').
    assert effective_max_concurrent("Conservative") == 5
    assert effective_max_concurrent("BALANCED", user_override=3) == 3
    assert effective_max_concurrent("Aggressive") == 20


def test_effective_max_concurrent_none_profile_uses_balanced():
    assert effective_max_concurrent(None) == 12  # type: ignore[arg-type]


def test_effective_max_concurrent_defensive_coercion_of_invalid_values():
    # Zero / negative / unparseable override -> fall back to the profile default
    # (never bricks the user). The DB CHECK enforces 1..20 at write time; this
    # defends against legacy rows / direct DB writes.
    assert effective_max_concurrent("balanced", user_override=0) == 12
    assert effective_max_concurrent("balanced", user_override=-5) == 12
    assert effective_max_concurrent("balanced", user_override="not-a-number") == 12
    # A numeric string / float (legacy row, API payload) is honoured, not dropped.
    assert effective_max_concurrent("balanced", user_override="12.0") == 12
    assert effective_max_concurrent("conservative", user_override=7.9) == 7


# --------------------------------------------------------------------------- gate (evaluate) integration


def test_gate_cap4_enforces_per_user_profile_default(monkeypatch):
    # balanced default = 12, no override. Cap 4 (open-position count, threaded
    # with the per-user limit and evaluated before step 7) rejects at 12 — not a
    # global 5.
    _patch_clear(monkeypatch, open_count=12)
    res = asyncio.run(evaluate(_ctx(risk_profile="balanced")))
    assert res.approved is False
    assert res.reason == "max_open_positions_12_reached"
    assert res.failed_step == 0


def test_gate_cap4_uses_tighter_user_override(monkeypatch):
    # balanced default 12, user tightens to 3; rejected at open_count 3 >= 3.
    _patch_clear(monkeypatch, open_count=3)
    res = asyncio.run(evaluate(_ctx(risk_profile="balanced", max_concurrent_override=3)))
    assert res.approved is False
    assert res.reason == "max_open_positions_3_reached"
    assert res.failed_step == 0


def test_gate_passes_when_open_below_effective_cap(monkeypatch):
    # balanced default 12, override 5, open_count 4 -> passes Cap 4 and step 7.
    _patch_clear(monkeypatch, open_count=4)
    res = asyncio.run(evaluate(_ctx(risk_profile="balanced", max_concurrent_override=5)))
    assert res.approved is True


def test_gate_user_override_raises_limit_above_profile(monkeypatch):
    # The core of the per-user change: an override ABOVE the profile default
    # raises the limit end-to-end. balanced default 12, override 18; 15 open
    # positions now PASSES (would have been blocked at the old global 5/12).
    _patch_clear(monkeypatch, open_count=15)
    res = asyncio.run(evaluate(_ctx(risk_profile="balanced", max_concurrent_override=18)))
    assert res.approved is True


# --------------------------------------------------------------------------- resume_safety_check step 7 integration


def test_resume_step_7_rejects_when_open_at_profile_cap(monkeypatch):
    _patch_clear(monkeypatch, open_count=12)
    res = asyncio.run(resume_safety_check(
        user_id=_USER,
        market_id=_MARKET,
        risk_profile="balanced",
        proposed_size_usdc=Decimal("10"),
        trading_mode="paper",
        chosen_mode="paper",
    ))
    assert res.approved is False
    assert res.reason == "max_concurrent_trades"
    assert res.failed_step == 7


def test_resume_step_7_rejects_when_user_override_tighter(monkeypatch):
    _patch_clear(monkeypatch, open_count=3)
    res = asyncio.run(resume_safety_check(
        user_id=_USER,
        market_id=_MARKET,
        risk_profile="balanced",
        proposed_size_usdc=Decimal("10"),
        trading_mode="paper",
        chosen_mode="paper",
        max_concurrent_override=3,
    ))
    assert res.approved is False
    assert res.reason == "max_concurrent_trades"
    assert res.failed_step == 7


def test_resume_step_7_passes_when_under_effective_cap(monkeypatch):
    _patch_clear(monkeypatch, open_count=4)
    res = asyncio.run(resume_safety_check(
        user_id=_USER,
        market_id=_MARKET,
        risk_profile="balanced",
        proposed_size_usdc=Decimal("10"),
        trading_mode="paper",
        chosen_mode="paper",
        max_concurrent_override=5,
    ))
    assert res.approved is True
    assert res.reason == "resume_safety_ok"


def test_resume_step_7_user_override_raises_limit(monkeypatch):
    # conservative default = 5; user raises override to 999; open_count = 5 now
    # PASSES (no global ceiling — the user's own setting governs).
    _patch_clear(monkeypatch, open_count=5)
    res = asyncio.run(resume_safety_check(
        user_id=_USER,
        market_id=_MARKET,
        risk_profile="conservative",
        proposed_size_usdc=Decimal("10"),
        trading_mode="paper",
        chosen_mode="paper",
        max_concurrent_override=999,
    ))
    assert res.approved is True
    assert res.reason == "resume_safety_ok"


# --------------------------------------------------------------------------- no global ceiling


def test_no_global_concurrent_ceiling_constant():
    # The global ceiling constant was removed — open positions are per-user.
    assert not hasattr(K, "MAX_CONCURRENT_TRADES")


def test_every_profile_has_max_concurrent_in_safe_range():
    # Hardening audit (audit_risk_constants) enforces 1 ≤ v ≤ 50 per profile.
    for name, profile in PROFILES.items():
        mc = profile.get("max_concurrent")
        assert mc is not None, f"{name} missing max_concurrent"
        assert 1 <= int(mc) <= 50, f"{name} max_concurrent {mc} out of range"
