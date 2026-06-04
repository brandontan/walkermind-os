"""Unit tests for the pure BTC fair-value / edge calculator (WARP-63, Chunk 2).

Pure logic only -- no network, no DB, no strategy import. Covers the done-criteria
edge cases: time_left -> 0 (fair_up -> 0/1), delta = 0 (fair_up = 0.5), negative
delta, and a missing best-ask falling back safely on the 0.01 CLOB tick.
"""
from __future__ import annotations

import math

import pytest

from projects.polymarket.crusaderbot.domain.strategy.oracle.fair_value import (
    CLOB_MIN_TICK,
    EdgeResult,
    annual_vol_to_sigma,
    compute_delta,
    compute_edge,
    compute_fair_value,
    normal_cdf,
)

SIGMA = 1e-4  # ~56% annualized, the configured default


# --- normal_cdf ------------------------------------------------------------

def test_normal_cdf_zero_is_half() -> None:
    assert normal_cdf(0.0) == pytest.approx(0.5)


def test_normal_cdf_saturates() -> None:
    assert normal_cdf(40.0) == pytest.approx(1.0)
    assert normal_cdf(-40.0) == pytest.approx(0.0)


def test_normal_cdf_symmetry() -> None:
    assert normal_cdf(1.3) + normal_cdf(-1.3) == pytest.approx(1.0)


def test_normal_cdf_rejects_nan() -> None:
    with pytest.raises(ValueError):
        normal_cdf(float("nan"))


# --- compute_delta ---------------------------------------------------------

def test_compute_delta_signed_return() -> None:
    assert compute_delta(101.0, 100.0) == pytest.approx(0.01)
    assert compute_delta(99.0, 100.0) == pytest.approx(-0.01)
    assert compute_delta(100.0, 100.0) == 0.0


def test_compute_delta_rejects_nonpositive_reference() -> None:
    with pytest.raises(ValueError):
        compute_delta(100.0, 0.0)
    with pytest.raises(ValueError):
        compute_delta(100.0, -5.0)


# --- compute_fair_value: core edge cases -----------------------------------

def test_fair_value_zero_delta_is_half() -> None:
    # delta = 0 -> no information -> exactly 0.5, independent of time / vol.
    assert compute_fair_value(0.0, 120.0, SIGMA) == 0.5
    assert compute_fair_value(0.0, 0.0, SIGMA) == 0.5
    assert compute_fair_value(0.0, 120.0, 0.0) == 0.5


def test_fair_value_time_left_to_zero_converges_to_bound() -> None:
    # As time_left -> 0 the deviation is decided: Up -> 1, Down -> 0.
    assert compute_fair_value(0.01, 0.0, SIGMA) == 1.0
    assert compute_fair_value(-0.01, 0.0, SIGMA) == 0.0
    assert compute_fair_value(0.01, -3.0, SIGMA) == 1.0  # negative time = past


def test_fair_value_small_positive_time_left_approaches_bound() -> None:
    # A real (non-zero) short window with a modest deviation -> near-certain but
    # still strictly interior (a larger deviation saturates erf to exactly 1.0,
    # which the time_left -> 0 / zero-variance limit tests already cover).
    fair = compute_fair_value(0.0003, 0.5, SIGMA)
    assert fair > 0.99
    assert fair < 1.0


def test_fair_value_negative_delta_below_half() -> None:
    assert compute_fair_value(-0.002, 120.0, SIGMA) < 0.5


def test_fair_value_positive_delta_above_half() -> None:
    assert compute_fair_value(0.002, 120.0, SIGMA) > 0.5


def test_fair_value_monotonic_in_delta() -> None:
    f_low = compute_fair_value(0.0005, 120.0, SIGMA)
    f_mid = compute_fair_value(0.0015, 120.0, SIGMA)
    f_high = compute_fair_value(0.0030, 120.0, SIGMA)
    assert 0.5 < f_low < f_mid < f_high


