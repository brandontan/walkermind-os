"""Synthetic tests for the pre-trade slippage estimator (WARP-83 Sub-Lane A).

Covers: thin book, tight spread, large-stake-vs-depth, zero/near-zero depth
(div-by-zero guard), and monotonicity sanity (stake/depth up -> slippage up;
wider spread -> slippage up). Pure / deterministic — no network, no DB.
"""
from __future__ import annotations

import math

import pytest

from projects.polymarket.crusaderbot.domain.research.slippage_estimator import (
    ILLIQUID_PARTICIPATION_CEILING,
    MIN_USABLE_DEPTH_USDC,
    SlippageEstimate,
    estimate_slippage_bps,
)


# --- baseline / shape --------------------------------------------------------


def test_returns_estimate_with_decomposed_components() -> None:
    est = estimate_slippage_bps(
        stake_usdc=100.0,
        orderbook_depth_usdc=10_000.0,
        spread=1.02,
        entry_price=0.50,
        current_price=0.50,
    )
    assert isinstance(est, SlippageEstimate)
    # total is the sum of the three components.
    assert est.total_bps == pytest.approx(
        est.spread_cost_bps + est.impact_bps + est.adverse_move_bps
    )
    assert math.isfinite(est.total_bps)
    assert est.total_bps > 0.0
    assert not est.illiquid_book


def test_tight_spread_at_fair_value_has_zero_spread_cost() -> None:
    # spread == 1.0 fair complete-set value -> no excess -> zero spread cost.
    est = estimate_slippage_bps(
        stake_usdc=100.0,
        orderbook_depth_usdc=50_000.0,
        spread=1.0,
        entry_price=0.40,
        current_price=0.40,
    )
    assert est.spread_cost_bps == 0.0
    # tight spread + deep book + no move -> only the small impact term remains.
    assert est.total_bps == pytest.approx(est.impact_bps)
    assert est.total_bps >= 0.0


def test_sub_fair_spread_floored_at_zero() -> None:
    est = estimate_slippage_bps(
        stake_usdc=100.0,
        orderbook_depth_usdc=50_000.0,
        spread=0.95,
        entry_price=0.40,
        current_price=0.40,
    )
    assert est.spread_cost_bps == 0.0


# --- thin book / large stake vs depth ----------------------------------------


def test_thin_book_large_stake_high_impact() -> None:
    thin = estimate_slippage_bps(
        stake_usdc=5_000.0,
        orderbook_depth_usdc=510.0,  # observed min depth ~510 USDC
        spread=1.0,
        entry_price=0.50,
        current_price=0.50,
    )
    deep = estimate_slippage_bps(
        stake_usdc=5_000.0,
        orderbook_depth_usdc=107_000.0,  # observed max depth ~107k USDC
        spread=1.0,
        entry_price=0.50,
        current_price=0.50,
    )
    assert thin.impact_bps > deep.impact_bps
    assert thin.total_bps > deep.total_bps


def test_participation_clamped_to_ceiling_for_extreme_stake() -> None:
    est = estimate_slippage_bps(
        stake_usdc=1_000_000.0,
        orderbook_depth_usdc=100.0,
        spread=1.0,
        entry_price=0.50,
        current_price=0.50,
    )
    # ratio = 10_000 but clamped to the ceiling.
    assert est.participation_ratio == pytest.approx(ILLIQUID_PARTICIPATION_CEILING)


# --- zero / near-zero depth guard (div-by-zero, no silent failure) -----------


def test_zero_depth_flagged_illiquid_and_finite() -> None:
    est = estimate_slippage_bps(
        stake_usdc=100.0,
        orderbook_depth_usdc=0.0,
        spread=1.0,
        entry_price=0.50,
        current_price=0.50,
    )
    assert est.illiquid_book is True
    assert est.participation_ratio == pytest.approx(ILLIQUID_PARTICIPATION_CEILING)
    assert math.isfinite(est.total_bps)
    assert est.impact_bps > 0.0  # maximally penalized, not NaN/inf


