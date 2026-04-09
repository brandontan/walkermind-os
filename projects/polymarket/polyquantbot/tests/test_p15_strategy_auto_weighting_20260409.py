from __future__ import annotations

from dataclasses import dataclass

from projects.polymarket.polyquantbot.execution.analytics import PerformanceTracker
from projects.polymarket.polyquantbot.execution.strategy_trigger import (
    CrossExchangeArbitrageDecision,
    MarketRegimeInputs,
    SmartMoneyCopyTradingDecision,
    StrategyConfig,
    StrategyDecision,
    StrategyTrigger,
)


def _build_tracker() -> PerformanceTracker:
    tracker = PerformanceTracker()
    rows = [
        {"position_id": "s1-1", "size": 100.0, "pnl": 18.0, "strategy_source": "S1", "regime_at_entry": "NEWS_DRIVEN", "actual_return": 0.18, "theoretical_edge": 0.05},
        {"position_id": "s1-2", "size": 100.0, "pnl": 12.0, "strategy_source": "S1", "regime_at_entry": "NEWS_DRIVEN", "actual_return": 0.12, "theoretical_edge": 0.04},
        {"position_id": "s2-1", "size": 100.0, "pnl": -8.0, "strategy_source": "S2", "regime_at_entry": "ARBITRAGE_DOMINANT", "actual_return": -0.08, "theoretical_edge": 0.03},
        {"position_id": "s3-1", "size": 100.0, "pnl": 4.0, "strategy_source": "S3", "regime_at_entry": "SMART_MONEY_DOMINANT", "actual_return": 0.04, "theoretical_edge": 0.03},
        {"position_id": "s5-1", "size": 100.0, "pnl": 2.0, "strategy_source": "S5", "regime_at_entry": "ARBITRAGE_DOMINANT", "actual_return": 0.02, "theoretical_edge": 0.02},
        {"position_id": "fal-1", "size": 100.0, "pnl": 9.0, "strategy_source": "FALCON", "regime_at_entry": "SMART_MONEY_DOMINANT", "actual_return": 0.09, "theoretical_edge": 0.04},
    ]
    for row in rows:
        tracker.record_trade(row)
    return tracker


@dataclass(frozen=True)
class _EngineStub:
    max_total_exposure_ratio: float = 0.30
    max_position_size_ratio: float = 0.10

    def __post_init__(self) -> None:
        object.__setattr__(self, "_analytics", _build_tracker())

    def get_analytics(self) -> PerformanceTracker:
        return self._analytics



def _make_trigger() -> StrategyTrigger:
    return StrategyTrigger(engine=_EngineStub(), config=StrategyConfig(market_id="m-p15"))



def _run_aggregation(trigger: StrategyTrigger, regime_inputs: MarketRegimeInputs) -> dict[str, float]:
    result = trigger.aggregate_strategy_decisions(
        s1_decision=StrategyDecision(decision="ENTER", reason="s1", edge=0.04),
        s2_decision=CrossExchangeArbitrageDecision(
            decision="ENTER",
            reason="s2",
            edge=0.04,
            matched_markets_info={"market": "k1"},
        ),
        s3_decision=SmartMoneyCopyTradingDecision(decision="ENTER", reason="s3", confidence=0.75, wallet_info={}),
        market_regime_inputs=regime_inputs,
    )
    return result.strategy_weights or {}



def test_strong_strategy_gets_higher_weight() -> None:
    trigger = _make_trigger()
    weights = _run_aggregation(
        trigger,
        MarketRegimeInputs(
            social_spike_intensity=0.80,
            price_dispersion=0.20,
            wallet_activity_strength=0.40,
            trade_frequency=0.50,
            volatility=0.40,
        ),
    )
    assert weights["S1"] > weights["S2"]



def test_weak_strategy_reduced() -> None:
    trigger = _make_trigger()
    weights = _run_aggregation(
        trigger,
        MarketRegimeInputs(
            social_spike_intensity=0.15,
            price_dispersion=0.15,
            wallet_activity_strength=0.15,
            trade_frequency=0.90,
            volatility=0.90,
        ),
    )
    assert weights["S2"] < 1.0



def test_regime_modifies_weights() -> None:
    trigger = _make_trigger()
    smart_money = _run_aggregation(
        trigger,
        MarketRegimeInputs(
            social_spike_intensity=0.30,
            price_dispersion=0.30,
            wallet_activity_strength=0.90,
            trade_frequency=0.65,
            volatility=0.55,
        ),
    )
    chaotic = _run_aggregation(
        trigger,
        MarketRegimeInputs(
            social_spike_intensity=0.10,
            price_dispersion=0.10,
            wallet_activity_strength=0.10,
            trade_frequency=0.95,
            volatility=0.95,
        ),
    )
    assert smart_money["FALCON"] > chaotic["FALCON"]



def test_outputs_are_deterministic() -> None:
    first_trigger = _make_trigger()
    second_trigger = _make_trigger()
    inputs = MarketRegimeInputs(
        social_spike_intensity=0.75,
        price_dispersion=0.20,
        wallet_activity_strength=0.35,
        trade_frequency=0.45,
        volatility=0.45,
    )
    first = _run_aggregation(first_trigger, inputs)
    second = _run_aggregation(second_trigger, inputs)
    assert first == second



def test_no_extreme_jumps_and_expected_keys_present() -> None:
    trigger = _make_trigger()
    first = _run_aggregation(
        trigger,
        MarketRegimeInputs(
            social_spike_intensity=0.85,
            price_dispersion=0.15,
            wallet_activity_strength=0.35,
            trade_frequency=0.45,
            volatility=0.35,
        ),
    )
    second = _run_aggregation(
        trigger,
        MarketRegimeInputs(
            social_spike_intensity=0.10,
            price_dispersion=0.10,
            wallet_activity_strength=0.10,
            trade_frequency=0.90,
            volatility=0.90,
        ),
    )
    assert set(second.keys()) == {"S1", "S2", "S3", "S5", "FALCON"}
    for strategy_name, weight in second.items():
        assert 0.5 <= weight <= 1.5
        assert abs(weight - first[strategy_name]) <= 0.15