def test_fair_value_larger_sigma_pulls_toward_half() -> None:
    # More vol -> less confident -> fair_up closer to 0.5 for the same deviation.
    sharp = compute_fair_value(0.002, 120.0, SIGMA)
    blurry = compute_fair_value(0.002, 120.0, SIGMA * 4.0)
    assert 0.5 < blurry < sharp


def test_fair_value_zero_sigma_degenerate_bound() -> None:
    assert compute_fair_value(0.01, 120.0, 0.0) == 1.0
    assert compute_fair_value(-0.01, 120.0, 0.0) == 0.0


def test_fair_value_always_in_unit_interval() -> None:
    for delta in (-0.05, -0.001, 0.0, 0.001, 0.05):
        for tl in (0.0, 1.0, 300.0):
            val = compute_fair_value(delta, tl, SIGMA)
            assert 0.0 <= val <= 1.0


def test_fair_value_rejects_nan() -> None:
    with pytest.raises(ValueError):
        compute_fair_value(float("nan"), 120.0, SIGMA)
    with pytest.raises(ValueError):
        compute_fair_value(0.01, float("inf"), SIGMA)


# --- compute_edge ----------------------------------------------------------

def test_compute_edge_basic_math() -> None:
    res = compute_edge(0.62, ask_up=0.55, ask_down=0.45)
    assert isinstance(res, EdgeResult)
    assert res.edge_up == pytest.approx(0.62 - 0.55)
    assert res.edge_down == pytest.approx((1.0 - 0.62) - 0.45)
    assert res.ask_up == pytest.approx(0.55)
    assert res.ask_down == pytest.approx(0.45)


def test_compute_edge_missing_ask_falls_back_to_clob_tick() -> None:
    # Done-criterion: missing price falls back safely on the 0.01 CLOB tick.
    res = compute_edge(0.70, ask_up=None, ask_down=None)
    assert res.ask_up == CLOB_MIN_TICK == 0.01
    assert res.ask_down == CLOB_MIN_TICK
    assert res.edge_up == pytest.approx(0.70 - 0.01)
    assert res.edge_down == pytest.approx((1.0 - 0.70) - 0.01)


def test_compute_edge_nonpositive_and_nonfinite_ask_floored() -> None:
    res = compute_edge(0.50, ask_up=0.0, ask_down=float("nan"))
    assert res.ask_up == CLOB_MIN_TICK
    assert res.ask_down == CLOB_MIN_TICK


def test_compute_edge_clamps_below_tick_and_above_one() -> None:
    res = compute_edge(0.50, ask_up=0.004, ask_down=1.4)
    assert res.ask_up == CLOB_MIN_TICK   # below tick -> floored
    assert res.ask_down == 1.0           # above 1.0 -> clamped


def test_compute_edge_can_be_negative() -> None:
    # Overpriced side -> negative edge (no buy signal).
    res = compute_edge(0.40, ask_up=0.55, ask_down=0.50)
    assert res.edge_up < 0.0
    assert res.edge_down == pytest.approx((1.0 - 0.40) - 0.50)


def test_compute_edge_rejects_out_of_range_fair() -> None:
    with pytest.raises(ValueError):
        compute_edge(1.2, 0.5, 0.5)
    with pytest.raises(ValueError):
        compute_edge(-0.1, 0.5, 0.5)


# --- annual_vol_to_sigma (sigma calibration basis) -------------------------

def test_annual_vol_to_sigma_matches_default_basis() -> None:
    # The configured 0.00010 default corresponds to ~56% annualized vol.
    sigma = annual_vol_to_sigma(0.562)
    assert sigma == pytest.approx(1e-4, rel=1e-2)


def test_annual_vol_to_sigma_round_trip() -> None:
    seconds_per_year = 365.25 * 24.0 * 60.0 * 60.0
    sigma = annual_vol_to_sigma(0.55)
    assert sigma * math.sqrt(seconds_per_year) == pytest.approx(0.55)


def test_annual_vol_to_sigma_rejects_negative() -> None:
    with pytest.raises(ValueError):
        annual_vol_to_sigma(-0.1)
