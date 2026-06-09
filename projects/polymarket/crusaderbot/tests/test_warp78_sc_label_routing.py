"""WARP-78 Phase 2 — safe_close horizon label routing tests.

Validates that row_outcome_for_rule selects the correct outcome column per rule,
and that derive_cell / compare() use the horizon-correct label for safe_close.
"""
from __future__ import annotations

import pytest

from projects.polymarket.crusaderbot.domain.strategy.scorer import row_outcome_for_rule
from projects.polymarket.crusaderbot.domain.strategy.scorer_trainer import derive_cell


# ---------------------------------------------------------------------------
# row_outcome_for_rule
# ---------------------------------------------------------------------------


def test_safe_close_uses_sc_column_when_present():
    row = {"realized_outcome": "UP", "realized_outcome_safe_close": "DOWN"}
    assert row_outcome_for_rule("safe_close", row) == "DOWN"


def test_safe_close_falls_back_when_sc_null():
    row = {"realized_outcome": "UP", "realized_outcome_safe_close": None}
    assert row_outcome_for_rule("safe_close", row) == "UP"


def test_safe_close_falls_back_when_sc_absent():
    row = {"realized_outcome": "UP"}
    assert row_outcome_for_rule("safe_close", row) == "UP"


def test_close_sweep_always_uses_open_close():
    row = {"realized_outcome": "UP", "realized_outcome_safe_close": "DOWN"}
    assert row_outcome_for_rule("close_sweep", row) == "UP"


def test_flip_hunter_always_uses_open_close():
    row = {"realized_outcome": "DOWN", "realized_outcome_safe_close": "UP"}
    assert row_outcome_for_rule("flip_hunter", row) == "DOWN"


def test_unknown_rule_uses_open_close():
    row = {"realized_outcome": "UP", "realized_outcome_safe_close": "DOWN"}
    assert row_outcome_for_rule("nonexistent_rule", row) == "UP"


# ---------------------------------------------------------------------------
# derive_cell uses horizon label for safe_close
# ---------------------------------------------------------------------------


def _make_row(
    fav_side: str,
    fav_price: float,
    outcome: str,
    sc_outcome: str | None = None,
    rule: str = "safe_close",
) -> dict:
    return {
        "asset": "BTC",
        "timeframe": "5m",
        "fav_side": fav_side,
        "fav_price": fav_price,
        "realized_outcome": outcome,
        "realized_outcome_safe_close": sc_outcome,
        "router_selected_rule": rule,
        "evaluated_rule": rule,
        "momentum": 0.5,
        "volatility_sigma": 0.01,
        "liquidity_usdc": 1000.0,
        "spread": 0.01,
        "orderbook_depth_usdc": 2000.0,
        "ttl_sec": 60.0,
        "oracle_edge": 0.05,
    }


def test_derive_cell_safe_close_uses_sc_label_when_diverges():
    """safe_close EV must differ from close_sweep when sc_label != open_close label."""
    rows = [
        # open→close UP but safe_close horizon DOWN (corrected label)
        _make_row("YES", 0.6, "UP", sc_outcome="DOWN", rule="safe_close"),
        _make_row("YES", 0.6, "UP", sc_outcome="DOWN", rule="safe_close"),
        _make_row("YES", 0.6, "UP", sc_outcome="DOWN", rule="safe_close"),
    ]
    model = derive_cell(rows)
    sc = model["rules"]["safe_close"]
    cs = model["rules"]["close_sweep"]
    # safe_close sees DOWN → loss (-0.6 EV); close_sweep sees UP → win (+0.4 EV)
    assert sc["base"] < 0, f"safe_close base_ev should be negative, got {sc['base']}"
    assert cs["base"] > 0, f"close_sweep base_ev should be positive, got {cs['base']}"


def test_derive_cell_safe_close_fallback_when_sc_null():
    """When sc_label is NULL, safe_close falls back to open→close (pre-migration rows)."""
    rows = [
        _make_row("YES", 0.6, "UP", sc_outcome=None, rule="safe_close"),
        _make_row("YES", 0.6, "UP", sc_outcome=None, rule="safe_close"),
    ]
    model = derive_cell(rows)
    sc = model["rules"]["safe_close"]
    # Falls back to open→close UP → win for safe_close (fav=YES, UP→YES wins) → +0.4
    assert sc["base"] > 0, f"fallback EV should be positive, got {sc['base']}"
