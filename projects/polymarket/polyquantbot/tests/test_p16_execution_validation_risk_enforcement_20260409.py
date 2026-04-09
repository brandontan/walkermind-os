from __future__ import annotations

import asyncio

from projects.polymarket.polyquantbot.execution.engine import ExecutionEngine
from projects.polymarket.polyquantbot.execution.strategy_trigger import (
    StrategyAggregationDecision,
    StrategyCandidateScore,
    StrategyConfig,
    StrategyTrigger,
)


def _build_aggregation(edge: float = 0.05) -> StrategyAggregationDecision:
    candidate = StrategyCandidateScore(
        strategy_name="S1",
        decision="ENTER",
        reason="test_signal",
        edge=edge,
        confidence=0.9,
        score=0.95,
        market_metadata={"market_id": "MARKET-1", "title": "Test Market"},
    )
    return StrategyAggregationDecision(
        selected_trade="S1",
        ranked_candidates=[candidate],
        selection_reason="highest_score",
        top_score=0.95,
        decision="ENTER",
    )


def _build_trigger(starting_equity: float = 10_000.0) -> StrategyTrigger:
    trigger = StrategyTrigger(
        engine=ExecutionEngine(starting_equity=starting_equity),
        config=StrategyConfig(market_id="MARKET-1", threshold=0.60, target_pnl=2.0),
    )
    trigger._cooldown_seconds = 0.0  # noqa: SLF001
    trigger._intelligence.evaluate_entry = lambda _snapshot: {"score": 1.0, "reasons": ["test"]}  # type: ignore[assignment] # noqa: SLF001
    return trigger


def test_p16_pre_trade_block_when_ev_non_positive() -> None:
    async def _run() -> None:
        trigger = _build_trigger()
        decision = await trigger.evaluate(
            market_price=0.45,
            aggregation_decision=_build_aggregation(),
            market_context={
                "expected_value": 0.0,
                "liquidity_usd": 20_000.0,
                "spread": 0.01,
                "best_bid": 0.44,
                "best_ask": 0.46,
            },
        )
        snapshot = await trigger._engine.snapshot()  # noqa: SLF001
        assert decision == "BLOCKED"
        assert len(snapshot.positions) == 0

    asyncio.run(_run())


def test_p16_successful_trade_records_execution_trace() -> None:
    async def _run() -> None:
        trigger = _build_trigger()
        decision = await trigger.evaluate(
            market_price=0.45,
            aggregation_decision=_build_aggregation(),
            market_context={
                "expected_value": 0.10,
                "liquidity_usd": 50_000.0,
                "spread": 0.01,
                "best_bid": 0.445,
                "best_ask": 0.455,
            },
        )
        assert decision == "OPENED"
        snapshot = await trigger._engine.snapshot()  # noqa: SLF001
        assert len(snapshot.positions) == 1
        trade_id = snapshot.positions[0].position_id
        trace = trigger.get_trade_trace(trade_id)
        assert trace["validation_result"]["decision"] == "ALLOW"
        assert trace["execution_data"]["expected_price"] is not None
        assert trace["execution_data"]["actual_fill_price"] is not None
        assert trace["execution_data"]["latency_ms"] is not None

    asyncio.run(_run())


def test_p16_risk_breach_triggers_global_block() -> None:
    async def _run() -> None:
        trigger = _build_trigger(starting_equity=10_000.0)
        trigger._risk_engine.update_from_snapshot(  # noqa: SLF001
            equity=9_100.0,
            realized_pnl=-2_100.0,
            open_trades=0,
            correlated_exposure_ratio=0.0,
        )
        trigger._risk_engine.record_trade_pnl(-2_100.0)  # noqa: SLF001
        decision = await trigger.evaluate(
            market_price=0.45,
            aggregation_decision=_build_aggregation(),
            market_context={
                "expected_value": 0.12,
                "liquidity_usd": 50_000.0,
                "spread": 0.01,
                "best_bid": 0.445,
                "best_ask": 0.455,
            },
        )
        snapshot = await trigger._engine.snapshot()  # noqa: SLF001
        assert decision == "BLOCKED"
        assert trigger._risk_engine.get_state().global_trade_block is True  # noqa: SLF001
        assert len(snapshot.positions) == 0

    asyncio.run(_run())
