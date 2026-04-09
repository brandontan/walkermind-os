from __future__ import annotations

from projects.polymarket.polyquantbot.execution.strategy_trigger import StrategyConfig, StrategyTrigger


class _Engine:
    max_total_exposure_ratio = 0.30
    max_position_size_ratio = 0.10


def _make_trigger() -> StrategyTrigger:
    return StrategyTrigger(
        engine=_Engine(),
        config=StrategyConfig(
            market_id="p10-market",
            min_edge=0.02,
            min_position_size_usd=25.0,
            max_execution_spread=0.04,
            borderline_execution_spread=0.025,
            min_execution_depth_usd=10_000.0,
            borderline_execution_depth_usd=20_000.0,
            max_slippage_edge_consumption_ratio=0.60,
            borderline_slippage_edge_consumption_ratio=0.35,
            execution_reduction_factor=0.50,
        ),
    )


def test_tight_spread_and_sufficient_depth_allows_execution() -> None:
    trigger = _make_trigger()
    result = trigger.evaluate_execution_quality(
        market_price=0.50,
        proposed_size=300.0,
        signal_edge=0.08,
        market_context={"best_bid": 0.495, "best_ask": 0.505, "orderbook_depth_usd": 75_000.0},
    )

    assert result.final_decision == "ENTER"
    assert result.adjusted_size == 300.0
    assert result.execution_quality_reason == "fill_quality_ok"


def test_wide_spread_skips_execution() -> None:
    trigger = _make_trigger()
    result = trigger.evaluate_execution_quality(
        market_price=0.50,
        proposed_size=300.0,
        signal_edge=0.08,
        market_context={"best_bid": 0.46, "best_ask": 0.54, "orderbook_depth_usd": 90_000.0},
    )

    assert result.final_decision == "SKIP"
    assert result.execution_quality_reason == "spread_too_wide"


def test_thin_liquidity_reduces_size() -> None:
    trigger = _make_trigger()
    result = trigger.evaluate_execution_quality(
        market_price=0.40,
        proposed_size=500.0,
        signal_edge=0.09,
        market_context={"best_bid": 0.395, "best_ask": 0.405, "orderbook_depth_usd": 15_000.0},
    )

    assert result.final_decision == "REDUCE"
    assert 0.0 < result.adjusted_size < 500.0
    assert result.execution_quality_reason == "size_reduced_for_liquidity"


def test_insufficient_depth_skips_execution() -> None:
    trigger = _make_trigger()
    result = trigger.evaluate_execution_quality(
        market_price=0.40,
        proposed_size=350.0,
        signal_edge=0.07,
        market_context={"best_bid": 0.395, "best_ask": 0.405, "orderbook_depth_usd": 5_000.0},
    )

    assert result.final_decision == "SKIP"
    assert result.execution_quality_reason == "insufficient_depth"


def test_high_slippage_consuming_edge_skips_execution() -> None:
    trigger = _make_trigger()
    result = trigger.evaluate_execution_quality(
        market_price=0.60,
        proposed_size=1_000.0,
        signal_edge=0.02,
        market_context={"best_bid": 0.588, "best_ask": 0.612, "orderbook_depth_usd": 12_000.0},
    )

    assert result.final_decision == "SKIP"
    assert result.execution_quality_reason == "slippage_too_high"


def test_borderline_quality_reduces_size() -> None:
    trigger = _make_trigger()
    result = trigger.evaluate_execution_quality(
        market_price=0.55,
        proposed_size=400.0,
        signal_edge=0.03,
        market_context={"best_bid": 0.538, "best_ask": 0.562, "orderbook_depth_usd": 30_000.0},
    )

    assert result.final_decision == "REDUCE"
    assert result.execution_quality_reason == "size_reduced_for_liquidity"


def test_execution_quality_is_deterministic_for_same_input() -> None:
    trigger = _make_trigger()
    market_context = {"best_bid": 0.495, "best_ask": 0.505, "orderbook_depth_usd": 60_000.0}

    first = trigger.evaluate_execution_quality(
        market_price=0.50,
        proposed_size=300.0,
        signal_edge=0.08,
        market_context=market_context,
    )
    second = trigger.evaluate_execution_quality(
        market_price=0.50,
        proposed_size=300.0,
        signal_edge=0.08,
        market_context=market_context,
    )

    assert first == second


def test_no_unrealistic_paper_fill_assumption() -> None:
    trigger = _make_trigger()
    result = trigger.evaluate_execution_quality(
        market_price=0.44,
        proposed_size=250.0,
        signal_edge=0.07,
        market_context={"best_bid": 0.438, "best_ask": 0.442, "orderbook_depth_usd": 80_000.0},
    )

    assert result.expected_fill_price >= 0.442
    assert result.expected_fill_price >= 0.44
    assert result.expected_slippage >= 0.0


def test_runtime_proof_enter_skip_reduce_and_slippage_math() -> None:
    trigger = _make_trigger()

    enter = trigger.evaluate_execution_quality(
        market_price=0.50,
        proposed_size=300.0,
        signal_edge=0.08,
        market_context={"best_bid": 0.495, "best_ask": 0.505, "orderbook_depth_usd": 75_000.0},
    )
    skip = trigger.evaluate_execution_quality(
        market_price=0.50,
        proposed_size=300.0,
        signal_edge=0.08,
        market_context={"best_bid": 0.46, "best_ask": 0.54, "orderbook_depth_usd": 75_000.0},
    )
    reduce = trigger.evaluate_execution_quality(
        market_price=0.40,
        proposed_size=500.0,
        signal_edge=0.09,
        market_context={"best_bid": 0.395, "best_ask": 0.405, "orderbook_depth_usd": 15_000.0},
    )

    assert enter.final_decision == "ENTER"
    assert skip.final_decision == "SKIP"
    assert reduce.final_decision == "REDUCE"
    assert enter.expected_fill_price >= 0.505
    assert enter.expected_slippage == round(enter.expected_fill_price - 0.505, 6)
