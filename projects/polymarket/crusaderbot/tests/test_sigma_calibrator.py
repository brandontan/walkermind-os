"""WARP-70 — adaptive online sigma calibrator tests. Hermetic: no DB, no network.

Covers the calibrator's safety invariants (bounded / smoothed / cold-start /
observable) and the shadow evaluation core (adaptive beats static when the true
realized vol diverges from the static prior).
"""
from __future__ import annotations

import math

import pytest

from projects.polymarket.crusaderbot.domain.research.sigma_calibrator import (
    SigmaCalibrator,
    gaussian_nll,
    prior_sigma_for_asset,
    variance_per_second,
)
from projects.polymarket.crusaderbot.scripts.sigma_calibration_shadow import (
    evaluate_adaptive_vs_static,
)


def test_variance_per_second_basic_and_degenerate():
    assert variance_per_second(0.02, 200.0) == pytest.approx((0.02 ** 2) / 200.0)
    assert variance_per_second(0.02, 0.0) is None       # non-positive duration
    assert variance_per_second(float("nan"), 200.0) is None
    assert variance_per_second(0.02, float("inf")) is None


def test_gaussian_nll_lower_when_sigma_matches_spread():
    # A return generated at sigma_true should be best explained by sigma_true.
    t, sigma_true = 300.0, 0.0002
    r = sigma_true * math.sqrt(t)  # a ~1-stdev candle
    nll_match = gaussian_nll(r, t, sigma_true)
    nll_too_small = gaussian_nll(r, t, sigma_true * 0.2)
    nll_too_big = gaussian_nll(r, t, sigma_true * 5.0)
    assert nll_match is not None
    assert nll_match < nll_too_small
    assert nll_match < nll_too_big


def test_gaussian_nll_degenerate_returns_none():
    assert gaussian_nll(0.01, 100.0, 0.0) is None
    assert gaussian_nll(0.01, 0.0, 0.001) is None
    assert gaussian_nll(float("inf"), 100.0, 0.001) is None


def test_cold_start_returns_prior_until_converged():
    cal = SigmaCalibrator(alpha=0.2, min_samples=5)
    prior = prior_sigma_for_asset("btc")
    # Below min_samples the static prior is authoritative regardless of samples.
    for _ in range(4):
        cal.observe("btc", "5m", 0.05, 300.0)  # large returns → high variance
        assert cal.sigma("btc", "5m") == prior
    # The 5th observation crosses the threshold → adaptive value takes over.
    cal.observe("btc", "5m", 0.05, 300.0)
    assert cal.sigma("btc", "5m") != prior


def test_adaptive_sigma_is_bounded_by_band():
    cal = SigmaCalibrator(alpha=1.0, min_samples=1, band_low=0.33, band_high=3.0)
    prior = prior_sigma_for_asset("btc")
    # A monstrous single candle would imply a huge sigma; the band clamps it.
    cal.observe("btc", "5m", 0.9, 1.0)
    assert cal.sigma("btc", "5m") == pytest.approx(prior * 3.0)
    # A near-zero-vol regime is clamped up to the lower band.
    cal2 = SigmaCalibrator(alpha=1.0, min_samples=1)
    cal2.observe("eth", "5m", 1e-9, 300.0)
    assert cal2.sigma("eth", "5m") == pytest.approx(prior_sigma_for_asset("eth") * 0.33)


def test_ewma_smoothing_one_outlier_does_not_swing_far():
    cal = SigmaCalibrator(alpha=0.05, min_samples=1)
    prior = prior_sigma_for_asset("btc")
    # Converge to a steady regime whose sigma ≈ prior (mid-band, not clamped) so
    # the smoothing — not the hard band — is what's under test.
    t = 300.0
    steady_r = prior * math.sqrt(t)            # realized_delta with variance = prior²/sec
    for _ in range(300):
        cal.observe("btc", "5m", steady_r, t)
    steady = cal.sigma("btc", "5m")
    assert steady == pytest.approx(prior, rel=0.05)
    # A moderate ~3x-vol outlier (still inside the band) moves the EWMA by only
    # ~alpha of the gap — one candle cannot swing the estimate far.
    cal.observe("btc", "5m", prior * 3.0 * math.sqrt(t), t)
    after = cal.sigma("btc", "5m")
    assert after > steady                       # it moved up
    assert after < steady * 1.5                 # but a single candle didn't blow it out
    assert after <= prior * 3.0                 # and the hard band still holds


def test_observe_audit_record_and_using_prior_flag():
    cal = SigmaCalibrator(alpha=0.3, min_samples=3)
    u1 = cal.observe("sol", "15m", 0.03, 900.0)
    assert u1 is not None
    assert u1.asset == "sol" and u1.timeframe == "15m"
    assert u1.n_samples == 1 and u1.using_prior is True
    assert cal.observe("sol", "15m", 0.03, 900.0).using_prior is True
    assert cal.observe("sol", "15m", 0.03, 900.0).using_prior is False  # n==3


def test_observe_skips_degenerate_candle():
    cal = SigmaCalibrator()
    assert cal.observe("btc", "5m", 0.01, 0.0) is None
    assert cal.observe("btc", "5m", float("nan"), 300.0) is None


def test_constructor_rejects_bad_params():
    with pytest.raises(ValueError):
        SigmaCalibrator(alpha=0.0)
    with pytest.raises(ValueError):
        SigmaCalibrator(min_samples=0)
    with pytest.raises(ValueError):
        SigmaCalibrator(band_low=1.2, band_high=3.0)


def _stream(asset, tf, sigma_true, n, t=300.0):
    # Deterministic alternating ±1-stdev candles at sigma_true (mean return ~0,
    # realized per-second variance ≈ sigma_true²) — a clean regime to track.
    r = sigma_true * math.sqrt(t)
    out = []
    for i in range(n):
        out.append({
            "asset": asset, "timeframe": tf,
            "realized_delta": r if i % 2 == 0 else -r,
            "candle_open_epoch": float(i * 1000),
            "candle_close_epoch": float(i * 1000) + t,
        })
    return out


def test_evaluate_adaptive_beats_static_when_vol_diverges():
    # True vol is ~3x the BTC static prior → the static sigma mis-prices the
    # spread; the adaptive estimate should converge and score a lower avg NLL.
    sigma_true = prior_sigma_for_asset("btc") * 3.0
    rows = _stream("btc", "5m", sigma_true, n=200)
    rep = evaluate_adaptive_vs_static(rows, alpha=0.1, min_samples=20)
    assert rep["overall"]["n"] > 0
    assert rep["overall"]["nll_improvement"] > 0.0   # adaptive better overall
    cell = rep["per_cell"][0]
    assert cell["converged"] is True
    assert cell["adaptive_sigma"] > cell["prior_sigma"]


def test_evaluate_skips_degenerate_rows_without_crashing():
    rows = [
        {"asset": "", "timeframe": "5m", "realized_delta": 0.01,
         "candle_open_epoch": 0.0, "candle_close_epoch": 300.0},       # no asset
        {"asset": "btc", "timeframe": "5m", "realized_delta": None,
         "candle_open_epoch": 0.0, "candle_close_epoch": 300.0},       # no return
        {"asset": "btc", "timeframe": "5m", "realized_delta": 0.01,
         "candle_open_epoch": 300.0, "candle_close_epoch": 300.0},     # zero dur
    ]
    rep = evaluate_adaptive_vs_static(rows)
    assert rep["overall"]["n"] == 0
    assert rep["per_cell"] == []
