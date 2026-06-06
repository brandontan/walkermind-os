"""WARP-78 Phase 3 — factor-weighted EV-comparator tests.

Validates derive_ev_model (v2 with factor weights + norm), EVComparator
factor-conditioned estimate_ev/select, holdout A/B, abstain logic, v1
compat, and the neutral fallback. Hermetic — no DB.
"""
from __future__ import annotations

import json
import math
import pathlib
import tempfile

import pytest

from projects.polymarket.crusaderbot.domain.strategy.ev_comparator import (
    ABSTAIN_EV_THRESHOLD,
    EV_COMPARATOR_SCHEMA_VERSION,
    ORCHESTRATOR_ACTIVE,
    EVComparator,
    derive_ev_model,
    ev_ab_compare,
    evaluate_ev_holdout,
    write_ev_model,
)


def _row(
    fav_side: str, fav_price: float, outcome: str,
    sc_outcome: str | None = None,
    momentum: float | None = 0.5,
    oracle_edge: float | None = 0.05,
    spread: float | None = 0.01,
    rule: str | None = "close_sweep",
) -> dict:
    return {
        "asset": "BTC", "timeframe": "5m",
        "fav_side": fav_side, "fav_price": fav_price,
        "realized_outcome": outcome, "realized_outcome_safe_close": sc_outcome,
        "momentum": momentum, "volatility_sigma": 0.01,
        "liquidity_usdc": 1000.0, "spread": spread,
        "orderbook_depth_usdc": 2000.0, "ttl_sec": 60.0,
        "oracle_edge": oracle_edge, "realized_vol": None,
        "router_selected_rule": rule, "evaluated_rule": rule,
    }


# ---------------------------------------------------------------------------
# derive_ev_model v2 (factor weights)
# ---------------------------------------------------------------------------


def test_derive_model_has_weights_and_norm():
    rows = [_row("YES", 0.7, "UP"), _row("YES", 0.7, "DOWN"), _row("YES", 0.7, "UP")]
    model = derive_ev_model(rows)
    assert model["schema_version"] == 2
    btc = model["cells"]["BTC/5m"]
    assert "norm" in btc
    assert "rules" in btc
    cs = btc["rules"]["close_sweep"]
    assert "weights" in cs
    assert "base_ev" in cs
    assert "mean_ev" in cs


def test_derive_model_weights_nonzero_for_varying_factor():
    rows = []
    for i in range(20):
        oe = 0.02 + i * 0.005
        outcome = "UP" if i % 2 == 0 else "DOWN"
        rows.append(_row("YES", 0.6, outcome, oracle_edge=oe))
    model = derive_ev_model(rows, shrinkage_k=0.0)
    btc = model["cells"]["BTC/5m"]
    cs_w = btc["rules"]["close_sweep"]["weights"]
    assert cs_w.get("oracle_edge", 0.0) != 0.0, "oracle_edge weight should be nonzero"


def test_derive_model_weights_zero_for_constant_factor():
    rows = [_row("YES", 0.6, "UP", momentum=0.5)] * 10
    model = derive_ev_model(rows, shrinkage_k=0.0)
    btc = model["cells"]["BTC/5m"]
    cs_w = btc["rules"]["close_sweep"]["weights"]
    assert cs_w.get("momentum", 0.0) == 0.0, "constant factor weight should be 0"


def test_shrinkage_reduces_base_ev():
    rows = [_row("YES", 0.6, "UP")] * 2
    model_k10 = derive_ev_model(rows, shrinkage_k=10.0)
    model_k0 = derive_ev_model(rows, shrinkage_k=0.0)
    ev_k10 = model_k10["cells"]["BTC/5m"]["rules"]["close_sweep"]["base_ev"]
    ev_k0 = model_k0["cells"]["BTC/5m"]["rules"]["close_sweep"]["base_ev"]
    assert abs(ev_k10) < abs(ev_k0)


