from __future__ import annotations

from dataclasses import dataclass

from projects.polymarket.polyquantbot.execution.strategy_trigger import (
    AnalyticsPerformanceSnapshot,
    StrategyConfig,
    StrategyTrigger,
)


@dataclass(frozen=True)
class _Snapshot:
    positions: tuple[object, ...]
    cash: float
    equity: float
    realized_pnl: float
    unrealized_pnl: float
    implied_prob: float
    volatility: float


class _Engine:
    def __init__(self) -> None:
        self.max_total_exposure_ratio = 0.30
        self.max_position_size_ratio = 0.10
        self._snapshot = _Snapshot(
            positions=tuple(),
            cash=10_000.0,
            equity=10_000.0,
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            implied_prob=0.50,
            volatility=0.10,
        )


def _make_trigger() -> StrategyTrigger:
    return StrategyTrigger(
        engine=_Engine(),
        config=StrategyConfig(market_id="m-p14-optimization", min_edge=0.02),
    )


def _strategy_analytics() -> dict[str, AnalyticsPerformanceSnapshot]:
    return {
        "S1": AnalyticsPerformanceSnapshot(pnl=420.0, win_rate=0.72, expectancy=0.18, drawdown=0.06, trades=18),
        "S2": AnalyticsPerformanceSnapshot(pnl=90.0, win_rate=0.51, expectancy=0.04, drawdown=0.12, trades=16),
        "S3": AnalyticsPerformanceSnapshot(pnl=-210.0, win_rate=0.32, expectancy=-0.08, drawdown=0.25, trades=17),
    }


def _regime_analytics() -> dict[str, AnalyticsPerformanceSnapshot]:
    return {
        "NEWS_DRIVEN": AnalyticsPerformanceSnapshot(pnl=260.0, win_rate=0.66, expectancy=0.11, drawdown=0.09, trades=14),
        "ARBITRAGE_DOMINANT": AnalyticsPerformanceSnapshot(
            pnl=120.0,
            win_rate=0.58,
            expectancy=0.07,
            drawdown=0.12,
            trades=12,
        ),
        "SMART_MONEY_DOMINANT": AnalyticsPerformanceSnapshot(
            pnl=-40.0,
            win_rate=0.46,
            expectancy=-0.01,
            drawdown=0.17,
            trades=11,
        ),
        "LOW_ACTIVITY_CHAOTIC": AnalyticsPerformanceSnapshot(
            pnl=-180.0,
            win_rate=0.33,
            expectancy=-0.05,
            drawdown=0.22,
            trades=10,
        ),
    }


def test_strong_strategy_weight_increases_and_ranking_example() -> None:
    trigger = _make_trigger()

    before = trigger.get_optimization_output().strategy_weights
    after = trigger.apply_analytics_optimization(
        strategy_analytics=_strategy_analytics(),
        regime_analytics=_regime_analytics(),
        execution_analytics={"high_slippage_ratio": 0.18, "timing_wait_ratio": 0.22, "poor_exit_ratio": 0.18},
        risk_analytics={"current_drawdown": 0.03, "drawdown_trend": -0.01, "loss_streak": 1},
    ).strategy_weights

    assert before["S1"] == 1.0
    assert after["S1"] > before["S1"]
    ranked = sorted(after.items(), key=lambda item: item[1], reverse=True)
    assert ranked[0][0] == "S1"


def test_weak_strategy_weight_decreases_and_soft_disable_not_hard_off() -> None:
    trigger = _make_trigger()

    output = trigger.apply_analytics_optimization(
        strategy_analytics=_strategy_analytics(),
        regime_analytics=_regime_analytics(),
        execution_analytics={"high_slippage_ratio": 0.40, "timing_wait_ratio": 0.20, "poor_exit_ratio": 0.20},
        risk_analytics={"current_drawdown": 0.02, "drawdown_trend": 0.0, "loss_streak": 1},
    )

    assert output.strategy_weights["S3"] < 1.0
    assert output.strategy_weights["S3"] > 0.0


