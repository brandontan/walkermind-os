from __future__ import annotations

from projects.polymarket.polyquantbot.execution.strategy_trigger import StrategyConfig, StrategyTrigger


class _Engine:
    max_total_exposure_ratio = 0.30
    max_position_size_ratio = 0.10


def _make_trigger() -> StrategyTrigger:
    return StrategyTrigger(
        engine=_Engine(),
        config=StrategyConfig(
            market_id="p12-market",
            min_edge=0.02,
            min_position_size_usd=25.0,
            max_execution_spread=0.04,
            borderline_execution_spread=0.025,
            min_execution_depth_usd=10_000.0,
            borderline_execution_depth_usd=20_000.0,
            max_slippage_edge_consumption_ratio=0.60,
            borderline_slippage_edge_consumption_ratio=0.35,
            execution_reduction_factor=0.50,
            anti_chase_extension_ratio=0.025,
            anti_chase_spread_ratio=0.030,
            micro_pullback_improvement_ratio=0.008,
            timing_reevaluation_window_seconds=15,
            timing_max_wait_cycles=2,
        ),
    )


def test_normal_stable_entry_returns_enter_now() -> None:
    trigger = _make_trigger()

    readiness = trigger.evaluate_entry_execution_readiness(
        market_price=0.50,
        signal_reference_price=0.50,
        proposed_size=300.0,
        signal_edge=0.08,
        market_context={"best_bid": 0.495, "best_ask": 0.505, "orderbook_depth_usd": 80_000.0},
    )

    assert readiness.timing_decision == "ENTER_NOW"
    assert readiness.timing_reason == "stable_entry_window"
    assert readiness.final_execution_readiness is True
    assert readiness.execution_quality_decision in {"ENTER", "REDUCE"}


def test_sharp_spike_chase_condition_returns_wait() -> None:
    trigger = _make_trigger()

    readiness = trigger.evaluate_entry_execution_readiness(
        market_price=0.54,
        signal_reference_price=0.50,
        proposed_size=300.0,
        signal_edge=0.08,
        market_context={
            "best_bid": 0.52,
            "best_ask": 0.56,
            "orderbook_depth_usd": 80_000.0,
            "post_signal_peak_price": 0.56,
        },
        wait_cycles=0,
    )

    assert readiness.timing_decision == "WAIT"
    assert readiness.timing_reason == "anti_chase_spike_detected"
    assert readiness.reevaluation_window == 15
    assert readiness.final_execution_readiness is False


def test_micro_pullback_flow_wait_then_enter() -> None:
    trigger = _make_trigger()

    waiting = trigger.evaluate_entry_execution_readiness(
        market_price=0.538,
        signal_reference_price=0.50,
        proposed_size=300.0,
        signal_edge=0.08,
        market_context={
            "best_bid": 0.536,
            "best_ask": 0.540,
            "orderbook_depth_usd": 90_000.0,
            "post_signal_peak_price": 0.54,
        },
        wait_cycles=0,
    )
    entered = trigger.evaluate_entry_execution_readiness(
        market_price=0.535,
        signal_reference_price=0.50,
        proposed_size=300.0,
        signal_edge=0.08,
        market_context={
            "best_bid": 0.532,
            "best_ask": 0.538,
            "orderbook_depth_usd": 90_000.0,
            "post_signal_peak_price": 0.54,
        },
        wait_cycles=1,
    )

    assert waiting.timing_decision == "WAIT"
    assert waiting.timing_reason == "awaiting_micro_pullback"
    assert entered.timing_decision == "ENTER_NOW"
    assert entered.timing_reason == "micro_pullback_improved_entry"
    assert entered.final_execution_readiness is True


def test_reevaluation_timeout_is_deterministic_skip() -> None:
    trigger = _make_trigger()

    timeout_result = trigger.evaluate_entry_execution_readiness(
        market_price=0.54,
        signal_reference_price=0.50,
        proposed_size=300.0,
        signal_edge=0.08,
        market_context={
            "best_bid": 0.52,
            "best_ask": 0.56,
            "orderbook_depth_usd": 80_000.0,
            "post_signal_peak_price": 0.56,
        },
        wait_cycles=2,
    )

    assert timeout_result.timing_decision == "SKIP"
    assert timeout_result.timing_reason == "anti_chase_timeout_skip"
    assert timeout_result.reevaluation_window == 0
    assert timeout_result.final_execution_readiness is False


def test_coordination_with_p10_quality_gate_remains_correct() -> None:
    trigger = _make_trigger()

    readiness = trigger.evaluate_entry_execution_readiness(
        market_price=0.50,
        signal_reference_price=0.50,
        proposed_size=300.0,
        signal_edge=0.08,
        market_context={"best_bid": 0.46, "best_ask": 0.54, "orderbook_depth_usd": 90_000.0},
    )

    assert readiness.timing_decision == "ENTER_NOW"
    assert readiness.execution_quality_decision == "SKIP"
    assert readiness.execution_quality_reason == "spread_too_wide"
    assert readiness.final_execution_readiness is False


def test_timing_decision_is_deterministic_for_same_input() -> None:
    trigger = _make_trigger()
    context = {
        "best_bid": 0.495,
        "best_ask": 0.505,
        "orderbook_depth_usd": 85_000.0,
        "post_signal_peak_price": 0.505,
    }

    first = trigger.evaluate_entry_execution_readiness(
        market_price=0.50,
        signal_reference_price=0.50,
        proposed_size=300.0,
        signal_edge=0.08,
        market_context=context,
        wait_cycles=0,
    )
    second = trigger.evaluate_entry_execution_readiness(
        market_price=0.50,
        signal_reference_price=0.50,
        proposed_size=300.0,
        signal_edge=0.08,
        market_context=context,
        wait_cycles=0,
    )

    assert first == second
