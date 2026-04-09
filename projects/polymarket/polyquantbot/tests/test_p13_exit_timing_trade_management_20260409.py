from __future__ import annotations

from dataclasses import dataclass

from projects.polymarket.polyquantbot.execution.models import Position
from projects.polymarket.polyquantbot.execution.strategy_trigger import StrategyConfig, StrategyTrigger


@dataclass(frozen=True)
class _Snapshot:
    positions: tuple[Position, ...]
    cash: float
    equity: float
    realized_pnl: float
    unrealized_pnl: float
    implied_prob: float
    volatility: float


class _NoopEngine:
    max_total_exposure_ratio = 0.30
    max_position_size_ratio = 0.10

    async def snapshot(self):  # pragma: no cover - not used
        return _Snapshot(
            positions=tuple(),
            cash=10_000.0,
            equity=10_000.0,
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            implied_prob=0.5,
            volatility=0.1,
        )


def _make_trigger() -> StrategyTrigger:
    return StrategyTrigger(
        engine=_NoopEngine(),
        config=StrategyConfig(
            market_id="m-p13",
            target_pnl=25.0,
            stop_loss_ratio=0.04,
            favorable_pnl_ratio=0.015,
            momentum_weakening_ratio=0.35,
            stale_trade_price_move_ratio=0.003,
            max_trade_duration_seconds=1800,
            hard_max_trade_duration_seconds=3600,
        ),
    )


def _position(price: float, *, entry_price: float = 0.5, size: float = 1000.0, created_at: float = 0.0) -> Position:
    position = Position(
        market_id="m-p13",
        market_title="P13 Market",
        side="YES",
        entry_price=entry_price,
        current_price=entry_price,
        size=size,
        position_id="pos-p13",
        created_at=created_at,
    )
    position.update_price(price)
    return position


def test_profitable_trade_holds_then_exits_on_momentum_weakening() -> None:
    trigger = _make_trigger()
    winning = _position(0.56)
    hold_decision = trigger.evaluate_exit_decision(
        tracked_position=winning,
        market_context={"current_regime": "NEWS_DRIVEN"},
        now_ts=1_000.0,
    )

    weakening = _position(0.53)
    exit_decision = trigger.evaluate_exit_decision(
        tracked_position=weakening,
        market_context={"current_regime": "NEWS_DRIVEN"},
        now_ts=1_010.0,
    )

    assert hold_decision.exit_decision == "HOLD"
    assert hold_decision.exit_reason == "favorable_momentum_intact"
    assert exit_decision.exit_decision == "EXIT_FULL"
    assert exit_decision.exit_reason == "momentum_weakened_after_favorable_move"


def test_losing_trade_triggers_stop_loss_fast() -> None:
    trigger = _make_trigger()
    losing = _position(0.45)

    decision = trigger.evaluate_exit_decision(
        tracked_position=losing,
        market_context={"current_regime": "LOW_ACTIVITY_CHAOTIC"},
        now_ts=900.0,
    )

    assert decision.exit_decision == "EXIT_FULL"
    assert decision.exit_reason == "stop_loss_threshold_breached"


def test_stale_trade_triggers_time_based_exit() -> None:
    trigger = _make_trigger()
    stale = _position(0.5005)

    decision = trigger.evaluate_exit_decision(
        tracked_position=stale,
        market_context={"current_regime": "LOW_ACTIVITY_CHAOTIC"},
        now_ts=2_000.0,
    )

    assert decision.exit_decision == "EXIT_FULL"
    assert decision.exit_reason == "stale_trade_timeout"


def test_regime_and_p9_feedback_adjust_exit_aggressiveness() -> None:
    trigger = _make_trigger()
    for _ in range(6):
        trigger.record_trade_result(strategy_name="S1", pnl=-120.0, edge=0.02, position_size=900.0)
        trigger.record_trade_result(strategy_name="S2", pnl=-80.0, edge=0.02, position_size=800.0)

    borderline_loss = _position(0.465)

    chaotic = trigger.evaluate_exit_decision(
        tracked_position=borderline_loss,
        market_context={"current_regime": "LOW_ACTIVITY_CHAOTIC"},
        now_ts=1_100.0,
    )
    news = trigger.evaluate_exit_decision(
        tracked_position=borderline_loss,
        market_context={"current_regime": "NEWS_DRIVEN"},
        now_ts=1_100.0,
    )

    assert chaotic.exit_decision == "EXIT_FULL"
    assert news.exit_decision == "HOLD"


def test_exit_decision_is_deterministic_for_same_inputs() -> None:
    trigger_a = _make_trigger()
    trigger_b = _make_trigger()
    pos_a = _position(0.54)
    pos_b = _position(0.54)

    first = trigger_a.evaluate_exit_decision(
        tracked_position=pos_a,
        market_context={"current_regime": "SMART_MONEY_DOMINANT", "signal_invalidated": False},
        now_ts=950.0,
    )
    second = trigger_b.evaluate_exit_decision(
        tracked_position=pos_b,
        market_context={"current_regime": "SMART_MONEY_DOMINANT", "signal_invalidated": False},
        now_ts=950.0,
    )

    assert first == second
