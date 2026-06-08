"""WARP — adaptive complete-set margin (heuristic, pure). Hermetic, no IO."""
from __future__ import annotations

import math

from projects.polymarket.crusaderbot.domain.strategy.complete_set_margin import (
    ADAPTIVE_PREMIUM_CAP_USDC,
    adaptive_required_margin,
)

HARD_FLOOR = 0.02


def _book(levels):
    """levels = [(price, size), ...] -> CLOB /book shape (asks)."""
    return {"asks": [{"price": p, "size": s} for p, s in levels]}


# ── invariant: never below the base floor ───────────────────────────────────

def test_premium_never_lowers_below_base_floor():
    # Deep, tight books (one fat level each at top) -> zero slippage -> premium 0.
    yes = _book([(0.40, 10_000)])
    no = _book([(0.55, 10_000)])
    d = adaptive_required_margin(
        base_floor=HARD_FLOOR, yes_book=yes, no_book=no, intended_shares=50,
    )
    assert d.premium == 0.0
    assert d.required_margin == HARD_FLOOR
    assert d.required_margin >= HARD_FLOOR  # invariant


def test_deep_tight_book_behaves_like_static():
    yes = _book([(0.40, 1_000)])
    no = _book([(0.55, 1_000)])
    d = adaptive_required_margin(
        base_floor=0.03, yes_book=yes, no_book=no, intended_shares=100,
    )
    assert d.premium == 0.0
    assert d.required_margin == 0.03


# ── adaptive: thin/steep book raises the required margin ────────────────────

def test_steep_book_adds_premium():
    # Intended 100 shares but top level only has 10 @ 0.40, rest deeper/worse.
    yes = _book([(0.40, 10), (0.45, 90)])   # avg for 100 = (10*0.40+90*0.45)/100=0.445; slip 0.045
    no = _book([(0.55, 100)])               # deep at top: slip 0
    d = adaptive_required_margin(
        base_floor=HARD_FLOOR, yes_book=yes, no_book=no, intended_shares=100,
    )
    assert d.premium > 0.0
    assert math.isclose(d.features["yes_impact_usdc"], 0.045, abs_tol=1e-6)
    assert d.features["no_impact_usdc"] == 0.0
    assert math.isclose(d.required_margin, HARD_FLOOR + d.premium, abs_tol=1e-9)


def test_both_legs_steep_sum_impact():
    yes = _book([(0.40, 10), (0.50, 90)])   # avg100 = 0.49; slip 0.09
    no = _book([(0.30, 10), (0.40, 90)])    # avg100 = 0.39; slip 0.09
    d = adaptive_required_margin(
        base_floor=HARD_FLOOR, yes_book=yes, no_book=no, intended_shares=100,
    )
    # raw impact 0.18 but capped
    assert d.premium == ADAPTIVE_PREMIUM_CAP_USDC
    assert d.required_margin == HARD_FLOOR + ADAPTIVE_PREMIUM_CAP_USDC


def test_premium_capped():
    yes = _book([(0.10, 1), (0.90, 1_000)])
    no = _book([(0.05, 1), (0.90, 1_000)])
    d = adaptive_required_margin(
        base_floor=HARD_FLOOR, yes_book=yes, no_book=no, intended_shares=100,
    )
    assert d.premium <= ADAPTIVE_PREMIUM_CAP_USDC
    assert d.required_margin <= HARD_FLOOR + ADAPTIVE_PREMIUM_CAP_USDC


# ── intended-size sensitivity: bigger size walks deeper -> more premium ─────

def test_larger_intended_size_walks_deeper():
    yes = _book([(0.40, 20), (0.50, 1_000)])
    no = _book([(0.55, 1_000)])
    small = adaptive_required_margin(
        base_floor=HARD_FLOOR, yes_book=yes, no_book=no, intended_shares=20,
    )
    big = adaptive_required_margin(
        base_floor=HARD_FLOOR, yes_book=yes, no_book=no, intended_shares=200,
    )
    assert small.premium == 0.0          # fits in the top level
    assert big.premium > small.premium   # walks into 0.50 level


# ── robustness: malformed / empty books never lower the bar or raise ────────

def test_empty_books_fall_back_to_base():
    d = adaptive_required_margin(
        base_floor=0.025, yes_book=None, no_book={"asks": []}, intended_shares=100,
    )
    assert d.premium == 0.0
    assert d.required_margin == 0.025


def test_malformed_levels_skipped():
    yes = {"asks": [{"price": "x", "size": "y"}, {"price": 0.40, "size": 100}]}
    no = _book([(0.55, 100)])
    d = adaptive_required_margin(
        base_floor=HARD_FLOOR, yes_book=yes, no_book=no, intended_shares=50,
    )
    assert d.premium == 0.0  # only the valid 0.40 level remains; fills at top


def test_non_positive_intended_uses_min_ref():
    yes = _book([(0.40, 100)])
    no = _book([(0.55, 100)])
    d = adaptive_required_margin(
        base_floor=HARD_FLOOR, yes_book=yes, no_book=no, intended_shares=0,
    )
    assert d.features["intended_shares"] == 1.0
    assert d.required_margin >= HARD_FLOOR


# ── feature vector present for shadow logging ───────────────────────────────

def test_feature_vector_shape():
    yes = _book([(0.40, 100)])
    no = _book([(0.55, 100)])
    d = adaptive_required_margin(
        base_floor=HARD_FLOOR, yes_book=yes, no_book=no, intended_shares=50,
        seconds_to_resolution=42.0,
    )
    for k in (
        "intended_shares", "yes_impact_usdc", "no_impact_usdc", "impact_usdc_per_pair",
        "premium_usdc", "base_floor", "required_margin", "seconds_to_resolution",
    ):
        assert k in d.features
    assert d.features["seconds_to_resolution"] == 42.0
