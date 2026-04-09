from __future__ import annotations

import asyncio

from projects.polymarket.polyquantbot.execution.engine import ExecutionEngine


async def _build_closed_trades() -> tuple[list[dict[str, object]], dict[str, object]]:
    engine = ExecutionEngine(starting_equity=10_000.0)

    first = await engine.open_position(
        market="mkt-s1-news",
        market_title="S1 NEWS",
        side="YES",
        price=0.50,
        size=100.0,
        position_id="p14-1",
        position_context={
            "strategy_source": "S1",
            "regime_at_entry": "NEWS_DRIVEN",
            "entry_quality": "quality_enter",
            "entry_timing": "timing_enter",
            "theoretical_edge": 0.05,
            "slippage_impact": 0.01,
            "timing_effectiveness": 0.90,
        },
    )
    assert first is not None
    await engine.close_position(
        first,
        0.60,
        close_context={"exit_reason": "momentum_weakened_after_favorable_move", "exit_efficiency": 0.95},
    )

    second = await engine.open_position(
        market="mkt-s2-arb",
        market_title="S2 ARB",
        side="YES",
        price=0.60,
        size=100.0,
        position_id="p14-2",
        position_context={
            "strategy_source": "S2",
            "regime_at_entry": "ARBITRAGE_DOMINANT",
            "entry_quality": "quality_reduce",
            "entry_timing": "timing_wait_then_enter",
            "theoretical_edge": 0.08,
            "slippage_impact": 0.03,
            "timing_effectiveness": 0.50,
        },
    )
    assert second is not None
    await engine.close_position(
        second,
        0.55,
        close_context={"exit_reason": "stop_loss_threshold_breached", "exit_efficiency": 0.20},
    )

    payload = await engine.snapshot()
    assert round(payload.realized_pnl, 6) == 5.0

    return list(engine._closed_trades), engine.get_analytics().summary()


async def _build_edge_safety_trades() -> dict[str, object]:
    engine = ExecutionEngine(starting_equity=10_000.0)
    position = await engine.open_position(
        market="mkt-falcon-chaotic",
        market_title="FALCON CHAOTIC",
        side="YES",
        price=0.50,
        size=100.0,
        position_id="p14-safety-1",
        position_context={
            "strategy_source": "FALCON",
            "regime_at_entry": "LOW_ACTIVITY_CHAOTIC",
            "entry_quality": "quality_enter",
            "entry_timing": "timing_enter",
            "theoretical_edge": 0.0001,
            "slippage_impact": 0.01,
            "timing_effectiveness": 0.6,
        },
    )
    assert position is not None
    await engine.close_position(
        position,
        0.90,
        close_context={"exit_reason": "take_profit", "exit_efficiency": 0.8},
    )

    ignored = await engine.open_position(
        market="mkt-safety-zero-edge",
        market_title="ZERO EDGE",
        side="YES",
        price=0.50,
        size=100.0,
        position_id="p14-safety-2",
        position_context={
            "strategy_source": "S3",
            "regime_at_entry": "SMART_MONEY_DOMINANT",
            "entry_quality": "quality_enter",
            "entry_timing": "timing_enter",
            "theoretical_edge": 0.0,
        },
    )
    assert ignored is not None
    await engine.close_position(ignored, 0.60, close_context={"exit_reason": "take_profit", "exit_efficiency": 0.8})
    return engine.get_analytics().summary()


def test_correct_pnl_aggregation() -> None:
    _, summary = asyncio.run(_build_closed_trades())

    assert summary["pnl"]["total_pnl"] == 5.0
    assert summary["pnl"]["avg_pnl_per_trade"] == 2.5
    assert summary["win_rate"] == 0.5


def test_strategy_attribution_correctness() -> None:
    _, summary = asyncio.run(_build_closed_trades())

    breakdown = summary["strategy_breakdown"]
    assert breakdown["S1"]["pnl"] == 10.0
    assert breakdown["S1"]["win_rate"] == 1.0
    assert breakdown["S2"]["pnl"] == -5.0
    assert breakdown["S2"]["win_rate"] == 0.0


def test_regime_attribution_correctness() -> None:
    _, summary = asyncio.run(_build_closed_trades())

    regime = summary["regime_breakdown"]
    assert regime["NEWS"]["pnl"] == 10.0
    assert regime["ARBITRAGE"]["pnl"] == -5.0


def test_edge_captured_calculation_correct() -> None:
    _, summary = asyncio.run(_build_closed_trades())

    # trade1: 0.10/0.05=2.0 ; trade2: -0.05/0.08=-0.625 ; avg=0.6875
    assert summary["edge_captured"] == 0.6875


def test_expectancy_calculation_correct() -> None:
    _, summary = asyncio.run(_build_closed_trades())
    assert summary["expectancy"] == 2.5


def test_edge_capture_safe_computation_bounded_and_division_safe() -> None:
    summary = asyncio.run(_build_edge_safety_trades())
    assert summary["edge_captured"] == 3.0
    assert summary["strategy_breakdown"]["FALCON"]["pnl"] == 40.0
    assert summary["regime_breakdown"]["CHAOTIC"]["pnl"] == 40.0


def test_deterministic_output() -> None:
    _, first = asyncio.run(_build_closed_trades())
    _, second = asyncio.run(_build_closed_trades())

    assert first == second


def test_trade_lifecycle_output_contains_required_attribution_fields() -> None:
    closed_trades, summary = asyncio.run(_build_closed_trades())

    assert len(closed_trades) == 2
    for trade in closed_trades:
        assert set(
            [
                "strategy_source",
                "regime_at_entry",
                "entry_quality",
                "entry_timing",
                "exit_reason",
                "duration",
            ]
        ).issubset(trade.keys())

    assert summary["execution_quality_metrics"]["avg_slippage_impact"] == 0.02
    assert summary["execution_quality_metrics"]["avg_timing_effectiveness"] == 0.7
    assert summary["execution_quality_metrics"]["avg_exit_efficiency"] == 0.575
