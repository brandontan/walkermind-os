"""TP/SL sourcing + Custom Risk TP-only/SL-only. Hermetic; no DB/network.

WARP-83 E.2 (Path C): TP/SL is a STRATEGY-LEVEL property (150% / 50%), the SAME
for every non-custom profile. Risk profile governs CAPITAL SIZING only
(capital_alloc_pct differs per profile). The canonical tp_sl_for_profile now
returns the strategy default for conservative/balanced/aggressive; custom stays
user-supplied (advanced override)."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from projects.polymarket.crusaderbot.domain.risk import constants as risk_const
from projects.polymarket.crusaderbot.webtrader.backend import router as r
from projects.polymarket.crusaderbot.webtrader.backend.schemas import RiskProfileRequest


# ── canonical tp/sl per profile ───────────────────────────────────────────────

def test_tp_sl_for_profile_canonical_values():
    # Path C: TP/SL is the strategy default (1.5 / 0.5) for EVERY non-custom
    # profile; only capital_alloc_pct differs per profile.
    assert risk_const.tp_sl_for_profile("balanced") == {
        "capital_alloc_pct": 0.40, "tp_pct": 1.5, "sl_pct": 0.5}
    assert risk_const.tp_sl_for_profile("aggressive")["tp_pct"] == 1.5
    assert risk_const.tp_sl_for_profile("aggressive")["sl_pct"] == 0.5
    assert risk_const.tp_sl_for_profile("conservative")["tp_pct"] == 1.5
    assert risk_const.tp_sl_for_profile("conservative")["sl_pct"] == 0.5
    # Capital sizing still differs per profile (the only per-profile knob).
    assert risk_const.tp_sl_for_profile("conservative")["capital_alloc_pct"] == 0.20
    assert risk_const.tp_sl_for_profile("aggressive")["capital_alloc_pct"] == 0.60


def test_tp_sl_for_profile_defaults_to_balanced():
    assert risk_const.tp_sl_for_profile(None) == risk_const.tp_sl_for_profile("balanced")
    assert risk_const.tp_sl_for_profile("garbage") == risk_const.tp_sl_for_profile("balanced")


def test_close_sweep_preset_routes_strategy_default_tpsl():
    # close_sweep maps to the balanced profile → TP/SL resolves to the strategy
    # default (1.5 / 0.5), NOT the preset's own tp_pct/sl_pct and NOT a
    # per-profile bundle.
    prof = r._PRESET_PARAMS["close_sweep"]["risk_profile"]
    ts = risk_const.tp_sl_for_profile(str(prof))
    assert (ts["tp_pct"], ts["sl_pct"]) == (1.5, 0.5)


# ── custom risk: TP-only / SL-only ────────────────────────────────────────────

def _ctx(value=None):
    cm = MagicMock(); cm.__aenter__ = AsyncMock(return_value=value); cm.__aexit__ = AsyncMock(return_value=False); return cm

def _pool(conn):
    p = MagicMock(); p.acquire = MagicMock(return_value=_ctx(conn)); return p

def _run_set_profile(body):
    conn = MagicMock(); conn.execute = AsyncMock()
    with patch.object(r, "get_pool", return_value=_pool(conn)):
        return asyncio.run(r.set_risk_profile(body, {"user_id": "u"}))


def test_custom_tp_only_allowed():
    out = _run_set_profile(RiskProfileRequest(profile="custom", capital_alloc_pct=0.30, tp_pct=0.25, sl_pct=None))
    assert out["tp_pct"] == 0.25
    assert out["sl_pct"] is None


def test_custom_sl_only_allowed():
    out = _run_set_profile(RiskProfileRequest(profile="custom", capital_alloc_pct=0.30, tp_pct=None, sl_pct=0.15))
    assert out["sl_pct"] == 0.15
    assert out["tp_pct"] is None


def test_custom_requires_at_least_one_of_tp_sl():
    with pytest.raises(Exception) as exc:
        _run_set_profile(RiskProfileRequest(profile="custom", capital_alloc_pct=0.30, tp_pct=None, sl_pct=None))
    assert "at least one" in str(exc.value) or "422" in str(exc.value)


def test_custom_both_set_still_enforces_tp_gt_sl():
    with pytest.raises(Exception) as exc:
        _run_set_profile(RiskProfileRequest(profile="custom", capital_alloc_pct=0.30, tp_pct=0.10, sl_pct=0.20))
    assert "greater than" in str(exc.value) or "422" in str(exc.value)


def test_custom_requires_capital():
    with pytest.raises(Exception) as exc:
        _run_set_profile(RiskProfileRequest(profile="custom", capital_alloc_pct=None, tp_pct=0.2, sl_pct=0.1))
    assert "capital" in str(exc.value) or "422" in str(exc.value)


def test_standard_profile_resolves_tp_sl_from_defaults():
    # Path C: a standard profile activation seeds the strategy default TP/SL
    # (1.5 / 0.5) — the same for every profile — with per-profile capital.
    out = _run_set_profile(RiskProfileRequest(profile="aggressive"))
    assert (out["tp_pct"], out["sl_pct"]) == (1.5, 0.5)
    assert out["capital_alloc_pct"] == 0.60


def test_conservative_same_tpsl_as_balanced_but_smaller_capital():
    # Path C invariant: conservative risks fewer dollars (smaller capital) but
    # uses the SAME TP/SL as balanced — it does not exit faster.
    cons = _run_set_profile(RiskProfileRequest(profile="conservative"))
    bal = _run_set_profile(RiskProfileRequest(profile="balanced"))
    assert (cons["tp_pct"], cons["sl_pct"]) == (bal["tp_pct"], bal["sl_pct"]) == (1.5, 0.5)
    assert cons["capital_alloc_pct"] < bal["capital_alloc_pct"]
