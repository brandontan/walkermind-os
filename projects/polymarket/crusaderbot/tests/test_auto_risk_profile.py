"""WARP-86 Phase 0b: AUTO risk profile.

AUTO is a single EV-driven profile = Kelly a=0.25 sizing + candle_auto entry
constraint + strategy-owned TP/SL (1.5/0.5 via late_entry_v3.default_tp_sl()).
Hermetic — no DB / network; the gate's DB-touching steps are mocked.

Covered:
  1. AUTO resolves: profile_or_default('auto')['kelly'] == 0.25 and the gate
     Kelly clamp min(profile['kelly'], KELLY_FRACTION) == 0.25.
  2. AUTO TP/SL delegates to the STRATEGY hook (late_entry_v3.default_tp_sl()
     == (1.5, 0.5)) — NOT a hardcoded risk-stage value.
  3. AUTO + non-candle_auto preset (None / 'safe_close') → gate rejects with
     reason 'auto_requires_candle_auto' + warning; AUTO + candle_auto passes
     that check.
  4. API accepts risk_profile='auto' (membership + non-custom default seed).
"""
from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from projects.polymarket.crusaderbot import config as crusaderbot_config
from projects.polymarket.crusaderbot.domain.risk import constants as K
from projects.polymarket.crusaderbot.domain.risk import gate as gate_mod
from projects.polymarket.crusaderbot.domain.risk.gate import GateContext, GateResult
from projects.polymarket.crusaderbot.domain.strategy.strategies.late_entry_v3 import (
    LateEntryV3Strategy,
)
from projects.polymarket.crusaderbot.webtrader.backend import router as r
from projects.polymarket.crusaderbot.webtrader.backend.schemas import RiskProfileRequest


