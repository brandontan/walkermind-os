"""Hermetic tests for WARP/ROOT/concurrency-policy (Lane 3C) + WARP-54 lane.

max_concurrent is a per-user override (tighter-only) on top of the per-profile
intents (conservative=5 / balanced=12 / aggressive=20). WARP-54 follow-up lane
reconciles the AGENTS.md RISK CONSTANTS hard rule ("Max concurrent trades = 5"):
the ``MAX_CONCURRENT_TRADES = 5`` system ceiling folds into
``effective_max_concurrent`` so every effective cap is min(5, profile, override)
— no profile, override, or settings value can ever loosen a user past 5. The
global open-position cap (gate Cap 4) is likewise clamped to
min(MAX_OPEN_POSITIONS, 5), so for a no-tighter-override user Cap 4 enforces the
ceiling before step 7 is reached. Per-profile audit coverage stays in
``hardening.audit_risk_constants`` (1..50 range); the gate (step 7) +
``resume_safety_check`` (step 7) consume ``effective_max_concurrent``.

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


def test_effective_max_concurrent_ceilings_every_profile_at_hard_max():
    # MAX_CONCURRENT_TRADES=5 is the non-overridable system ceiling, so the
    # balanced(12)/aggressive(20) profile intents are clamped to 5 too
    # (AGENTS.md RISK CONSTANTS = 5; WARP-54 reconciliation).
    assert effective_max_concurrent("conservative") == 5
    assert effective_max_concurrent("balanced") == 5
    assert effective_max_concurrent("aggressive") == 5
    assert effective_max_concurrent("custom") == 5


def test_effective_max_concurrent_user_override_tightens():
    assert effective_max_concurrent("balanced", user_override=3) == 3
    # Override above the hard ceiling cannot loosen — clamps to 5.
    assert effective_max_concurrent("aggressive", user_override=10) == 5
    assert effective_max_concurrent("conservative", user_override=2) == 2


def test_effective_max_concurrent_user_override_cannot_loosen():
    # Neither profile cap NOR hard ceiling can be loosened by a larger override.
    assert effective_max_concurrent("conservative", user_override=10) == 5
    assert effective_max_concurrent("balanced", user_override=50) == 5
    assert effective_max_concurrent("aggressive", user_override=999) == 5


def test_effective_max_concurrent_unknown_profile_falls_back_to_balanced():
    # Unknown profile -> balanced intent (12), then clamped by the 5 ceiling.
    assert effective_max_concurrent("garbage") == 5
    assert effective_max_concurrent("garbage", user_override=4) == 4


def test_effective_max_concurrent_is_case_insensitive():
    # Profile names from UI forms may arrive title- or upper-cased. They must
    # resolve to a real profile (not silently fall through to 'balanced'); the
    # effective cap is then bounded by the hard ceiling of 5 regardless.
    assert effective_max_concurrent("Conservative") == 5
    assert effective_max_concurrent("BALANCED", user_override=3) == 3
    assert effective_max_concurrent("Aggressive", user_override=50) == 5


def test_effective_max_concurrent_none_profile_uses_balanced():
    # None -> balanced intent (12), clamped by the hard ceiling to 5.
    assert effective_max_concurrent(None) == 5  # type: ignore[arg-type]


def test_effective_max_concurrent_defensive_coercion_of_invalid_values():
    # Zero / negative override = ignored (DB CHECK enforces 1..20 at write time;
    # this defends against legacy rows / direct DB writes). Falls back to the
    # ceiling-clamped profile cap (balanced 12 -> 5).
    assert effective_max_concurrent("balanced", user_override=0) == 5
    assert effective_max_concurrent("balanced", user_override=-5) == 5
    # Non-int coerces; if conversion fails the helper treats it as 0 → ignored.
    assert effective_max_concurrent("balanced", user_override="not-a-number") == 5


# --------------------------------------------------------------------------- gate step 7 integration


def test_gate_cap4_rejects_at_hard_ceiling_when_no_tighter_override(monkeypatch):
    # No tighter override: the global open-position hard ceiling
    # (Cap 4 = min(MAX_OPEN_POSITIONS, 5)) fires first at open_count 5 >= 5,
    # before step 7 is reached. This is the WARP-54 reconciliation enforcing
    # the AGENTS.md hard rule of 5 even for balanced (profile intent 12).
    _patch_clear(monkeypatch, open_count=5)
    res = asyncio.run(evaluate(_ctx(risk_profile="balanced")))
    assert res.approved is False
    assert res.reason == "max_open_positions_5_reached"
    assert res.failed_step == 0


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


def test_gate_user_override_cannot_loosen_above_hard_ceiling(monkeypatch):
    # aggressive profile intent = 20, user_override = 999 — neither can loosen
    # past the hard ceiling of 5. At open_count 5 the global Cap 4 rejects
    # (max_open_positions_5_reached) before the loosened cap is ever consulted.
    _patch_clear(monkeypatch, open_count=5)
    res = asyncio.run(evaluate(
        _ctx(risk_profile="aggressive", max_concurrent_override=999)
    ))
    assert res.approved is False
    assert res.reason == "max_open_positions_5_reached"
    assert res.failed_step == 0


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


def test_max_concurrent_trades_hard_ceiling_constant():
    # WARP-54 reconciliation: the system hard ceiling constant exists and equals
    # the AGENTS.md RISK CONSTANT (5). It folds into effective_max_concurrent so
    # no profile/override/settings value can exceed it.
    assert hasattr(K, "MAX_CONCURRENT_TRADES")
    assert K.MAX_CONCURRENT_TRADES == 5


def test_every_profile_has_max_concurrent_in_safe_range():
    # Hardening audit (audit_risk_constants) enforces 1 ≤ v ≤ 50 per profile.
    for name, profile in PROFILES.items():
        mc = profile.get("max_concurrent")
        assert mc is not None, f"{name} missing max_concurrent"
        assert 1 <= int(mc) <= 50, f"{name} max_concurrent {mc} out of range"
