from __future__ import annotations

from dataclasses import dataclass

from projects.polymarket.polyquantbot.execution.analytics import PerformanceTracker
from projects.polymarket.polyquantbot.execution.strategy_trigger import (
    CrossExchangeArbitrageDecision,
    SmartMoneyCopyTradingDecision,
    StrategyConfig,
    StrategyDecision,
    StrategyTrigger,
)


def _build_tracker_with_mixed_results() -> PerformanceTracker:
    tracker = PerformanceTracker()
    rows = [
        {"position_id": "t1", "size": 100.0, "pnl": 12.0, "strategy_source": "S1", "regime_at_entry": "NEWS_DRIVEN", "actual_return": 0.12, "theoretical_edge": 0.04, "slippage_impact": 0.01, "timing_effectiveness": 0.80, "exit_efficiency": 0.80},
        {"position_id": "t2", "size": 100.0, "pnl": 8.0, "strategy_source": "S1", "regime_at_entry": "NEWS_DRIVEN", "actual_return": 0.08, "theoretical_edge": 0.03, "slippage_impact": 0.01, "timing_effectiveness": 0.75, "exit_efficiency": 0.70},
        {"position_id": "t3", "size": 100.0, "pnl": -7.0, "strategy_source": "S2", "regime_at_entry": "ARBITRAGE_DOMINANT", "actual_return": -0.07, "theoretical_edge": 0.03, "slippage_impact": 0.05, "timing_effectiveness": 0.35, "exit_efficiency": 0.40},
        {"position_id": "t4", "size": 100.0, "pnl": -9.0, "strategy_source": "S2", "regime_at_entry": "ARBITRAGE_DOMINANT", "actual_return": -0.09, "theoretical_edge": 0.04, "slippage_impact": 0.05, "timing_effectiveness": 0.30, "exit_efficiency": 0.35},
        {"position_id": "t5", "size": 100.0, "pnl": 3.0, "strategy_source": "S3", "regime_at_entry": "SMART_MONEY_DOMINANT", "actual_return": 0.03, "theoretical_edge": 0.03, "slippage_impact": 0.02, "timing_effectiveness": 0.60, "exit_efficiency": 0.60},
    ]
    for row in rows:
        tracker.record_trade(row)
    return tracker


def test_strong_strategy_weight_increases() -> None:
    optimization = _build_tracker_with_mixed_results().optimization_output()
    assert optimization["strategy_weights"]["S1"] > 1.0


def test_weak_strategy_weight_decreases() -> None:
    optimization = _build_tracker_with_mixed_results().optimization_output()
    assert optimization["strategy_weights"]["S2"] < 1.0


def test_high_drawdown_reduces_risk_aggression() -> None:
    tracker = PerformanceTracker()
    for idx, pnl in enumerate([8.0, -12.0, -13.0, -9.0, -7.0], start=1):
        tracker.record_trade(
            {
                "position_id": f"dd-{idx}",
                "size": 100.0,
                "pnl": pnl,
                "strategy_source": "S3",
                "regime_at_entry": "LOW_ACTIVITY_CHAOTIC",
                "actual_return": pnl / 100.0,
                "theoretical_edge": 0.04,
            }
        )
    optimization = tracker.optimization_output()
    assert optimization["risk_adjustments"]["aggression_multiplier"] < 1.0
    assert optimization["risk_adjustments"]["size_multiplier"] < 1.0


def test_adjustments_are_deterministic() -> None:
    first = _build_tracker_with_mixed_results().optimization_output()
    second = _build_tracker_with_mixed_results().optimization_output()
    assert first == second


def test_all_adjustments_are_bounded_no_extreme_jumps() -> None:
    optimization = _build_tracker_with_mixed_results().optimization_output()
    for modifier in optimization["strategy_weights"].values():
        assert 0.75 <= modifier <= 1.15
    for modifier in optimization["regime_weights"].values():
        assert 0.85 <= modifier <= 1.15
    assert 0.85 <= optimization["risk_adjustments"]["aggression_multiplier"] <= 1.0
    assert 0.85 <= optimization["risk_adjustments"]["size_multiplier"] <= 1.0
    assert 0.85 <= optimization["execution_adjustments"]["p10_max_spread_multiplier"] <= 1.0
    assert 0.80 <= optimization["execution_adjustments"]["p10_slippage_guard_multiplier"] <= 1.0
    assert 0 <= optimization["execution_adjustments"]["p12_wait_cycle_bias"] <= 2
    assert 1.0 <= optimization["execution_adjustments"]["p12_reevaluation_window_multiplier"] <= 1.2
    assert 0.80 <= optimization["execution_adjustments"]["p13_exit_sensitivity_multiplier"] <= 1.0


@dataclass(frozen=True)
class _EngineStub:
    max_total_exposure_ratio: float = 0.30
    max_position_size_ratio: float = 0.10

    def __post_init__(self) -> None:
        object.__setattr__(self, "_analytics", _build_tracker_with_mixed_results())

    def get_analytics(self) -> PerformanceTracker:
        return self._analytics


def test_before_after_weight_changes_and_strategy_ranking_example() -> None:
    trigger = StrategyTrigger(engine=_EngineStub(), config=StrategyConfig(market_id="m-p14-1"))
    baseline = trigger.aggregate_strategy_decisions(
        s1_decision=StrategyDecision(decision="ENTER", reason="s1", edge=0.04),
        s2_decision=CrossExchangeArbitrageDecision(decision="ENTER", reason="s2", edge=0.04, matched_markets_info={}),
        s3_decision=SmartMoneyCopyTradingDecision(decision="ENTER", reason="s3", confidence=0.4, wallet_info={}),
    )
    trigger.refresh_optimization_output()
    optimized = trigger.aggregate_strategy_decisions(
        s1_decision=StrategyDecision(decision="ENTER", reason="s1", edge=0.04),
        s2_decision=CrossExchangeArbitrageDecision(decision="ENTER", reason="s2", edge=0.04, matched_markets_info={}),
        s3_decision=SmartMoneyCopyTradingDecision(decision="ENTER", reason="s3", confidence=0.4, wallet_info={}),
    )
    baseline_scores = {item.strategy_name: item.score for item in baseline.ranked_candidates}
    optimized_scores = {item.strategy_name: item.score for item in optimized.ranked_candidates}
    assert optimized_scores["S1"] > baseline_scores["S1"]
    assert optimized_scores["S2"] < baseline_scores["S2"]
