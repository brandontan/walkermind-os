"""Phase 11 — Strategy Implementations & Intelligence Layer Test Suite.

Validates the three concrete strategy implementations and the intelligence modules
introduced in the Phase 11 structure refactor.

  ── EV Momentum Strategy ──
  SI-01  ev_momentum — name returns "ev_momentum"
  SI-02  ev_momentum — is_ready returns False before window is full
  SI-03  ev_momentum — is_ready returns True once window is full
  SI-04  ev_momentum — returns None when liquidity below threshold
  SI-05  ev_momentum — returns None when not yet ready (window not full)
  SI-06  ev_momentum — returns YES signal when upward momentum exceeds min_edge
  SI-07  ev_momentum — returns NO signal when downward momentum exceeds min_edge
  SI-08  ev_momentum — returns None when momentum below min_edge
  SI-09  ev_momentum — size_usdc never exceeds max_position_usd
  SI-10  ev_momentum — size_usdc is at least 1.0

  ── Mean Reversion Strategy ──
  SI-11  mean_reversion — name returns "mean_reversion"
  SI-12  mean_reversion — is_ready returns False before warmup ticks
  SI-13  mean_reversion — returns None when liquidity below threshold
  SI-14  mean_reversion — returns YES signal when price below EWMA by threshold
  SI-15  mean_reversion — returns NO signal when price above EWMA by threshold
  SI-16  mean_reversion — returns None when deviation below threshold
  SI-17  mean_reversion — reset() clears EWMA and tick count
  SI-18  mean_reversion — size_usdc bounded by max_position_usd

  ── Liquidity Edge Strategy ──
  SI-19  liquidity_edge — name returns "liquidity_edge"
  SI-20  liquidity_edge — returns None when spread below min_spread
  SI-21  liquidity_edge — returns None when liquidity below threshold
  SI-22  liquidity_edge — returns None before warmup ticks
  SI-23  liquidity_edge — returns YES when YES depth dominant and spread wide
  SI-24  liquidity_edge — returns NO when NO depth dominant and spread wide
  SI-25  liquidity_edge — returns None when depth imbalance insufficient
  SI-26  liquidity_edge — size_usdc bounded by max_position_usd
  SI-27  liquidity_edge — reset() clears spread EWMA and tick count

  ── Strategy Registry ──
  SI-28  STRATEGY_REGISTRY contains all three strategy keys
  SI-29  STRATEGY_REGISTRY values are instantiable classes

  ── Bayesian Confidence ──
  SI-30  bayesian — raises ValueError on non-positive priors
  SI-31  bayesian — confidence returns prior mean before min_samples
  SI-32  bayesian — update(won=True) increases alpha and raises confidence
  SI-33  bayesian — update(won=False) increases beta and lowers confidence
  SI-34  bayesian — reset() restores prior state
  SI-35  bayesian — snapshot() returns correct BayesianState
  SI-36  bayesian — to_dict() contains all expected keys
  SI-37  bayesian — confidence clamps between 0 and 1

  ── Drift Detector ──
  SI-38  drift — not ready before warmup ticks
  SI-39  drift — no drift detected during warmup
  SI-40  drift — upward drift detected after cumulative positive deviation
  SI-41  drift — downward drift detected after cumulative negative deviation
  SI-42  drift — confidence_multiplier is 1.0 when no drift
  SI-43  drift — confidence_multiplier < 1.0 on drift detection
  SI-44  drift — CUSUM resets after detection (reset_on_detect=True)
  SI-45  drift — reset() clears cusum accumulators
  SI-46  drift — to_dict() contains expected keys
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import pytest

from projects.polymarket.polyquantbot.strategy.base.base_strategy import SignalResult
from projects.polymarket.polyquantbot.strategy.implementations import (
    STRATEGY_REGISTRY,
    EVMomentumStrategy,
    LiquidityEdgeStrategy,
    MeanReversionStrategy,
)
from projects.polymarket.polyquantbot.intelligence.bayesian import (
    BayesianConfidence,
    BayesianState,
)
from projects.polymarket.polyquantbot.intelligence.drift import (
    DriftDetector,
    DriftResult,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

_DEEP_MARKET: Dict[str, Any] = {
    "bid": 0.48,
    "ask": 0.52,
    "mid": 0.50,
    "depth_yes": 50_000.0,
    "depth_no": 50_000.0,
    "volume": 10_000.0,
}

_SHALLOW_MARKET: Dict[str, Any] = {
    **_DEEP_MARKET,
    "depth_yes": 1_000.0,
    "depth_no": 1_000.0,
}


def _market_with_mid(mid: float, depth: float = 50_000.0) -> Dict[str, Any]:
    spread = 0.02
    return {
        "bid": round(mid - spread / 2, 4),
        "ask": round(mid + spread / 2, 4),
        "mid": mid,
        "depth_yes": depth,
        "depth_no": depth,
        "volume": 5_000.0,
    }


# ─────────────────────────────────────────────────────────────────────────────
# SI-01–SI-10: EVMomentumStrategy
# ─────────────────────────────────────────────────────────────────────────────


class TestEVMomentumStrategy:
    """EVMomentumStrategy unit tests."""

    def test_si01_name(self):
        """SI-01 ev_momentum — name returns 'ev_momentum'."""
        s = EVMomentumStrategy()
        assert s.name == "ev_momentum"

    async def test_si02_not_ready_before_window(self):
        """SI-02 ev_momentum — is_ready returns False before window is full."""
        s = EVMomentumStrategy(window=5)
        assert await s.is_ready() is False

    async def test_si03_ready_after_window(self):
        """SI-03 ev_momentum — is_ready returns True once window is full."""
        s = EVMomentumStrategy(window=3)
        for i in range(3):
            await s.evaluate("m1", _market_with_mid(0.50 + i * 0.01))
        assert await s.is_ready() is True

    async def test_si04_liquidity_filter(self):
        """SI-04 ev_momentum — returns None when liquidity below threshold."""
        s = EVMomentumStrategy(min_depth_usd=20_000.0)
        result = await s.evaluate("m1", _SHALLOW_MARKET)
        assert result is None

    async def test_si05_none_before_ready(self):
        """SI-05 ev_momentum — returns None before window is full."""
        s = EVMomentumStrategy(window=20, min_depth_usd=1.0)
        result = await s.evaluate("m1", _DEEP_MARKET)
        assert result is None

    async def test_si06_yes_signal_on_upward_momentum(self):
        """SI-06 ev_momentum — returns YES signal when upward momentum >= min_edge."""
        s = EVMomentumStrategy(
            window=5, min_edge=0.01, momentum_scale=5.0, min_depth_usd=1.0
        )
        sig = None
        for i in range(5):
            sig = await s.evaluate("m1", _market_with_mid(0.50 + i * 0.02))
        assert sig is not None
        assert sig.side == "YES"
        assert sig.edge > 0

    async def test_si07_no_signal_on_downward_momentum(self):
        """SI-07 ev_momentum — returns NO signal when downward momentum >= min_edge."""
        s = EVMomentumStrategy(
            window=5, min_edge=0.01, momentum_scale=5.0, min_depth_usd=1.0
        )
        sig = None
        for i in range(5):
            sig = await s.evaluate("m1", _market_with_mid(0.50 - i * 0.02))
        assert sig is not None
        assert sig.side == "NO"

    async def test_si08_none_when_momentum_below_edge(self):
        """SI-08 ev_momentum — returns None when momentum below min_edge."""
        s = EVMomentumStrategy(
            window=5, min_edge=0.50, momentum_scale=1.0, min_depth_usd=1.0
        )
        sig = None
        for i in range(5):
            sig = await s.evaluate("m1", _market_with_mid(0.50 + i * 0.0001))
        assert sig is None

    async def test_si09_size_capped_at_max(self):
        """SI-09 ev_momentum — size_usdc never exceeds max_position_usd."""
        s = EVMomentumStrategy(
            window=5, min_edge=0.01, momentum_scale=50.0,
            max_position_usd=50.0, min_depth_usd=1.0
        )
        sig = None
        for i in range(5):
            sig = await s.evaluate("m1", _market_with_mid(0.50 + i * 0.02))
        if sig:
            assert sig.size_usdc <= 50.0

    async def test_si10_size_at_least_one(self):
        """SI-10 ev_momentum — size_usdc is at least 1.0."""
        s = EVMomentumStrategy(
            window=5, min_edge=0.01, momentum_scale=5.0,
            max_position_usd=100.0, min_depth_usd=1.0
        )
        sig = None
        for i in range(5):
            sig = await s.evaluate("m1", _market_with_mid(0.50 + i * 0.02))
        if sig:
            assert sig.size_usdc >= 1.0


# ─────────────────────────────────────────────────────────────────────────────
# SI-11–SI-18: MeanReversionStrategy
# ─────────────────────────────────────────────────────────────────────────────


class TestMeanReversionStrategy:
    """MeanReversionStrategy unit tests."""

    def test_si11_name(self):
        """SI-11 mean_reversion — name returns 'mean_reversion'."""
        s = MeanReversionStrategy()
        assert s.name == "mean_reversion"

    async def test_si12_not_ready_before_warmup(self):
        """SI-12 mean_reversion — is_ready returns False before warmup ticks."""
        s = MeanReversionStrategy()
        assert await s.is_ready() is False

    async def test_si13_liquidity_filter(self):
        """SI-13 mean_reversion — returns None when liquidity below threshold."""
        s = MeanReversionStrategy(min_depth_usd=100_000.0)
        result = await s.evaluate("m1", _SHALLOW_MARKET)
        assert result is None

    async def test_si14_yes_signal_price_below_ewma(self):
        """SI-14 mean_reversion — returns YES signal when price below EWMA by threshold."""
        s = MeanReversionStrategy(
            min_edge=0.01,
            ewma_alpha=0.9,
            deviation_threshold=0.02,
            min_depth_usd=1.0,
        )
        for _ in range(15):
            await s.evaluate("m1", _market_with_mid(0.60))
        result = await s.evaluate("m1", _market_with_mid(0.40))
        assert result is not None
        assert result.side == "YES"

    async def test_si15_no_signal_price_above_ewma(self):
        """SI-15 mean_reversion — returns NO signal when price above EWMA by threshold."""
        s = MeanReversionStrategy(
            min_edge=0.01,
            ewma_alpha=0.9,
            deviation_threshold=0.02,
            min_depth_usd=1.0,
        )
        for _ in range(15):
            await s.evaluate("m1", _market_with_mid(0.40))
        result = await s.evaluate("m1", _market_with_mid(0.60))
        assert result is not None
        assert result.side == "NO"

    async def test_si16_none_when_deviation_small(self):
        """SI-16 mean_reversion — returns None when deviation below threshold."""
        s = MeanReversionStrategy(
            deviation_threshold=0.20,
            min_depth_usd=1.0,
        )
        for _ in range(15):
            await s.evaluate("m1", _market_with_mid(0.50))
        result = await s.evaluate("m1", _market_with_mid(0.51))
        assert result is None

    async def test_si17_reset_clears_state(self):
        """SI-17 mean_reversion — reset() clears EWMA and tick count."""
        s = MeanReversionStrategy(min_depth_usd=1.0)
        await s.evaluate("m1", _market_with_mid(0.50))
        s.reset()
        assert s._ewma is None
        assert s._tick_count == 0

    async def test_si18_size_bounded(self):
        """SI-18 mean_reversion — size_usdc bounded by max_position_usd."""
        s = MeanReversionStrategy(
            min_edge=0.01,
            ewma_alpha=0.9,
            deviation_threshold=0.02,
            max_position_usd=25.0,
            min_depth_usd=1.0,
        )
        for _ in range(15):
            await s.evaluate("m1", _market_with_mid(0.60))
        result = await s.evaluate("m1", _market_with_mid(0.30))
        if result:
            assert result.size_usdc <= 25.0


# ─────────────────────────────────────────────────────────────────────────────
# SI-19–SI-27: LiquidityEdgeStrategy
# ─────────────────────────────────────────────────────────────────────────────


def _wide_market(
    bid: float = 0.40,
    ask: float = 0.60,
    depth_yes: float = 80_000.0,
    depth_no: float = 10_000.0,
) -> Dict[str, Any]:
    """Helper: market with wide spread and depth imbalance."""
    return {
        "bid": bid,
        "ask": ask,
        "mid": (bid + ask) / 2.0,
        "depth_yes": depth_yes,
        "depth_no": depth_no,
        "volume": 5_000.0,
    }


class TestLiquidityEdgeStrategy:
    """LiquidityEdgeStrategy unit tests."""

    def test_si19_name(self):
        """SI-19 liquidity_edge — name returns 'liquidity_edge'."""
        s = LiquidityEdgeStrategy()
        assert s.name == "liquidity_edge"

    async def test_si20_tight_spread_returns_none(self):
        """SI-20 liquidity_edge — returns None when spread below min_spread."""
        s = LiquidityEdgeStrategy(min_spread=0.10, min_depth_usd=1.0)
        result = await s.evaluate("m1", _DEEP_MARKET)  # spread = 0.04
        assert result is None

    async def test_si21_liquidity_filter(self):
        """SI-21 liquidity_edge — returns None when liquidity below threshold."""
        s = LiquidityEdgeStrategy(min_depth_usd=200_000.0)
        result = await s.evaluate("m1", _wide_market())
        assert result is None

    async def test_si22_none_before_warmup(self):
        """SI-22 liquidity_edge — returns None before warmup ticks."""
        s = LiquidityEdgeStrategy(min_spread=0.01, min_depth_usd=1.0)
        result = await s.evaluate("m1", _wide_market())
        assert result is None

    async def test_si23_yes_signal_yes_depth_dominant(self):
        """SI-23 liquidity_edge — returns YES when YES depth dominant and spread wide."""
        s = LiquidityEdgeStrategy(
            min_edge=0.01,
            min_spread=0.05,
            spread_ewma_alpha=0.01,
            spread_multiplier=1.5,
            depth_ratio_threshold=2.0,
            min_depth_usd=1.0,
        )
        for _ in range(20):
            await s.evaluate(
                "m1",
                {"bid": 0.47, "ask": 0.53, "depth_yes": 80_000.0, "depth_no": 10_000.0},
            )
        result = await s.evaluate(
            "m1",
            {"bid": 0.35, "ask": 0.65, "depth_yes": 80_000.0, "depth_no": 10_000.0},
        )
        assert result is not None
        assert result.side == "YES"

    async def test_si24_no_signal_no_depth_dominant(self):
        """SI-24 liquidity_edge — returns NO when NO depth dominant and spread wide."""
        s = LiquidityEdgeStrategy(
            min_edge=0.01,
            min_spread=0.05,
            spread_ewma_alpha=0.01,
            spread_multiplier=1.5,
            depth_ratio_threshold=2.0,
            min_depth_usd=1.0,
        )
        for _ in range(20):
            await s.evaluate(
                "m1",
                {"bid": 0.47, "ask": 0.53, "depth_yes": 10_000.0, "depth_no": 80_000.0},
            )
        result = await s.evaluate(
            "m1",
            {"bid": 0.35, "ask": 0.65, "depth_yes": 10_000.0, "depth_no": 80_000.0},
        )
        assert result is not None
        assert result.side == "NO"

    async def test_si25_none_when_depth_imbalance_insufficient(self):
        """SI-25 liquidity_edge — returns None when depth imbalance insufficient."""
        s = LiquidityEdgeStrategy(
            min_edge=0.01,
            min_spread=0.05,
            spread_ewma_alpha=0.01,
            spread_multiplier=1.5,
            depth_ratio_threshold=5.0,
            min_depth_usd=1.0,
        )
        for _ in range(20):
            await s.evaluate(
                "m1",
                {"bid": 0.47, "ask": 0.53, "depth_yes": 50_000.0, "depth_no": 50_000.0},
            )
        result = await s.evaluate(
            "m1",
            {"bid": 0.35, "ask": 0.70, "depth_yes": 60_000.0, "depth_no": 50_000.0},
        )
        assert result is None

    async def test_si26_size_bounded(self):
        """SI-26 liquidity_edge — size_usdc bounded by max_position_usd."""
        s = LiquidityEdgeStrategy(
            min_edge=0.01,
            min_spread=0.05,
            spread_ewma_alpha=0.01,
            spread_multiplier=1.5,
            depth_ratio_threshold=2.0,
            max_position_usd=30.0,
            min_depth_usd=1.0,
        )
        for _ in range(20):
            await s.evaluate(
                "m1",
                {"bid": 0.47, "ask": 0.53, "depth_yes": 80_000.0, "depth_no": 10_000.0},
            )
        result = await s.evaluate(
            "m1",
            {"bid": 0.30, "ask": 0.80, "depth_yes": 80_000.0, "depth_no": 10_000.0},
        )
        if result:
            assert result.size_usdc <= 30.0

    async def test_si27_reset_clears_state(self):
        """SI-27 liquidity_edge — reset() clears spread EWMA and tick count."""
        s = LiquidityEdgeStrategy(min_depth_usd=1.0)
        await s.evaluate("m1", _wide_market())
        s.reset()
        assert s._spread_ewma is None
        assert s._tick_count == 0


# ─────────────────────────────────────────────────────────────────────────────
# SI-28–SI-29: Strategy Registry
# ─────────────────────────────────────────────────────────────────────────────


class TestStrategyRegistry:
    """STRATEGY_REGISTRY unit tests."""

    def test_si28_registry_contains_all_keys(self):
        """SI-28 STRATEGY_REGISTRY contains all three strategy keys."""
        assert "ev_momentum" in STRATEGY_REGISTRY
        assert "mean_reversion" in STRATEGY_REGISTRY
        assert "liquidity_edge" in STRATEGY_REGISTRY

    def test_si29_registry_values_instantiable(self):
        """SI-29 STRATEGY_REGISTRY values are instantiable classes."""
        for key, cls in STRATEGY_REGISTRY.items():
            instance = cls()
            assert instance.name == key


# ─────────────────────────────────────────────────────────────────────────────
# SI-30–SI-37: BayesianConfidence
# ─────────────────────────────────────────────────────────────────────────────


class TestBayesianConfidence:
    """BayesianConfidence unit tests."""

    def test_si30_raises_on_non_positive_priors(self):
        """SI-30 bayesian — raises ValueError on non-positive priors."""
        with pytest.raises(ValueError):
            BayesianConfidence(alpha_prior=0.0, beta_prior=1.0)
        with pytest.raises(ValueError):
            BayesianConfidence(alpha_prior=1.0, beta_prior=-1.0)

    def test_si31_prior_mean_before_min_samples(self):
        """SI-31 bayesian — confidence returns prior mean before min_samples."""
        bc = BayesianConfidence(alpha_prior=3.0, beta_prior=1.0, min_samples=5)
        expected_prior_mean = 3.0 / (3.0 + 1.0)
        assert bc.confidence == pytest.approx(expected_prior_mean)

    async def test_si32_update_win_increases_confidence(self):
        """SI-32 bayesian — update(won=True) increases alpha and raises confidence."""
        bc = BayesianConfidence(alpha_prior=1.0, beta_prior=9.0, min_samples=1)
        before = bc.confidence
        new_conf = await bc.update(won=True)
        assert new_conf > before
        assert bc._alpha > 1.0

    async def test_si33_update_loss_lowers_confidence(self):
        """SI-33 bayesian — update(won=False) increases beta and lowers confidence."""
        bc = BayesianConfidence(alpha_prior=9.0, beta_prior=1.0, min_samples=1)
        before = bc.confidence
        new_conf = await bc.update(won=False)
        assert new_conf < before
        assert bc._beta > 1.0

    async def test_si34_reset_restores_prior(self):
        """SI-34 bayesian — reset() restores prior state."""
        bc = BayesianConfidence(alpha_prior=2.0, beta_prior=3.0, min_samples=1)
        await bc.update(won=True)
        await bc.update(won=True)
        bc.reset()
        assert bc._alpha == pytest.approx(2.0)
        assert bc._beta == pytest.approx(3.0)
        assert bc._sample_count == 0

    async def test_si35_snapshot_correct(self):
        """SI-35 bayesian — snapshot() returns correct BayesianState."""
        bc = BayesianConfidence(alpha_prior=2.0, beta_prior=2.0, min_samples=1)
        await bc.update(won=True)
        snap = bc.snapshot()
        assert isinstance(snap, BayesianState)
        assert snap.alpha == pytest.approx(3.0, abs=0.01)
        assert snap.sample_count == 1
        assert snap.win_count == 1

    def test_si36_to_dict_has_expected_keys(self):
        """SI-36 bayesian — to_dict() contains all expected keys."""
        bc = BayesianConfidence()
        d = bc.to_dict()
        for key in ("alpha", "beta", "confidence", "sample_count", "win_count",
                    "alpha_prior", "beta_prior"):
            assert key in d

    async def test_si37_confidence_bounded(self):
        """SI-37 bayesian — confidence is always between 0 and 1."""
        bc = BayesianConfidence(min_samples=0)
        for _ in range(100):
            await bc.update(won=True)
        for _ in range(100):
            await bc.update(won=False)
        assert 0.0 <= bc.confidence <= 1.0


# ─────────────────────────────────────────────────────────────────────────────
# SI-38–SI-46: DriftDetector
# ─────────────────────────────────────────────────────────────────────────────


class TestDriftDetector:
    """DriftDetector unit tests."""

    def test_si38_not_ready_before_warmup(self):
        """SI-38 drift — not ready before warmup ticks."""
        d = DriftDetector()
        assert d.is_ready is False

    def test_si39_no_drift_during_warmup(self):
        """SI-39 drift — no drift detected during warmup."""
        d = DriftDetector()
        for _ in range(5):
            result = d.update(0.50)
            assert result.drift_detected is False

    def test_si40_upward_drift_detected(self):
        """SI-40 drift — upward drift detected after cumulative positive deviation."""
        d = DriftDetector(threshold=0.05, ewma_alpha=0.001, reset_on_detect=False)
        results = [d.update(0.50 + 0.01 * i) for i in range(50)]
        any_drift = any(r.drift_detected and r.drift_direction == "up" for r in results)
        assert any_drift

    def test_si41_downward_drift_detected(self):
        """SI-41 drift — downward drift detected after cumulative negative deviation."""
        d = DriftDetector(threshold=0.05, ewma_alpha=0.001, reset_on_detect=False)
        results = [d.update(0.50 - 0.01 * i) for i in range(50)]
        any_drift = any(r.drift_detected and r.drift_direction == "down" for r in results)
        assert any_drift

    def test_si42_confidence_one_when_no_drift(self):
        """SI-42 drift — confidence_multiplier is 1.0 when no drift."""
        d = DriftDetector(threshold=100.0)
        result = d.update(0.50)
        assert result.confidence_multiplier == pytest.approx(1.0)

    def test_si43_confidence_reduced_on_drift(self):
        """SI-43 drift — confidence_multiplier < 1.0 on drift detection."""
        d = DriftDetector(threshold=0.01, ewma_alpha=0.001, reset_on_detect=False)
        results = [d.update(0.50 + 0.005 * i) for i in range(50)]
        drift_results = [r for r in results if r.drift_detected]
        if drift_results:
            assert all(r.confidence_multiplier < 1.0 for r in drift_results)

    def test_si44_cusum_resets_after_detection(self):
        """SI-44 drift — CUSUM resets after detection (reset_on_detect=True)."""
        d = DriftDetector(threshold=0.05, ewma_alpha=0.001, reset_on_detect=True)
        for i in range(50):
            d.update(0.50 + 0.01 * i)
        assert d._cusum_pos == pytest.approx(0.0)

    def test_si45_reset_clears_cusum(self):
        """SI-45 drift — reset() clears cusum accumulators."""
        d = DriftDetector()
        d._cusum_pos = 5.0
        d._cusum_neg = 3.0
        d.reset()
        assert d._cusum_pos == pytest.approx(0.0)
        assert d._cusum_neg == pytest.approx(0.0)

    def test_si46_to_dict_expected_keys(self):
        """SI-46 drift — to_dict() contains expected keys."""
        d = DriftDetector()
        d.update(0.50)
        result = d.to_dict()
        for key in ("baseline", "cusum_pos", "cusum_neg", "threshold", "tick_count", "is_ready"):
            assert key in result