def test_near_zero_depth_below_min_usable_flagged() -> None:
    est = estimate_slippage_bps(
        stake_usdc=100.0,
        orderbook_depth_usdc=MIN_USABLE_DEPTH_USDC,
        spread=1.0,
        entry_price=0.50,
        current_price=0.50,
    )
    assert est.illiquid_book is True


def test_negative_depth_treated_as_illiquid() -> None:
    est = estimate_slippage_bps(
        stake_usdc=100.0,
        orderbook_depth_usdc=-5.0,
        spread=1.0,
        entry_price=0.50,
        current_price=0.50,
    )
    assert est.illiquid_book is True
    assert math.isfinite(est.total_bps)


def test_non_finite_inputs_do_not_propagate_nan() -> None:
    est = estimate_slippage_bps(
        stake_usdc=float("nan"),
        orderbook_depth_usdc=10_000.0,
        spread=float("inf"),
        entry_price=0.50,
        current_price=float("nan"),
    )
    assert math.isfinite(est.total_bps)
    assert est.spread_cost_bps == 0.0  # inf spread coerced safe
    assert est.adverse_move_bps == 0.0  # nan current_price -> no move term


# --- adverse price move ------------------------------------------------------


def test_adverse_move_adds_cost() -> None:
    no_move = estimate_slippage_bps(
        stake_usdc=100.0,
        orderbook_depth_usdc=10_000.0,
        spread=1.0,
        entry_price=0.50,
        current_price=0.50,
    )
    moved = estimate_slippage_bps(
        stake_usdc=100.0,
        orderbook_depth_usdc=10_000.0,
        spread=1.0,
        entry_price=0.50,
        current_price=0.55,
    )
    assert no_move.adverse_move_bps == 0.0
    # 0.05/0.50 = 10% move = 1000 bps with move_coeff=1.0
    assert moved.adverse_move_bps == pytest.approx(1000.0)
    assert moved.total_bps > no_move.total_bps


def test_current_price_none_skips_move_term() -> None:
    est = estimate_slippage_bps(
        stake_usdc=100.0,
        orderbook_depth_usdc=10_000.0,
        spread=1.0,
        entry_price=0.50,
        current_price=None,
    )
    assert est.adverse_move_bps == 0.0


def test_zero_entry_price_skips_move_term() -> None:
    est = estimate_slippage_bps(
        stake_usdc=100.0,
        orderbook_depth_usdc=10_000.0,
        spread=1.0,
        entry_price=0.0,
        current_price=0.50,
    )
    assert est.adverse_move_bps == 0.0


# --- monotonicity sanity -----------------------------------------------------


def test_monotonic_in_stake_over_depth() -> None:
    prev = -1.0
    for stake in (100.0, 1_000.0, 5_000.0, 20_000.0):
        est = estimate_slippage_bps(
            stake_usdc=stake,
            orderbook_depth_usdc=10_000.0,
            spread=1.0,
            entry_price=0.50,
            current_price=0.50,
        )
        assert est.impact_bps >= prev
        prev = est.impact_bps


def test_monotonic_in_spread() -> None:
    prev = -1.0
    for spread in (1.0, 1.02, 1.05, 1.20):
        est = estimate_slippage_bps(
            stake_usdc=100.0,
            orderbook_depth_usdc=10_000.0,
            spread=spread,
            entry_price=0.50,
            current_price=0.50,
        )
        assert est.spread_cost_bps >= prev
        prev = est.spread_cost_bps


def test_deeper_book_lower_or_equal_impact() -> None:
    prev = math.inf
    for depth in (1_000.0, 10_000.0, 50_000.0, 107_000.0):
        est = estimate_slippage_bps(
            stake_usdc=5_000.0,
            orderbook_depth_usdc=depth,
            spread=1.0,
            entry_price=0.50,
            current_price=0.50,
        )
        assert est.impact_bps <= prev
        prev = est.impact_bps