def test_safe_close_uses_sc_horizon():
    rows = [
        _row("YES", 0.6, "UP", sc_outcome="DOWN"),
        _row("YES", 0.6, "UP", sc_outcome="DOWN"),
        _row("YES", 0.6, "UP", sc_outcome="DOWN"),
    ]
    model = derive_ev_model(rows, shrinkage_k=0.0)
    btc = model["cells"]["BTC/5m"]["rules"]
    assert btc["safe_close"]["mean_ev"] < 0
    assert btc["close_sweep"]["mean_ev"] > 0


# ---------------------------------------------------------------------------
# EVComparator factor-weighted selection
# ---------------------------------------------------------------------------


def _v2_model() -> dict:
    return {
        "schema_version": 2, "shrinkage_k": 0.0, "abstain_threshold": 0.0,
        "factors": ["momentum", "volatility_sigma", "liquidity_usdc", "spread",
                     "orderbook_depth_usdc", "ttl_sec", "oracle_edge"],
        "cells": {
            "BTC/5m": {
                "norm": {
                    "momentum": {"mean": 0.0, "std": 1.0},
                    "volatility_sigma": {"mean": 0.01, "std": 0.0},
                    "liquidity_usdc": {"mean": 1000.0, "std": 500.0},
                    "spread": {"mean": 0.02, "std": 0.01},
                    "orderbook_depth_usdc": {"mean": 2000.0, "std": 0.0},
                    "ttl_sec": {"mean": 120.0, "std": 60.0},
                    "oracle_edge": {"mean": 0.03, "std": 0.02},
                },
                "rules": {
                    "close_sweep": {"n": 50, "mean_ev": 0.02, "base_ev": 0.02,
                                    "weights": {"oracle_edge": -0.05, "spread": -0.03,
                                                "momentum": 0.01, "volatility_sigma": 0.0,
                                                "liquidity_usdc": 0.0, "orderbook_depth_usdc": 0.0,
                                                "ttl_sec": 0.01}},
                    "safe_close": {"n": 50, "mean_ev": 0.06, "base_ev": 0.06,
                                   "weights": {"oracle_edge": -0.04, "spread": -0.02,
                                               "momentum": 0.0, "volatility_sigma": 0.0,
                                               "liquidity_usdc": 0.0, "orderbook_depth_usdc": 0.0,
                                               "ttl_sec": 0.0}},
                    "flip_hunter": {"n": 50, "mean_ev": -0.01, "base_ev": -0.01,
                                    "weights": {"oracle_edge": 0.03, "spread": 0.0,
                                                "momentum": 0.0, "volatility_sigma": 0.0,
                                                "liquidity_usdc": 0.0, "orderbook_depth_usdc": 0.0,
                                                "ttl_sec": 0.0}},
                },
            }
        },
    }


def test_select_with_factors_picks_highest_ev():
    cmp = EVComparator.from_model(_v2_model())
    pick = cmp.select("BTC/5m", ["close_sweep", "safe_close", "flip_hunter"],
                       factors={"oracle_edge": 0.03, "spread": 0.02})
    assert pick == "safe_close"


def test_select_without_factors_uses_base_ev():
    cmp = EVComparator.from_model(_v2_model())
    pick = cmp.select("BTC/5m", ["close_sweep", "safe_close", "flip_hunter"])
    assert pick == "safe_close"


def test_factor_adjustment_can_flip_ranking():
    """High oracle_edge flips ranking: close_sweep loses (-0.05 weight), flip_hunter gains (+0.03)."""
    m = _v2_model()
    m["cells"]["BTC/5m"]["rules"]["close_sweep"]["base_ev"] = 0.065
    m["cells"]["BTC/5m"]["rules"]["safe_close"]["base_ev"] = 0.060
    cmp = EVComparator.from_model(m)
    assert cmp.select("BTC/5m", ["close_sweep", "safe_close", "flip_hunter"]) == "close_sweep"
    # z = (0.10 - 0.03)/0.02 = 3.5 → cs: 0.065+(-0.05*3.5)=-0.11, fh: -0.01+(0.03*3.5)=0.095
    factors = {"oracle_edge": 0.10}
    assert cmp.select("BTC/5m", ["close_sweep", "safe_close", "flip_hunter"], factors=factors) == "flip_hunter"


