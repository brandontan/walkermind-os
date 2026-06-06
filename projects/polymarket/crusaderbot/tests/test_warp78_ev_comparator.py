"""WARP-78 Phase 2 — EV-comparator tests.

Validates derive_ev_model, EVComparator.rank/select, abstain logic, and
the neutral (model-absent) fallback. Hermetic — no DB.
"""
from __future__ import annotations

import json
import math
import pathlib
import tempfile

import pytest

from projects.polymarket.crusaderbot.domain.strategy.ev_comparator import (
    ABSTAIN_EV_THRESHOLD,
    ORCHESTRATOR_ACTIVE,
    EVComparator,
    derive_ev_model,
    write_ev_model,
)


def _row(fav_side: str, fav_price: float, outcome: str, sc_outcome: str | None = None) -> dict:
    return {
        "asset": "BTC", "timeframe": "5m",
        "fav_side": fav_side, "fav_price": fav_price,
        "realized_outcome": outcome, "realized_outcome_safe_close": sc_outcome,
    }


# ---------------------------------------------------------------------------
# derive_ev_model
# ---------------------------------------------------------------------------


def test_derive_model_basic():
    rows = [
        _row("YES", 0.7, "UP"),   # close_sweep wins: 1-0.7=+0.3; flip_hunter loses: -0.3
        _row("YES", 0.7, "UP"),
        _row("YES", 0.7, "DOWN"), # close_sweep loses: -0.7; flip_hunter wins: +0.7
    ]
    model = derive_ev_model(rows)
    assert model["schema_version"] == 1
    btc = model["cells"]["BTC/5m"]
    cs = btc["close_sweep"]
    fh = btc["flip_hunter"]
    # close_sweep: 2 wins +0.3, 1 loss -0.7 → mean = (0.3+0.3-0.7)/3 ≈ -0.033
    assert cs["n"] == 3
    assert abs(cs["mean_ev"] - (-0.7 + 0.3 + 0.3) / 3) < 1e-4
    # flip_hunter entries at 1-0.7=0.3; opposite wins: 1 win +0.7, 2 losses -0.3
    assert fh["n"] == 3


def test_shrinkage_reduces_ev_toward_zero():
    rows = [_row("YES", 0.6, "UP")] * 2  # small n
    model_k10 = derive_ev_model(rows, shrinkage_k=10.0)
    model_k0 = derive_ev_model(rows, shrinkage_k=0.0)
    cell_k10 = model_k10["cells"]["BTC/5m"]["close_sweep"]
    cell_k0 = model_k0["cells"]["BTC/5m"]["close_sweep"]
    # shrinkage_k=10 with n=2 → shrink factor 2/12 ≈ 0.167; k=0 → factor 1.0
    assert abs(cell_k10["shrunk_ev"]) < abs(cell_k0["shrunk_ev"])


def test_safe_close_uses_sc_horizon():
    rows = [
        _row("YES", 0.6, "UP", sc_outcome="DOWN"),  # sc_label differs
        _row("YES", 0.6, "UP", sc_outcome="DOWN"),
        _row("YES", 0.6, "UP", sc_outcome="DOWN"),
    ]
    model = derive_ev_model(rows, shrinkage_k=0.0)
    btc = model["cells"]["BTC/5m"]
    # safe_close uses sc label DOWN → loss for YES entry → ev = 0 - 0.6 = -0.6
    assert btc["safe_close"]["mean_ev"] < 0
    # close_sweep uses open→close UP → win → ev = 1 - 0.6 = +0.4
    assert btc["close_sweep"]["mean_ev"] > 0


# ---------------------------------------------------------------------------
# EVComparator.select
# ---------------------------------------------------------------------------


def test_select_picks_highest_shrunk_ev():
    model = {
        "schema_version": 1, "shrinkage_k": 0.0, "abstain_threshold": 0.0,
        "cells": {
            "BTC/5m": {
                "close_sweep": {"n": 10, "mean_ev": 0.05, "shrunk_ev": 0.05},
                "safe_close":  {"n": 10, "mean_ev": 0.08, "shrunk_ev": 0.08},
                "flip_hunter": {"n": 10, "mean_ev": 0.01, "shrunk_ev": 0.01},
            }
        },
    }
    cmp = EVComparator.from_model(model)
    assert cmp.select("BTC/5m", ["close_sweep", "safe_close", "flip_hunter"]) == "safe_close"


def test_select_abstains_when_all_below_threshold():
    # Inject model directly with all-negative shrunk_ev (impossible in practice since
    # flip_hunter is the inverse of close_sweep, but the comparator must handle it).
    model = {
        "schema_version": 1, "shrinkage_k": 0.0, "abstain_threshold": 0.0,
        "cells": {
            "BTC/5m": {
                "close_sweep": {"n": 5, "mean_ev": -0.02, "shrunk_ev": -0.02},
                "safe_close":  {"n": 5, "mean_ev": -0.05, "shrunk_ev": -0.05},
                "flip_hunter": {"n": 5, "mean_ev": -0.01, "shrunk_ev": -0.01},
            }
        },
    }
    cmp = EVComparator.from_model(model)
    assert cmp.select("BTC/5m", ["close_sweep", "safe_close", "flip_hunter"]) is None


def test_select_unknown_cell_abstains():
    model = {"schema_version": 1, "cells": {}}
    cmp = EVComparator.from_model(model)
    assert cmp.select("SOL/5m", ["close_sweep"]) is None


def test_neutral_comparator_always_abstains():
    cmp = EVComparator.neutral()
    assert cmp.select("BTC/5m", ["close_sweep", "safe_close", "flip_hunter"]) is None
    assert not cmp.trained


def test_orchestrator_active_is_false():
    assert ORCHESTRATOR_ACTIVE is False


# ---------------------------------------------------------------------------
# write_ev_model / from_file round-trip
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
        # The model stored is valid — at least one cell parsed
        assert cmp.estimate_ev("BTC/5m", "close_sweep") is not None
