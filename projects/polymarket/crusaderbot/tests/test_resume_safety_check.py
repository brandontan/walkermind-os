"""Hermetic tests for the crash-recovery capital-circuit-breaker re-check.

WARP/ROOT/risk-path-hardening:
  * C-1 — resume_safety_check re-runs gate steps 5/6/7/8/15 on a queued-row
          resume so the full-gate bypass cannot outrun an account circuit
          breaker (daily-loss, drawdown, concurrent, exposure, live cap).
  * C-2 — every domain strategy (incl. "weather") is routable at gate step 4.
  * MED-2 — registered strategies are all present in STRATEGY_AVAILABILITY.

No DB, no broker, no Telegram. All gate DB helpers patched.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from projects.polymarket.crusaderbot.domain.risk import gate as gate_mod
from projects.polymarket.crusaderbot.domain.risk.constants import (
    STRATEGY_AVAILABILITY,
)
from projects.polymarket.crusaderbot.domain.risk.gate import resume_safety_check

_USER = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
_MARKET = "market-resume-001"


def _patch_clear(monkeypatch, *, balance=1000.0, pnl=0.0, dd=False,
                 open_count=0, open_exp=0.0, open_live=0.0):
    """Patch every gate DB helper to a clear (passing) baseline."""
    monkeypatch.setattr(gate_mod, "_log", AsyncMock(return_value=None))
    monkeypatch.setattr(gate_mod, "daily_pnl", AsyncMock(return_value=Decimal(str(pnl))))
    monkeypatch.setattr(gate_mod, "get_balance", AsyncMock(return_value=Decimal(str(balance))))
    monkeypatch.setattr(gate_mod, "_max_drawdown_breached", AsyncMock(return_value=dd))
    monkeypatch.setattr(gate_mod, "_open_position_count", AsyncMock(return_value=open_count))
    monkeypatch.setattr(gate_mod, "_open_exposure", AsyncMock(return_value=Decimal(str(open_exp))))
    monkeypatch.setattr(gate_mod, "_open_live_exposure", AsyncMock(return_value=Decimal(str(open_live))))


def _run(**kw):
    base = dict(
        user_id=_USER, market_id=_MARKET, risk_profile="balanced",
        proposed_size_usdc=Decimal("100"), trading_mode="paper",
        chosen_mode="paper",
    )
    base.update(kw)
    return asyncio.run(resume_safety_check(**base))


# --------------------------------------------------------------------------- C-1


def test_resume_all_clear_approves(monkeypatch):
    _patch_clear(monkeypatch)
    res = _run()
    assert res.approved is True
    assert res.reason == "resume_safety_ok"


def test_resume_zero_balance_blocks(monkeypatch):
    # Mirrors gate step 0 cap 0: a zero/negative balance must never resume a
    # new position, and must fail before the exposure division.
    _patch_clear(monkeypatch, balance=0.0)
    res = _run()
    assert res.approved is False
    assert res.failed_step == 0
    assert res.reason == "balance_zero_or_negative"


def test_resume_negative_balance_blocks(monkeypatch):
    _patch_clear(monkeypatch, balance=-5.0)
    res = _run()
    assert res.approved is False
    assert res.failed_step == 0


def test_resume_daily_loss_blocks(monkeypatch):
    # balanced cap = -500; pnl -600 breaches.
    _patch_clear(monkeypatch, pnl=-600.0)
    res = _run()
    assert res.approved is False
    assert res.failed_step == 5
    assert res.reason == "daily_loss_cap_hit"


def test_resume_drawdown_blocks(monkeypatch):
    _patch_clear(monkeypatch, dd=True)
    res = _run()
    assert res.approved is False
    assert res.failed_step == 6


def test_resume_concurrent_blocks(monkeypatch):
    # balanced max_concurrent = 12
    _patch_clear(monkeypatch, open_count=12)
    res = _run()
    assert res.approved is False
    assert res.failed_step == 7


def test_resume_exposure_blocks(monkeypatch):
    # open 350 + proposed 100 = 450 / 1000 = 0.45 > MAX_CORRELATED_EXPOSURE 0.40
    _patch_clear(monkeypatch, open_exp=350.0)
    res = _run()
    assert res.approved is False
    assert res.failed_step == 8


def test_resume_live_not_opted_in_blocks(monkeypatch):
    _patch_clear(monkeypatch)
    res = _run(chosen_mode="live", trading_mode="live", live_capital_cap_usdc=0.0)
    assert res.approved is False
    assert res.failed_step == 15
    assert res.reason == "live_not_opted_in"


def test_resume_live_cap_exceeded_blocks(monkeypatch):
    # open_live 60 + proposed 100 = 160 > cap 100
    _patch_clear(monkeypatch, open_live=60.0)
    res = _run(chosen_mode="live", trading_mode="live", live_capital_cap_usdc=100.0)
    assert res.approved is False
    assert res.failed_step == 15
    assert res.reason == "live_capital_cap_exceeded"


def test_resume_live_within_cap_approves(monkeypatch):
    _patch_clear(monkeypatch, open_live=20.0)
    res = _run(chosen_mode="live", trading_mode="live", live_capital_cap_usdc=500.0)
    assert res.approved is True


def test_resume_paper_skips_live_cap(monkeypatch):
    # paper resume with cap=0 must still approve — live cap is live-only.
    _patch_clear(monkeypatch)
    res = _run(chosen_mode="paper", live_capital_cap_usdc=0.0)
    assert res.approved is True


# --------------------------------------------------------------------------- C-2


def test_weather_strategy_is_routable():
    assert "weather" in STRATEGY_AVAILABILITY
    assert set(STRATEGY_AVAILABILITY["weather"]) >= {
        "conservative", "balanced", "aggressive", "custom",
    }


# --------------------------------------------------------------------------- MED-2


def test_every_registered_domain_strategy_is_in_availability():
    from projects.polymarket.crusaderbot.domain.strategy.registry import (
        StrategyRegistry,
        bootstrap_default_strategies,
    )
    StrategyRegistry._reset_for_tests()
    bootstrap_default_strategies()
    names = [s["name"] for s in StrategyRegistry.instance().list_available()]
    missing = [n for n in names if n not in STRATEGY_AVAILABILITY]
    assert missing == [], f"strategies unroutable at gate step 4: {missing}"