def test_select_abstains_when_all_below_threshold():
    model = {
        "schema_version": 2, "abstain_threshold": 0.0,
        "cells": {"BTC/5m": {"rules": {
            "close_sweep": {"n": 5, "mean_ev": -0.02, "base_ev": -0.02, "weights": {}},
            "safe_close":  {"n": 5, "mean_ev": -0.05, "base_ev": -0.05, "weights": {}},
            "flip_hunter": {"n": 5, "mean_ev": -0.01, "base_ev": -0.01, "weights": {}},
        }, "norm": {}}},
    }
    cmp = EVComparator.from_model(model)
    assert cmp.select("BTC/5m", ["close_sweep", "safe_close", "flip_hunter"]) is None


def test_v1_compat_flat_cell_keys():
    """v1 model (rules at cell root, no 'rules' wrapper) still works."""
    model = {
        "schema_version": 1, "abstain_threshold": 0.0,
        "cells": {
            "BTC/5m": {
                "close_sweep": {"n": 10, "shrunk_ev": 0.05},
                "safe_close":  {"n": 10, "shrunk_ev": 0.08},
                "flip_hunter": {"n": 10, "shrunk_ev": 0.01},
            }
        },
    }
    cmp = EVComparator.from_model(model)
    assert cmp.select("BTC/5m", ["close_sweep", "safe_close", "flip_hunter"]) == "safe_close"


def test_neutral_comparator_always_abstains():
    cmp = EVComparator.neutral()
    assert cmp.select("BTC/5m", ["close_sweep", "safe_close", "flip_hunter"]) is None
    assert not cmp.trained


def test_orchestrator_active_is_false():
    assert ORCHESTRATOR_ACTIVE is False


def test_schema_version_is_two():
    assert EV_COMPARATOR_SCHEMA_VERSION == 2


# ---------------------------------------------------------------------------
# write / from_file round-trip
# ---------------------------------------------------------------------------


def test_write_and_load_roundtrip():
    rows = [_row("YES", 0.65, "UP")] * 5 + [_row("YES", 0.65, "DOWN")] * 3
    model = derive_ev_model(rows)
    with tempfile.TemporaryDirectory() as td:
        path = pathlib.Path(td) / "ev_model.json"
        written = write_ev_model(model, path)
        assert written == path
        cmp = EVComparator.from_file(path)
        assert cmp.trained
        assert cmp.estimate_ev("BTC/5m", "close_sweep") is not None


# ---------------------------------------------------------------------------
# ev_ab_compare + evaluate_ev_holdout
# ---------------------------------------------------------------------------


def test_ev_ab_compare_basic():
    rows = [_row("YES", 0.6, "UP", rule="safe_close")] * 10
    model = derive_ev_model(rows, shrinkage_k=0.0)
    cmp = EVComparator.from_model(model)
    result = ev_ab_compare(rows, cmp)
    overall = result["overall"]
    assert overall["n"] == 10
    assert overall["router_avg_ev"] is not None
    assert overall["comp_avg_ev"] is not None


def test_evaluate_ev_holdout_returns_result():
    rows = [_row("YES", 0.6, "UP", rule="safe_close")] * 8
    rows += [_row("YES", 0.6, "DOWN", rule="close_sweep")] * 4
    result = evaluate_ev_holdout(rows)
    assert "overall" in result
    assert "_model_summary" in result
    assert result["_model_summary"]["train_rows"] > 0
    assert result["_model_summary"]["test_rows"] > 0
