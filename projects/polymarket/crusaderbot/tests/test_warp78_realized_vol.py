"""WARP-78 Phase 1 — realized-volatility factor tests.

Covers the pure ``compute_realized_vol`` estimator (insufficient-history None, flat
series == 0.0, positive movement, per-sqrt-second scaling, window filtering,
non-positive dt skipped) and the ``MomentumTracker.realized_vol`` ring readout.
Hermetic — pure math, no I/O.
"""
from __future__ import annotations

from projects.polymarket.crusaderbot.domain.signal.momentum import (
    MomentumTracker,
    PriceSample,
    compute_realized_vol,
)


def _s(t: float, p: float) -> PriceSample:
    return PriceSample(ts=t, price=p)


def test_insufficient_history_is_none():
    assert compute_realized_vol([], window_sec=60, now=0) is None
    assert compute_realized_vol([_s(0, 100)], window_sec=60, now=0) is None
    # 2 samples = 1 return — still < 3-sample floor → honest None.
    assert compute_realized_vol([_s(0, 100), _s(1, 101)], window_sec=60, now=1) is None


def test_flat_series_is_zero():
    v = compute_realized_vol([_s(0, 100), _s(1, 100), _s(2, 100)], window_sec=60, now=2)
    assert v == 0.0  # the measurement IS zero, not None


def test_positive_movement_positive_vol():
    v = compute_realized_vol([_s(0, 100), _s(1, 101), _s(2, 102)], window_sec=60, now=2)
    assert v is not None and v > 0.0


def test_per_sqrt_second_scaling():
    # SAME log-returns spread over a longer interval → lower per-sqrt-second vol.
    fast = compute_realized_vol([_s(0, 100), _s(1, 101), _s(2, 102)], window_sec=60, now=2)
    slow = compute_realized_vol([_s(0, 100), _s(10, 101), _s(20, 102)], window_sec=60, now=20)
    assert fast is not None and slow is not None
    assert slow < fast


def test_window_filters_old_samples():
    # window [5, 10] keeps ts 6/8/10 (3 samples); ts 0 is excluded.
    v = compute_realized_vol(
        [_s(0, 100), _s(6, 101), _s(8, 102), _s(10, 103)], window_sec=5, now=10
    )
    assert v is not None and v > 0.0
    # Drop one in-window sample → only 2 remain → None.
    v2 = compute_realized_vol([_s(0, 100), _s(8, 102), _s(10, 103)], window_sec=5, now=10)
    assert v2 is None


def test_non_positive_dt_skipped():
    # Duplicate timestamp (dt=0) is skipped, not a divide-by-zero.
    v = compute_realized_vol(
        [_s(0, 100), _s(0, 100), _s(1, 101), _s(2, 102)], window_sec=60, now=2
    )
    assert v is not None and v > 0.0


def test_tracker_reads_same_ring():
    t = MomentumTracker(min_gap_sec=0.0)
    t.record("k", 100.0, now=0.0)
    t.record("k", 101.0, now=1.0)
    t.record("k", 102.0, now=2.0)
    v = t.realized_vol("k", now=2.0)
    assert v is not None and v > 0.0
    assert t.realized_vol("missing", now=2.0) is None
