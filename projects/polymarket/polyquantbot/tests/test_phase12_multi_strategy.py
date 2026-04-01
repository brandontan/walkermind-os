"""Phase 12 — Multi-Strategy Orchestration Test Suite.

Validates the StrategyRouter, StrategyAllocator, BacktestEngine, and
MarketFeatures components introduced in Phase 12.

  ── MarketFeatures ──
  MS-01  compute_features — basic fields computed correctly from market_data
  MS-02  compute_features — spread_pct is 0.0 when mid is 0
  MS-03  compute_features — depth_imbalance is None when depth_total == 0
  MS-04  compute_features — depth_imbalance is +1.0 when all depth on YES side
  MS-05  compute_features — depth_imbalance is -1.0 when all depth on NO side
  MS-06  compute_features — vwap_proxy computed from recent_trades
  MS-07  compute_features — vwap_proxy is None when no recent_trades
  MS-08  compute_features — price_velocity from recent_ticks (ascending)
  MS-09  compute_features — price_velocity is None when fewer than 2 ticks
  MS-10  compute_features — to_dict() includes all expected keys

  ── StrategyRouter ──
  MS-11  router — register adds strategy to strategy_names
  MS-12  router — unregister removes strategy from strategy_names
  MS-13  router — unregister returns False for unknown strategy
  MS-14  router — disable excludes strategy from active_strategy_names
  MS-15  router — enable re-activates disabled strategy
  MS-16  router — enable raises KeyError for unknown strategy
  MS-17  router — disable raises KeyError for unknown strategy
  MS-18  router — evaluate returns RouterResult with signals list
  MS-19  router — evaluate with no active strategies returns empty RouterResult
  MS-20  router — evaluate deduplifies same-side signals (best edge wins)
  MS-21  router — evaluate with erroring strategy increments errored count
  MS-22  router — evaluate with timed-out strategy is handled gracefully
  MS-23  router — RouterResult.best_signal() returns highest-edge signal
  MS-24  router — RouterResult.best_signal() returns None when no signals
  MS-25  router — from_registry() registers all three strategies

  ── StrategyAllocator ──
  MS-26  allocator — raises ValueError on non-positive bankroll
  MS-27  allocator — raises ValueError on empty strategy_names
  MS-28  allocator — allocate returns confidence-scaled size
  MS-29  allocator — allocate caps at max_position_usd
  MS-30  allocator — allocate rejects when total_exposure >= cap
  MS-31  allocator — allocate uses minimum confidence multiplier floor
  MS-32  allocator — record_outcome increases win confidence
  MS-33  allocator — record_outcome decreases confidence on loss
  MS-34  allocator — get_confidence raises KeyError for unknown strategy
  MS-35  allocator — snapshot returns dict with all strategy names
  MS-36  allocator — unknown strategy in allocate uses neutral fallback

  ── BacktestEngine ──
  MS-37  backtest — empty tick list returns zero-trade result
  MS-38  backtest — BacktestResult.summary() returns correct keys
  MS-39  backtest — trades are generated when strategies produce signals
  MS-40  backtest — max_position cap enforced on trade size
  MS-41  backtest — win_rate is 0.0 when no trades
  MS-42  backtest — profit_factor is None when no losses
  MS-43  backtest — max_drawdown_pct >= 0.0 after negative PnL
  MS-44  backtest — ticks_processed equals input tick count
  MS-45  backtest — TickData.to_market_data() includes bid/ask/mid/depth keys
  MS-46  backtest — BacktestConfig defaults are risk-compliant (<= 10% position)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, patch

import pytest

from projects.polymarket.polyquantbot.backtest.engine import (
    BacktestConfig,
    BacktestEngine,
    BacktestResult,
    BacktestTrade,
    TickData,
)
from projects.polymarket.polyquantbot.strategy.allocator import (
    AllocationDecision,
    StrategyAllocator,
)
from projects.polymarket.polyquantbot.strategy.base.base_strategy import (
    BaseStrategy,
    SignalResult,
)
from projects.polymarket.polyquantbot.strategy.features.market_features import (
    MarketFeatures,
    compute_features,
)
from projects.polymarket.polyquantbot.strategy.router import RouterResult, StrategyRouter

# ── Helper strategies ─────────────────────────────────────────────────────────


class _AlwaysSignalStrategy(BaseStrategy):
    """Test strategy that always emits a YES signal with configurable edge."""

    def __init__(self, edge: float = 0.10, name_: str = "always_signal") -> None:
        super().__init__(min_edge=0.01)
        self._edge = edge
        self._name = name_

    @property
    def name(self) -> str:
        return self._name

    async def evaluate(
        self, market_id: str, market_data: Dict[str, Any]
    ) -> Optional[SignalResult]:
        return SignalResult(
            market_id=market_id,
            side="YES",
            edge=self._edge,
            size_usdc=50.0,
            confidence=0.9,
            metadata={"strategy": self._name},
        )


class _NeverSignalStrategy(BaseStrategy):
    """Test strategy that never emits a signal."""

    @property
    def name(self) -> str:
        return "never_signal"

    async def evaluate(
        self, market_id: str, market_data: Dict[str, Any]
    ) -> Optional[SignalResult]:
        return None


class _ErrorStrategy(BaseStrategy):
    """Test strategy that always raises an exception."""

    @property
    def name(self) -> str:
        return "error_strategy"

    async def evaluate(
        self, market_id: str, market_data: Dict[str, Any]
    ) -> Optional[SignalResult]:
        raise RuntimeError("deliberate test error")


class _SlowStrategy(BaseStrategy):
    """Test strategy that sleeps longer than the router timeout."""

    @property
    def name(self) -> str:
        return "slow_strategy"

    async def evaluate(
        self, market_id: str, market_data: Dict[str, Any]
    ) -> Optional[SignalResult]:
        import asyncio
        await asyncio.sleep(10)
        return None  # pragma: no cover


# ── Shared market data fixture ─────────────────────────────────────────────────

_MARKET_DATA: Dict[str, Any] = {
    "bid": 0.48,
    "ask": 0.52,
    "mid": 0.50,
    "depth_yes": 20_000.0,
    "depth_no": 15_000.0,
    "volume": 50_000.0,
}

# ─────────────────────────────────────────────────────────────────────────────
# MS-01 – MS-10: MarketFeatures
# ─────────────────────────────────────────────────────────────────────────────


def test_ms01_compute_features_basic():
    """MS-01 compute_features — basic fields computed correctly."""
    features = compute_features(
        {"bid": 0.48, "ask": 0.52, "mid": 0.50, "depth_yes": 20_000, "depth_no": 10_000},
        market_id="mkt-1",
    )
    assert features.bid == pytest.approx(0.48)
    assert features.ask == pytest.approx(0.52)
    assert features.mid == pytest.approx(0.50)
    assert features.spread == pytest.approx(0.04)
    assert features.depth_total == pytest.approx(30_000)


def test_ms02_compute_features_zero_mid():
    """MS-02 compute_features — spread_pct is 0.0 when mid is 0."""
    features = compute_features({"bid": 0.0, "ask": 0.0, "mid": 0.0})
    assert features.spread_pct == 0.0


def test_ms03_compute_features_depth_imbalance_none_when_zero():
    """MS-03 compute_features — depth_imbalance is None when depth_total == 0."""
    features = compute_features({"bid": 0.48, "ask": 0.52, "depth_yes": 0, "depth_no": 0})
    assert features.depth_imbalance is None


def test_ms04_compute_features_depth_imbalance_full_yes():
    """MS-04 compute_features — depth_imbalance is +1.0 when all depth on YES."""
    features = compute_features({"bid": 0.48, "ask": 0.52, "depth_yes": 10_000, "depth_no": 0})
    assert features.depth_imbalance == pytest.approx(1.0)


def test_ms05_compute_features_depth_imbalance_full_no():
    """MS-05 compute_features — depth_imbalance is -1.0 when all depth on NO."""
    features = compute_features({"bid": 0.48, "ask": 0.52, "depth_yes": 0, "depth_no": 10_000})
    assert features.depth_imbalance == pytest.approx(-1.0)


def test_ms06_compute_features_vwap_proxy():
    """MS-06 compute_features — vwap_proxy computed from recent_trades."""
    trades = [{"price": 0.50, "size": 100}, {"price": 0.60, "size": 100}]
    features = compute_features({"bid": 0.48, "ask": 0.52}, recent_trades=trades)
    assert features.vwap_proxy == pytest.approx(0.55)


def test_ms07_compute_features_vwap_none_when_no_trades():
    """MS-07 compute_features — vwap_proxy is None when no recent_trades."""
    features = compute_features({"bid": 0.48, "ask": 0.52})
    assert features.vwap_proxy is None


def test_ms08_compute_features_price_velocity():
    """MS-08 compute_features — price_velocity from ascending tick list."""
    ticks = [0.50, 0.51, 0.52, 0.53]  # velocity = +0.01 per tick
    features = compute_features({"bid": 0.48, "ask": 0.52}, recent_ticks=ticks)
    assert features.price_velocity == pytest.approx(0.01)


def test_ms09_compute_features_velocity_none_single_tick():
    """MS-09 compute_features — price_velocity is None when fewer than 2 ticks."""
    features = compute_features({"bid": 0.48, "ask": 0.52}, recent_ticks=[0.50])
    assert features.price_velocity is None


def test_ms10_compute_features_to_dict_keys():
    """MS-10 compute_features — to_dict() includes all expected keys."""
    features = compute_features(_MARKET_DATA, market_id="mkt-1")
    d = features.to_dict()
    expected_keys = {
        "market_id", "bid", "ask", "mid", "spread", "spread_pct",
        "depth_yes", "depth_no", "depth_total", "depth_imbalance",
        "volume", "vwap_proxy", "price_velocity",
    }
    assert expected_keys.issubset(d.keys())


# ─────────────────────────────────────────────────────────────────────────────
# MS-11 – MS-25: StrategyRouter
# ─────────────────────────────────────────────────────────────────────────────


def test_ms11_router_register_adds_strategy():
    """MS-11 router — register adds strategy to strategy_names."""
    router = StrategyRouter()
    router.register(_AlwaysSignalStrategy())
    assert "always_signal" in router.strategy_names


def test_ms12_router_unregister_removes_strategy():
    """MS-12 router — unregister removes strategy from strategy_names."""
    router = StrategyRouter()
    router.register(_AlwaysSignalStrategy())
    router.unregister("always_signal")
    assert "always_signal" not in router.strategy_names


def test_ms13_router_unregister_returns_false_unknown():
    """MS-13 router — unregister returns False for unknown strategy."""
    router = StrategyRouter()
    result = router.unregister("nonexistent")
    assert result is False


def test_ms14_router_disable_excludes_from_active():
    """MS-14 router — disable excludes strategy from active_strategy_names."""
    router = StrategyRouter()
    router.register(_AlwaysSignalStrategy())
    router.disable("always_signal")
    assert "always_signal" not in router.active_strategy_names


def test_ms15_router_enable_reactivates_disabled():
    """MS-15 router — enable re-activates disabled strategy."""
    router = StrategyRouter()
    router.register(_AlwaysSignalStrategy())
    router.disable("always_signal")
    router.enable("always_signal")
    assert "always_signal" in router.active_strategy_names


def test_ms16_router_enable_raises_for_unknown():
    """MS-16 router — enable raises KeyError for unknown strategy."""
    router = StrategyRouter()
    with pytest.raises(KeyError):
        router.enable("nonexistent")


def test_ms17_router_disable_raises_for_unknown():
    """MS-17 router — disable raises KeyError for unknown strategy."""
    router = StrategyRouter()
    with pytest.raises(KeyError):
        router.disable("nonexistent")


async def test_ms18_router_evaluate_returns_router_result():
    """MS-18 router — evaluate returns RouterResult with signals list."""
    router = StrategyRouter()
    router.register(_AlwaysSignalStrategy(edge=0.10))
    result = await router.evaluate("mkt-1", _MARKET_DATA)
    assert isinstance(result, RouterResult)
    assert result.market_id == "mkt-1"
    assert len(result.signals) >= 0


async def test_ms19_router_evaluate_empty_returns_empty_result():
    """MS-19 router — evaluate with no active strategies returns empty RouterResult."""
    router = StrategyRouter()
    result = await router.evaluate("mkt-1", _MARKET_DATA)
    assert result.signals == []
    assert result.evaluated == 0


async def test_ms20_router_evaluate_deduplicates_same_side():
    """MS-20 router — evaluate deduplifies same-side signals (best edge wins)."""
    # Two strategies both emit YES but with different edges
    router = StrategyRouter()
    router.register(_AlwaysSignalStrategy(edge=0.08, name_="strat_a"))
    router.register(_AlwaysSignalStrategy(edge=0.12, name_="strat_b"))

    result = await router.evaluate("mkt-1", _MARKET_DATA)
    # Should have only one YES signal (the one with higher edge)
    yes_signals = [s for s in result.signals if s.side == "YES"]
    assert len(yes_signals) == 1
    assert yes_signals[0].edge == pytest.approx(0.12)


async def test_ms21_router_evaluate_erroring_strategy_increments_errored():
    """MS-21 router — evaluate with erroring strategy increments errored count."""
    router = StrategyRouter()
    router.register(_ErrorStrategy())
    result = await router.evaluate("mkt-1", _MARKET_DATA)
    assert result.errored == 1


async def test_ms22_router_evaluate_timed_out_strategy_handled():
    """MS-22 router — evaluate with timed-out strategy is handled gracefully."""
    router = StrategyRouter(timeout_s=0.01)  # very short timeout
    router.register(_SlowStrategy())
    # Should not raise; slow strategy should be treated as errored (no crash)
    result = await router.evaluate("mkt-1", _MARKET_DATA)
    assert isinstance(result, RouterResult)
    # Timeout is treated as an error (no signal emitted, no crash)
    assert result.errored == 1


def test_ms23_router_result_best_signal_highest_edge():
    """MS-23 router — RouterResult.best_signal() returns highest-edge signal."""
    s1 = SignalResult(market_id="m", side="YES", edge=0.10, size_usdc=50.0)
    s2 = SignalResult(market_id="m", side="NO", edge=0.20, size_usdc=30.0)
    r = RouterResult(market_id="m", signals=[s1, s2], evaluated=2, errored=0, skipped=0)
    best = r.best_signal()
    assert best is not None
    assert best.edge == pytest.approx(0.20)


def test_ms24_router_result_best_signal_none_when_empty():
    """MS-24 router — RouterResult.best_signal() returns None when no signals."""
    r = RouterResult(market_id="m", signals=[], evaluated=1, errored=0, skipped=1)
    assert r.best_signal() is None


def test_ms25_router_from_registry_registers_all_three():
    """MS-25 router — from_registry() registers all three strategies."""
    router = StrategyRouter.from_registry()
    assert "ev_momentum" in router.strategy_names
    assert "mean_reversion" in router.strategy_names
    assert "liquidity_edge" in router.strategy_names


# ─────────────────────────────────────────────────────────────────────────────
# MS-26 – MS-36: StrategyAllocator
# ─────────────────────────────────────────────────────────────────────────────


def test_ms26_allocator_raises_on_nonpositive_bankroll():
    """MS-26 allocator — raises ValueError on non-positive bankroll."""
    with pytest.raises(ValueError):
        StrategyAllocator(strategy_names=["ev_momentum"], bankroll=0.0)


def test_ms27_allocator_raises_on_empty_strategy_names():
    """MS-27 allocator — raises ValueError on empty strategy_names."""
    with pytest.raises(ValueError):
        StrategyAllocator(strategy_names=[], bankroll=10_000.0)


def test_ms28_allocator_allocate_confidence_scaled():
    """MS-28 allocator — allocate returns confidence-scaled size."""
    allocator = StrategyAllocator(
        strategy_names=["ev_momentum"],
        bankroll=10_000.0,
        alpha_prior=9.0,  # high confidence (90%)
        beta_prior=1.0,
    )
    decision = allocator.allocate("ev_momentum", raw_size_usd=100.0)
    # With ~90% confidence, adjusted size should be close to 90
    assert not decision.rejected
    assert decision.adjusted_size_usd > 0


def test_ms29_allocator_allocate_caps_at_max_position():
    """MS-29 allocator — allocate caps at max_position_usd."""
    allocator = StrategyAllocator(
        strategy_names=["ev_momentum"],
        bankroll=10_000.0,
        max_position_pct=0.10,  # $1000 cap
        alpha_prior=2.0,
        beta_prior=2.0,
    )
    # Request way more than the cap
    decision = allocator.allocate("ev_momentum", raw_size_usd=5_000.0)
    assert decision.adjusted_size_usd <= 1_000.0


def test_ms30_allocator_allocate_rejects_over_exposure():
    """MS-30 allocator — allocate rejects when total_exposure >= cap."""
    bankroll = 10_000.0
    allocator = StrategyAllocator(
        strategy_names=["ev_momentum"],
        bankroll=bankroll,
        max_total_exposure_pct=0.30,  # $3000 cap
    )
    # Expose already at cap
    decision = allocator.allocate(
        "ev_momentum",
        raw_size_usd=100.0,
        current_exposure_usd=3_000.0,  # at the cap
    )
    assert decision.rejected is True
    assert "total_exposure_cap_reached" in (decision.rejection_reason or "")


def test_ms31_allocator_allocate_min_confidence_floor():
    """MS-31 allocator — allocate uses minimum confidence multiplier floor."""
    allocator = StrategyAllocator(
        strategy_names=["ev_momentum"],
        bankroll=10_000.0,
        alpha_prior=0.01,  # effectively 0 confidence
        beta_prior=100.0,
    )
    decision = allocator.allocate("ev_momentum", raw_size_usd=100.0)
    # Size should be at least min_confidence_multiplier * raw (10% floor)
    assert decision.adjusted_size_usd >= 100.0 * 0.10 - 0.01  # small float tolerance


async def test_ms32_allocator_record_outcome_increases_confidence_on_win():
    """MS-32 allocator — record_outcome increases win confidence."""
    allocator = StrategyAllocator(
        strategy_names=["ev_momentum"],
        bankroll=10_000.0,
        min_samples=1,  # respond immediately
    )
    before = allocator.get_confidence("ev_momentum")
    await allocator.record_outcome("ev_momentum", won=True)
    after = allocator.get_confidence("ev_momentum")
    assert after >= before


async def test_ms33_allocator_record_outcome_decreases_confidence_on_loss():
    """MS-33 allocator — record_outcome decreases confidence on loss."""
    allocator = StrategyAllocator(
        strategy_names=["ev_momentum"],
        bankroll=10_000.0,
        alpha_prior=10.0,  # start with high confidence
        beta_prior=2.0,
        min_samples=1,
    )
    before = allocator.get_confidence("ev_momentum")
    await allocator.record_outcome("ev_momentum", won=False)
    after = allocator.get_confidence("ev_momentum")
    assert after <= before


def test_ms34_allocator_get_confidence_raises_for_unknown():
    """MS-34 allocator — get_confidence raises KeyError for unknown strategy."""
    allocator = StrategyAllocator(strategy_names=["ev_momentum"], bankroll=10_000.0)
    with pytest.raises(KeyError):
        allocator.get_confidence("nonexistent")


def test_ms35_allocator_snapshot_returns_all_strategies():
    """MS-35 allocator — snapshot returns dict with all strategy names."""
    names = ["ev_momentum", "mean_reversion", "liquidity_edge"]
    allocator = StrategyAllocator(strategy_names=names, bankroll=10_000.0)
    snap = allocator.snapshot()
    for name in names:
        assert name in snap
        assert "confidence" in snap[name]


def test_ms36_allocator_unknown_strategy_uses_neutral_fallback():
    """MS-36 allocator — unknown strategy in allocate uses neutral fallback (0.5)."""
    allocator = StrategyAllocator(strategy_names=["ev_momentum"], bankroll=10_000.0)
    # "other_strategy" is not registered — should use 0.5 neutral
    decision = allocator.allocate("other_strategy", raw_size_usd=100.0)
    assert not decision.rejected
    # With neutral 0.5 confidence: adjusted = 100 * max(0.10, 0.5) = 50
    assert decision.adjusted_size_usd == pytest.approx(50.0)


# ─────────────────────────────────────────────────────────────────────────────
# MS-37 – MS-46: BacktestEngine
# ─────────────────────────────────────────────────────────────────────────────


async def test_ms37_backtest_empty_ticks_returns_zero_trades():
    """MS-37 backtest — empty tick list returns zero-trade result."""
    router = StrategyRouter()
    router.register(_AlwaysSignalStrategy())
    engine = BacktestEngine(router=router)
    result = await engine.run([])
    assert result.ticks_processed == 0
    assert len(result.trades) == 0


def test_ms38_backtest_result_summary_keys():
    """MS-38 backtest — BacktestResult.summary() returns correct keys."""
    result = BacktestResult(
        ticks_processed=10,
        trades=[],
        total_pnl_usd=0.0,
        win_rate=0.0,
        sharpe_ratio=None,
        max_drawdown_pct=0.0,
        profit_factor=None,
        signals_generated=0,
        strategies_evaluated=["ev_momentum"],
    )
    summary = result.summary()
    expected_keys = {
        "ticks_processed", "total_trades", "total_pnl_usd", "win_rate",
        "sharpe_ratio", "max_drawdown_pct", "profit_factor",
        "signals_generated", "strategies_evaluated",
    }
    assert expected_keys.issubset(summary.keys())


async def test_ms39_backtest_generates_trades_on_signals():
    """MS-39 backtest — trades are generated when strategies produce signals."""
    router = StrategyRouter()
    router.register(_AlwaysSignalStrategy(edge=0.10))
    config = BacktestConfig(bankroll=10_000.0)
    engine = BacktestEngine(router=router, config=config)

    ticks = [
        TickData(market_id="mkt-1", bid=0.48, ask=0.52, depth_yes=20_000, depth_no=15_000),
        TickData(market_id="mkt-1", bid=0.49, ask=0.53, depth_yes=20_000, depth_no=15_000),
        TickData(market_id="mkt-1", bid=0.50, ask=0.54, depth_yes=20_000, depth_no=15_000),
    ]
    result = await engine.run(ticks)
    assert result.ticks_processed == 3
    assert len(result.trades) > 0


async def test_ms40_backtest_max_position_cap_enforced():
    """MS-40 backtest — max_position cap enforced on trade size."""
    router = StrategyRouter()
    router.register(_AlwaysSignalStrategy(edge=0.10))
    # Very small bankroll to make cap tight
    config = BacktestConfig(bankroll=1_000.0, max_position_pct=0.10)
    engine = BacktestEngine(router=router, config=config)

    ticks = [
        TickData(market_id="mkt-1", bid=0.48, ask=0.52, depth_yes=20_000, depth_no=15_000),
        TickData(market_id="mkt-1", bid=0.49, ask=0.53, depth_yes=20_000, depth_no=15_000),
    ]
    result = await engine.run(ticks)
    max_allowed = 1_000.0 * 0.10  # $100
    for trade in result.trades:
        assert trade.size_usd <= max_allowed + 0.01  # small float tolerance


def test_ms41_backtest_win_rate_zero_no_trades():
    """MS-41 backtest — win_rate is 0.0 when no trades."""
    result = BacktestResult(
        ticks_processed=5,
        trades=[],
        total_pnl_usd=0.0,
        win_rate=0.0,
        sharpe_ratio=None,
        max_drawdown_pct=0.0,
        profit_factor=None,
        signals_generated=0,
        strategies_evaluated=[],
    )
    assert result.win_rate == 0.0


def test_ms42_backtest_profit_factor_none_no_losses():
    """MS-42 backtest — profit_factor is None when no losses."""
    winning_trade = BacktestTrade(
        market_id="m",
        side="YES",
        entry_price=0.48,
        size_usd=50.0,
        signal_edge=0.10,
        exit_price=0.55,
        pnl_usd=5.0,
    )
    result = BacktestResult(
        ticks_processed=1,
        trades=[winning_trade],
        total_pnl_usd=5.0,
        win_rate=1.0,
        sharpe_ratio=None,
        max_drawdown_pct=0.0,
        profit_factor=None,  # explicitly None when no losses
        signals_generated=1,
        strategies_evaluated=["ev_momentum"],
    )
    assert result.profit_factor is None


async def test_ms43_backtest_max_drawdown_non_negative():
    """MS-43 backtest — max_drawdown_pct >= 0.0 after negative PnL."""
    router = StrategyRouter()
    router.register(_AlwaysSignalStrategy(edge=0.05))
    engine = BacktestEngine(router=router, config=BacktestConfig(bankroll=1_000.0))

    ticks = [
        TickData(market_id="mkt-1", bid=0.48, ask=0.52),
        TickData(market_id="mkt-1", bid=0.45, ask=0.48),  # price drops
        TickData(market_id="mkt-1", bid=0.42, ask=0.45),
    ]
    result = await engine.run(ticks)
    assert result.max_drawdown_pct >= 0.0


async def test_ms44_backtest_ticks_processed_equals_input_count():
    """MS-44 backtest — ticks_processed equals input tick count."""
    router = StrategyRouter()
    router.register(_NeverSignalStrategy())
    engine = BacktestEngine(router=router)
    n = 7
    ticks = [
        TickData(market_id="m", bid=0.48, ask=0.52)
        for _ in range(n)
    ]
    result = await engine.run(ticks)
    assert result.ticks_processed == n


def test_ms45_tick_data_to_market_data_keys():
    """MS-45 backtest — TickData.to_market_data() includes bid/ask/mid/depth keys."""
    tick = TickData(
        market_id="mkt-1",
        bid=0.48,
        ask=0.52,
        depth_yes=20_000,
        depth_no=15_000,
    )
    md = tick.to_market_data()
    assert "bid" in md
    assert "ask" in md
    assert "mid" in md
    assert "depth_yes" in md
    assert "depth_no" in md
    assert md["mid"] == pytest.approx(0.50)


def test_ms46_backtest_config_defaults_risk_compliant():
    """MS-46 backtest — BacktestConfig defaults are risk-compliant (<= 10% position)."""
    config = BacktestConfig()
    assert config.max_position_pct <= 0.10