@pytest.fixture(autouse=True)
def _settings_env(monkeypatch):
    # gate.evaluate() calls get_settings(); supply the required env (hermetic —
    # never reaches a real DB/network because the DB-touching calls are mocked).
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("OPERATOR_CHAT_ID", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("WALLET_HD_SEED", "seed")
    monkeypatch.setenv("WALLET_ENCRYPTION_KEY", "k")
    monkeypatch.setenv("POLYGON_RPC_URL", "https://rpc")
    monkeypatch.setenv("ALCHEMY_POLYGON_WS_URL", "wss://ws")
    crusaderbot_config.get_settings.cache_clear()
    yield
    crusaderbot_config.get_settings.cache_clear()


# ── 1. AUTO resolves to Kelly 0.25 (reuses the existing gate clamp) ───────────

def test_auto_profile_resolves_kelly_025():
    prof = K.profile_or_default("auto")
    assert prof["kelly"] == 0.25
    # The gate's clamp (gate.py:~619): min(profile['kelly'], KELLY_FRACTION).
    # AUTO's 0.25 flows through unchanged — no Kelly duplication.
    assert min(float(prof["kelly"]), K.KELLY_FRACTION) == 0.25


def test_auto_caps_mirror_balanced_except_kelly():
    # DESIGN DECISION (WARP-86): AUTO's non-Kelly caps mirror 'balanced'; the
    # directive specified only kelly=0.25. This pins that decision so a drift
    # (or a deliberate SENTINEL-review change) is caught.
    auto = K.PROFILES["auto"]
    bal = K.PROFILES["balanced"]
    assert auto["kelly"] == 0.25
    assert bal["kelly"] == 0.20
    for key in ("max_pos_pct", "max_concurrent", "daily_loss",
                "min_edge_bps", "min_liquidity", "max_days"):
        assert auto[key] == bal[key], f"AUTO.{key} must mirror balanced"


def test_auto_full_kelly_forbidden_invariant():
    # AUTO must never exceed the global hard cap (full Kelly 1.0 forbidden).
    assert K.PROFILES["auto"]["kelly"] <= K.KELLY_FRACTION == 0.25


# ── 2. AUTO TP/SL delegates to the strategy hook (not risk-stage hardcode) ────

def test_auto_tp_sl_sourced_from_strategy_hook():
    # AUTO trades candle_auto → late_entry_v3. The runtime exit thresholds come
    # from the STRATEGY hook, not the risk stage.
    strat_tp_sl = LateEntryV3Strategy().default_tp_sl()
    assert strat_tp_sl == (1.5, 0.5)
    # The PROFILE_TP_SL['auto'] entry is only a bootstrap seed and must equal the
    # strategy default (1.5/0.5) — it is NOT an independent risk-stage exit value.
    seed = K.PROFILE_TP_SL["auto"]
    assert (seed["tp_pct"], seed["sl_pct"]) == strat_tp_sl


def test_auto_tp_sl_resolver_uses_strategy_default():
    # signal_scan_job._strategy_default_tp_sl reads the SAME strategy hook used at
    # runtime; for AUTO's late_entry_v3 it yields (1.5, 0.5). Confirms the NULL→
    # default fallback path (WARP-85/90) sources AUTO TP/SL from the strategy.
    from projects.polymarket.crusaderbot.services.signal_scan import (
        signal_scan_job as ssj,
    )
    assert ssj._strategy_default_tp_sl("late_entry_v3") == (1.5, 0.5)


# ── 3. AUTO entry constraint at the gate ──────────────────────────────────────

def _gate_ctx(*, risk_profile: str, active_preset, strategy_type="late_entry_v3"):
    return GateContext(
        user_id=uuid4(),
        telegram_user_id=1,
        role="user",
        auto_trade_on=True,
        paused=False,
        market_id="0xmarket",
        side="yes",
        proposed_size_usdc=Decimal("10"),
        proposed_price=0.5,
        market_liquidity=50_000.0,
        market_status="active",
        edge_bps=400.0,
        signal_ts=None,
        idempotency_key="k",
        strategy_type=strategy_type,
        risk_profile=risk_profile,
        daily_loss_override=None,
        trading_mode="paper",
        active_preset=active_preset,
    )


class _ReachedStep5(Exception):
    """Sentinel: raised by the mocked daily_pnl (gate step 5) to prove the
    candidate cleared the step-4 strategy-availability + AUTO-entry checks."""


def _run_gate_to_step4(ctx: GateContext) -> GateResult:
    """Drive evaluate() through the DB-touching steps 0-3 (mocked) to step 4.

    When step 4 REJECTS (e.g. AUTO + wrong preset) the GateResult is returned
    before step 5. When step 4 PASSES, the mocked daily_pnl at step 5 raises
    _ReachedStep5 — the caller treats that as "AUTO entry check passed".
    """
    approved = GateResult(True, "ok")
    with patch.object(gate_mod, "validate_risk_caps",
                      new=AsyncMock(return_value=approved)), \
         patch.object(gate_mod, "_log", new=AsyncMock()), \
         patch.object(gate_mod, "kill_switch_is_active",
                      new=AsyncMock(return_value=False)), \
         patch.object(gate_mod, "daily_pnl",
                      new=AsyncMock(side_effect=_ReachedStep5())):
        return asyncio.run(gate_mod.evaluate(ctx))


def test_auto_rejects_non_candle_auto_preset_none(caplog):
    ctx = _gate_ctx(risk_profile="auto", active_preset=None)
    with caplog.at_level(logging.WARNING, logger=gate_mod.logger.name):
        res = _run_gate_to_step4(ctx)
    assert res.approved is False
    assert res.reason == "auto_requires_candle_auto"
    assert res.failed_step == 4
    assert any("candle_auto" in rec.message for rec in caplog.records)


def test_auto_rejects_non_candle_auto_preset_safe_close():
    ctx = _gate_ctx(risk_profile="auto", active_preset="safe_close")
    res = _run_gate_to_step4(ctx)
    assert res.approved is False
    assert res.reason == "auto_requires_candle_auto"
    assert res.failed_step == 4


def test_auto_passes_step4_with_candle_auto():
    # AUTO + candle_auto must clear the strategy-availability + AUTO-entry checks.
    # Clearing step 4 means execution reaches step 5 (daily_pnl), which the mock
    # raises as _ReachedStep5 — proving no 'auto_requires_candle_auto' rejection.
    ctx = _gate_ctx(risk_profile="auto", active_preset="candle_auto")
    with pytest.raises(_ReachedStep5):
        _run_gate_to_step4(ctx)


def test_non_auto_profile_unaffected_by_preset():
    # 'balanced' on a non-candle_auto preset must NOT trip the AUTO entry fence —
    # it reaches step 5 like any normal candidate.
    ctx = _gate_ctx(risk_profile="balanced", active_preset="safe_close")
    with pytest.raises(_ReachedStep5):
        _run_gate_to_step4(ctx)


def test_auto_listed_only_on_late_entry_v3():
    # candle_auto routes ONLY to late_entry_v3 → 'auto' is allowed there alone.
    assert "auto" in K.STRATEGY_AVAILABILITY["late_entry_v3"]
    for strat, profiles in K.STRATEGY_AVAILABILITY.items():
        if strat != "late_entry_v3":
            assert "auto" not in profiles, f"'auto' must not be on {strat}"


# ── 4. API accepts risk_profile='auto' ────────────────────────────────────────

def test_api_valid_risk_profiles_includes_auto():
    assert "auto" in r._VALID_RISK_PROFILES


def _ctx(value=None):
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=value)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _pool(conn):
    p = MagicMock()
    p.acquire = MagicMock(return_value=_ctx(conn))
    return p


def test_api_set_risk_profile_auto_accepted():
    conn = MagicMock()
    conn.execute = AsyncMock()
    body = RiskProfileRequest(profile="auto")
    with patch.object(r, "get_pool", return_value=_pool(conn)):
        out = asyncio.run(r.set_risk_profile(body, {"user_id": "u"}))
    # No 400; non-custom 'auto' seeds the balanced-mirrored capital + strategy
    # default TP/SL (1.5/0.5) from PROFILE_TP_SL['auto'].
    assert out["risk_profile"] == "auto"
    assert out["capital_alloc_pct"] == 0.40
    assert (out["tp_pct"], out["sl_pct"]) == (1.5, 0.5)
