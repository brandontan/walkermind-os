"""PR #1 — TP/SL come from the risk profile (not the preset) + Custom Risk
allows TP-only or SL-only. Hermetic; no DB/network."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from projects.polymarket.crusaderbot.domain.risk import constants as risk_const
from projects.polymarket.crusaderbot.webtrader.backend import router as r
from projects.polymarket.crusaderbot.webtrader.backend.schemas import RiskProfileRequest


# ── canonical tp/sl per profile ───────────────────────────────────────────────

def test_tp_sl_for_profile_canonical_values():
    assert risk_const.tp_sl_for_profile("balanced") == {
        "capital_alloc_pct": 0.40, "tp_pct": 0.20, "sl_pct": 0.15}
    assert risk_const.tp_sl_for_profile("aggressive")["tp_pct"] == 0.30
    assert risk_const.tp_sl_for_profile("aggressive")["sl_pct"] == 0.20
    assert risk_const.tp_sl_for_profile("conservative")["tp_pct"] == 0.10


def test_tp_sl_for_profile_defaults_to_balanced():
    assert risk_const.tp_sl_for_profile(None) == risk_const.tp_sl_for_profile("balanced")
    assert risk_const.tp_sl_for_profile("garbage") == risk_const.tp_sl_for_profile("balanced")


def test_close_sweep_preset_routes_balanced_profile():
    # close_sweep maps to the balanced profile → TP/SL must resolve to 0.20/0.15,
    # NOT the preset's wide 0.90/0.40.
    prof = r._PRESET_PARAMS["close_sweep"]["risk_profile"]
    ts = risk_const.tp_sl_for_profile(str(prof))
    assert (ts["tp_pct"], ts["sl_pct"]) == (0.20, 0.15)


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
    out = _run_set_profile(RiskProfileRequest(profile="aggressive"))
    assert (out["tp_pct"], out["sl_pct"]) == (0.30, 0.20)
