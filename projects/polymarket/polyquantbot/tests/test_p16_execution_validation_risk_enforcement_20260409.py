from __future__ import annotations

import asyncio
from pathlib import Path

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


def _latest_terminal_trace(trigger: StrategyTrigger) -> dict[str, object]:
    traces = trigger._trade_traceability  # noqa: SLF001
    assert traces
    latest_key = next(reversed(traces))
    return trigger.get_trade_trace(latest_key)


def test_p16_pre_trade_block_when_ev_non_positive(tmp_path: Path) -> None:
    async def _run() -> None:
        state_file = tmp_path / "risk_block_state.json"
        trigger = _build_trigger()
        trigger._risk_engine._block_state_file = state_file  # noqa: SLF001
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


def test_p16_successful_trade_records_execution_trace(tmp_path: Path) -> None:
    async def _run() -> None:
        trigger = _build_trigger()
        trigger._risk_engine._block_state_file = tmp_path / "risk_block_state.json"  # noqa: SLF001
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
        assert trace["outcome_data"] == {}

    asyncio.run(_run())


def test_p16_risk_breach_triggers_global_block_restart_safe(tmp_path: Path) -> None:
    async def _run() -> None:
        state_file = tmp_path / "risk_block_state.json"
        trigger = _build_trigger(starting_equity=10_000.0)
        trigger._risk_engine._block_state_file = state_file  # noqa: SLF001
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

        restarted_trigger = _build_trigger(starting_equity=10_000.0)
        restarted_trigger._risk_engine = restarted_trigger._risk_engine.__class__(  # noqa: SLF001
            block_state_file=str(state_file)
        )
        restarted_decision = await restarted_trigger.evaluate(
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
        restarted_snapshot = await restarted_trigger._engine.snapshot()  # noqa: SLF001
        assert restarted_decision == "BLOCKED"
        assert restarted_trigger._risk_engine.get_state().global_trade_block is True  # noqa: SLF001
        assert len(restarted_snapshot.positions) == 0

    asyncio.run(_run())


def test_p16_terminal_trace_for_portfolio_guard_block(tmp_path: Path) -> None:
    async def _run() -> None:
        trigger = _build_trigger()
        trigger._risk_engine._block_state_file = tmp_path / "risk_block_state.json"  # noqa: SLF001
        trigger._engine.max_total_exposure_ratio = 0.0  # noqa: SLF001
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
        trace = _latest_terminal_trace(trigger)
        assert decision == "BLOCKED"
        assert trace["outcome_data"]["terminal_status"] == "BLOCKED"
        assert trace["outcome_data"]["terminal_reason"] == "portfolio_guard"

    asyncio.run(_run())


def test_p16_terminal_trace_for_timing_gate_hold(tmp_path: Path) -> None:
    async def _run() -> None:
        trigger = _build_trigger()
        trigger._risk_engine._block_state_file = tmp_path / "risk_block_state.json"  # noqa: SLF001
        decision = await trigger.evaluate(
            market_price=0.49,
            aggregation_decision=_build_aggregation(edge=0.06),
            market_context={
                "expected_value": 0.12,
                "liquidity_usd": 50_000.0,
                "spread": 0.01,
                "best_bid": 0.40,
                "best_ask": 0.60,
                "signal_reference_price": 0.40,
                "timing_wait_cycles": 0,
            },
        )
        trace = _latest_terminal_trace(trigger)
        assert decision == "HOLD"
        assert trace["outcome_data"]["terminal_status"] == "HOLD"
        assert trace["outcome_data"]["terminal_reason"] == "timing_gate"

    asyncio.run(_run())


def test_p16_terminal_trace_for_execution_quality_block(tmp_path: Path) -> None:
    async def _run() -> None:
        trigger = _build_trigger()
        trigger._risk_engine._block_state_file = tmp_path / "risk_block_state.json"  # noqa: SLF001
        decision = await trigger.evaluate(
            market_price=0.45,
            aggregation_decision=_build_aggregation(edge=0.05),
            market_context={
                "expected_value": 0.12,
                "liquidity_usd": 50_000.0,
                "spread": 0.01,
                "best_bid": 0.30,
                "best_ask": 0.70,
                "orderbook_depth_usd": 100_000.0,
                "signal_reference_price": 0.45,
                "timing_wait_cycles": 2,
            },
        )
        trace = _latest_terminal_trace(trigger)
        assert decision == "BLOCKED"
        assert trace["outcome_data"]["terminal_status"] == "BLOCKED"
        assert trace["outcome_data"]["terminal_reason"] == "execution_quality_gate"

    asyncio.run(_run())


def test_p16_terminal_trace_for_execution_engine_rejection(tmp_path: Path) -> None:
    async def _run() -> None:
        trigger = _build_trigger()
        trigger._risk_engine._block_state_file = tmp_path / "risk_block_state.json"  # noqa: SLF001
        async def _reject_open_position(**_: object) -> None:
            return None

        trigger._engine.open_position = _reject_open_position  # type: ignore[assignment] # noqa: SLF001
        decision = await trigger.evaluate(
            market_price=0.45,
            aggregation_decision=_build_aggregation(edge=0.05),
            market_context={
                "expected_value": 0.12,
                "liquidity_usd": 50_000.0,
                "spread": 0.01,
                "best_bid": 0.445,
                "best_ask": 0.455,
                "signal_reference_price": 0.45,
            },
        )
        trace = _latest_terminal_trace(trigger)
        assert decision == "BLOCKED"
        assert trace["outcome_data"]["terminal_status"] == "BLOCKED"
        assert trace["outcome_data"]["terminal_reason"] == "execution_engine_rejection"

    asyncio.run(_run())
