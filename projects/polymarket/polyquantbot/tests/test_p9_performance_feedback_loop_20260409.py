from __future__ import annotations

from dataclasses import dataclass

from projects.polymarket.polyquantbot.execution.strategy_trigger import StrategyConfig, StrategyTrigger


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
        config=StrategyConfig(market_id="m-p9-feedback", min_edge=0.02),
    )


def _record_series(trigger: StrategyTrigger, strategy_name: str, entries: list[tuple[float, float, float]]) -> None:
    for pnl, edge, size in entries:
        trigger.record_trade_result(
            strategy_name=strategy_name,
            pnl=pnl,
            edge=edge,
            position_size=size,
        )


def test_good_performance_increases_weight() -> None:
    trigger = _make_trigger()
    _record_series(
        trigger,
        "S1",
        [
            (150.0, 0.06, 1_000.0),
            (120.0, 0.05, 900.0),
            (90.0, 0.045, 800.0),
            (110.0, 0.055, 950.0),
            (85.0, 0.05, 850.0),
            (95.0, 0.048, 900.0),
        ],
    )

    state = trigger.get_adaptive_adjustment_state()
    assert state.strategy_weights["S1"] > 1.0


def test_poor_performance_decreases_weight() -> None:
    trigger = _make_trigger()
    _record_series(
        trigger,
        "S2",
        [
            (-120.0, 0.03, 900.0),
            (-90.0, 0.028, 850.0),
            (-80.0, 0.025, 800.0),
            (-150.0, 0.02, 1_000.0),
            (-70.0, 0.02, 750.0),
            (-95.0, 0.03, 900.0),
        ],
    )

    state = trigger.get_adaptive_adjustment_state()
    assert state.strategy_weights["S2"] < 1.0


def test_sizing_adjusts_safely_within_cap() -> None:
    trigger = _make_trigger()
    _record_series(
        trigger,
        "S1",
        [
            (140.0, 0.06, 1_000.0),
            (120.0, 0.055, 900.0),
            (100.0, 0.05, 800.0),
            (90.0, 0.045, 700.0),
            (110.0, 0.05, 850.0),
        ],
    )

    state = trigger.get_adaptive_adjustment_state()
    assert 0.85 <= state.sizing_modifier <= 1.15


def test_thresholds_adapt_within_bounds() -> None:
    trigger = _make_trigger()
    _record_series(
        trigger,
        "S3",
        [
            (-50.0, 0.02, 600.0),
            (-55.0, 0.025, 650.0),
            (-45.0, 0.02, 600.0),
            (-40.0, 0.02, 550.0),
            (-60.0, 0.03, 700.0),
            (-52.0, 0.025, 650.0),
        ],
    )

    state = trigger.get_adaptive_adjustment_state()
    assert 0.016 <= state.min_edge_threshold <= 0.024
    assert 0.55 <= state.confidence_threshold <= 0.80


def test_no_unstable_oscillation_step_limited() -> None:
    trigger = _make_trigger()
    _record_series(
        trigger,
        "S1",
        [(120.0, 0.06, 900.0)] * 8,
    )
    high_state = trigger.get_adaptive_adjustment_state()
    _record_series(
        trigger,
        "S1",
        [(-120.0, 0.02, 900.0)] * 8,
    )
    low_state = trigger.get_adaptive_adjustment_state()

    assert abs(low_state.strategy_weights["S1"] - high_state.strategy_weights["S1"]) <= 0.30


def test_deterministic_behavior_and_default_fallback() -> None:
    trigger_a = _make_trigger()
    trigger_b = _make_trigger()
    entries = [
        (80.0, 0.05, 800.0),
        (70.0, 0.045, 750.0),
        (90.0, 0.055, 900.0),
        (-30.0, 0.03, 700.0),
        (60.0, 0.04, 800.0),
    ]
    _record_series(trigger_a, "S1", entries)
    _record_series(trigger_b, "S1", entries)

    assert trigger_a.get_adaptive_adjustment_state() == trigger_b.get_adaptive_adjustment_state()

    fallback_trigger = _make_trigger()
    fallback_state = fallback_trigger.get_adaptive_adjustment_state()
    assert fallback_state.strategy_weights == {"S1": 1.0, "S2": 1.0, "S3": 1.0}
    assert fallback_state.sizing_modifier == 1.0
