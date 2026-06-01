"""Hermetic tests for WARP/ROOT/concurrency-policy (Lane 3C).

Closes C-3 by making max_concurrent a per-user override (tighter-only) on top of
the per-profile defaults (conservative=5 / balanced=12 / aggressive=20). The
dead ``MAX_CONCURRENT_TRADES`` constant is removed; per-profile audit coverage
is added in ``hardening.audit_risk_constants``; and the gate (step 7) +
``resume_safety_check`` (step 7) consume the new
``effective_max_concurrent(profile, user_override)`` helper.

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


def test_effective_max_concurrent_returns_profile_default_when_none():
    assert effective_max_concurrent("conservative") == 5
    assert effective_max_concurrent("balanced") == 12
    assert effective_max_concurrent("aggressive") == 20
    assert effective_max_concurrent("custom") == 12


def test_effective_max_concurrent_user_override_tightens():
    assert effective_max_concurrent("balanced", user_override=3) == 3
    assert effective_max_concurrent("aggressive", user_override=10) == 10
    assert effective_max_concurrent("conservative", user_override=2) == 2


def test_effective_max_concurrent_user_override_cannot_loosen():
    # User override higher than profile cap → profile wins.
    assert effective_max_concurrent("conservative", user_override=10) == 5
    assert effective_max_concurrent("balanced", user_override=50) == 12
    assert effective_max_concurrent("aggressive", user_override=999) == 20


def test_effective_max_concurrent_unknown_profile_falls_back_to_balanced():
    assert effective_max_concurrent("garbage") == 12
    assert effective_max_concurrent("garbage", user_override=4) == 4


def test_effective_max_concurrent_is_case_insensitive():
    # Profile names from UI forms may arrive title- or upper-cased. They must
    # resolve to the correct profile cap — NOT silently fall through to the
    # 'balanced' default, which would loosen a 'Conservative' user's 5-cap to 12.
    assert effective_max_concurrent("Conservative") == 5
    assert effective_max_concurrent("BALANCED", user_override=3) == 3
    assert effective_max_concurrent("Aggressive", user_override=50) == 20


def test_effective_max_concurrent_none_profile_uses_balanced():
    assert effective_max_concurrent(None) == 12  # type: ignore[arg-type]


def test_effective_max_concurrent_defensive_coercion_of_invalid_values():
    # Zero / negative override = ignored (DB CHECK enforces 1..20 at write time;
    # this defends against legacy rows / direct DB writes).
    assert effective_max_concurrent("balanced", user_override=0) == 12
    assert effective_max_concurrent("balanced", user_override=-5) == 12
    # Non-int coerces; if conversion fails the helper treats it as 0 → ignored.
    assert effective_max_concurrent("balanced", user_override="not-a-number") == 12


# --------------------------------------------------------------------------- gate step 7 integration


def test_gate_step_7_rejects_when_open_count_at_profile_cap_and_no_override(monkeypatch):
    # balanced cap = 12; open_count = 12 → reject step 7.
    _patch_clear(monkeypatch, open_count=12)
    res = asyncio.run(evaluate(_ctx(risk_profile="balanced")))
    assert res.approved is False
    assert res.reason == "max_concurrent_trades"
    assert res.failed_step == 7


def test_gate_step_7_rejects_when_user_override_tighter_than_profile(monkeypatch):
    # balanced cap = 12; user_override = 3; open_count = 3 → reject (3 >= 3).
    _patch_clear(monkeypatch, open_count=3)
    res = asyncio.run(evaluate(_ctx(risk_profile="balanced", max_concurrent_override=3)))
    assert res.approved is False
    assert res.reason == "max_concurrent_trades"
    assert res.failed_step == 7


def test_gate_step_7_passes_when_open_below_effective_cap(monkeypatch):
    # balanced cap = 12; user_override = 5; open_count = 4 → passes step 7.
    _patch_clear(monkeypatch, open_count=4)
    res = asyncio.run(evaluate(_ctx(risk_profile="balanced", max_concurrent_override=5)))
    assert res.approved is True


def test_gate_step_7_user_override_cannot_loosen_above_profile_cap(monkeypatch):
    # conservative cap = 5; user_override = 999 — must NOT loosen.
    # open_count = 5 → still reject at step 7 (effective cap is 5, not 999).
    _patch_clear(monkeypatch, open_count=5)
    res = asyncio.run(evaluate(
        _ctx(risk_profile="conservative", max_concurrent_override=999)
    ))
    assert res.approved is False
    assert res.reason == "max_concurrent_trades"
    assert res.failed_step == 7


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


def test_resume_step_7_user_override_cannot_loosen(monkeypatch):
    # conservative cap = 5; user tries override 999; open_count = 5 → still rejected.
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
    assert res.approved is False
    assert res.reason == "max_concurrent_trades"
    assert res.failed_step == 7


# --------------------------------------------------------------------------- dead-constant removal


def test_max_concurrent_trades_constant_is_removed():
    # The dead ``MAX_CONCURRENT_TRADES = 5`` constant is gone; gate step 7
    # enforces per-profile caps (5/12/20) via ``effective_max_concurrent``.
    assert not hasattr(K, "MAX_CONCURRENT_TRADES")


def test_every_profile_has_max_concurrent_in_safe_range():
    # Hardening audit (audit_risk_constants) enforces 1 ≤ v ≤ 50 per profile.
    for name, profile in PROFILES.items():
        mc = profile.get("max_concurrent")
        assert mc is not None, f"{name} missing max_concurrent"
        assert 1 <= int(mc) <= 50, f"{name} max_concurrent {mc} out of range"