def test_high_drawdown_and_loss_streak_reduce_risk() -> None:
    trigger = _make_trigger()

    before = trigger.get_optimization_output().risk_adjustments
    after = trigger.apply_analytics_optimization(
        strategy_analytics=_strategy_analytics(),
        regime_analytics=_regime_analytics(),
        execution_analytics={"high_slippage_ratio": 0.20, "timing_wait_ratio": 0.20, "poor_exit_ratio": 0.20},
        risk_analytics={"current_drawdown": 0.09, "drawdown_trend": 0.02, "loss_streak": 4},
    ).risk_adjustments

    assert before["aggression_modifier"] == 1.0
    assert before["size_modifier"] == 1.0
    assert after["aggression_modifier"] < 1.0
    assert after["size_modifier"] < 1.0


def test_adjustments_are_deterministic_for_same_inputs() -> None:
    trigger_a = _make_trigger()
    trigger_b = _make_trigger()

    output_a = trigger_a.apply_analytics_optimization(
        strategy_analytics=_strategy_analytics(),
        regime_analytics=_regime_analytics(),
        execution_analytics={"high_slippage_ratio": 0.35, "timing_wait_ratio": 0.38, "poor_exit_ratio": 0.41},
        risk_analytics={"current_drawdown": 0.08, "drawdown_trend": 0.01, "loss_streak": 3},
    )
    output_b = trigger_b.apply_analytics_optimization(
        strategy_analytics=_strategy_analytics(),
        regime_analytics=_regime_analytics(),
        execution_analytics={"high_slippage_ratio": 0.35, "timing_wait_ratio": 0.38, "poor_exit_ratio": 0.41},
        risk_analytics={"current_drawdown": 0.08, "drawdown_trend": 0.01, "loss_streak": 3},
    )

    assert output_a == output_b


def test_no_extreme_jumps_and_bounds_enforced() -> None:
    trigger = _make_trigger()

    first = trigger.apply_analytics_optimization(
        strategy_analytics=_strategy_analytics(),
        regime_analytics=_regime_analytics(),
        execution_analytics={"high_slippage_ratio": 0.95, "timing_wait_ratio": 0.95, "poor_exit_ratio": 0.95},
        risk_analytics={"current_drawdown": 0.20, "drawdown_trend": 0.04, "loss_streak": 8},
    )
    second = trigger.apply_analytics_optimization(
        strategy_analytics=_strategy_analytics(),
        regime_analytics=_regime_analytics(),
        execution_analytics={"high_slippage_ratio": 0.95, "timing_wait_ratio": 0.95, "poor_exit_ratio": 0.95},
        risk_analytics={"current_drawdown": 0.20, "drawdown_trend": 0.04, "loss_streak": 8},
    )

    assert abs(first.strategy_weights["S1"] - 1.0) <= 0.041
    assert abs(second.strategy_weights["S1"] - first.strategy_weights["S1"]) <= 0.041
    assert 0.85 <= second.strategy_weights["S3"] <= 1.15
    assert 0.88 <= second.regime_weights["LOW_ACTIVITY_CHAOTIC"] <= 1.12
    assert 0.80 <= second.risk_adjustments["size_modifier"] <= 1.05
    assert 0.85 <= second.execution_adjustments["p10_spread_tightening"] <= 1.05


def test_insufficient_data_falls_back_to_neutral() -> None:
    trigger = _make_trigger()

    output = trigger.apply_analytics_optimization(
        strategy_analytics={
            "S1": AnalyticsPerformanceSnapshot(pnl=10.0, win_rate=0.6, expectancy=0.01, drawdown=0.03, trades=1)
        },
        regime_analytics={},
        execution_analytics={"high_slippage_ratio": 0.90, "timing_wait_ratio": 0.90, "poor_exit_ratio": 0.90},
        risk_analytics={"current_drawdown": 0.15, "drawdown_trend": 0.03, "loss_streak": 5},
    )

    assert output.strategy_weights == {"S1": 1.0, "S2": 1.0, "S3": 1.0}
    assert output.execution_adjustments == {
        "p10_spread_tightening": 1.0,
        "p12_wait_window_factor": 1.0,
        "p13_exit_sensitivity_factor": 1.0,
    }
