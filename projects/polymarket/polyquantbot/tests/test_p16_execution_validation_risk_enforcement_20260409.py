from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path

from projects.polymarket.polyquantbot.execution.engine import ExecutionEngine, ExecutionValidationProof
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


def _seed_risk_state_file(path: Path) -> None:
    path.write_text(
        (
            '{"correlated_exposure_ratio":0.0,'
            '"daily_pnl_by_day":{},'
            '"drawdown_ratio":0.0,'
            '"equity":10000.0,'
            '"global_trade_block":false,'
            '"open_trades":0,'
            '"peak_equity":10000.0,'
            '"portfolio_pnl":0.0,'
            '"version":1}'
        ),
        encoding="utf-8",
    )


def _build_trigger(
    starting_equity: float = 10_000.0,
    risk_state_path: str | None = None,
) -> StrategyTrigger:
    state_file = Path(risk_state_path) if risk_state_path else Path(tempfile.mkstemp(suffix="_p16_risk_state.json")[1])
    if not state_file.exists() or state_file.stat().st_size == 0:
        _seed_risk_state_file(state_file)
    trigger = StrategyTrigger(
        engine=ExecutionEngine(starting_equity=starting_equity),
        config=StrategyConfig(
            market_id="MARKET-1",
            threshold=0.60,
            target_pnl=2.0,
            risk_state_persistence_path=str(state_file),
        ),
    )
    trigger._cooldown_seconds = 0.0  # noqa: SLF001
    trigger._intelligence.evaluate_entry = lambda _snapshot: {"score": 1.0, "reasons": ["test"]}  # type: ignore[assignment] # noqa: SLF001
    return trigger


def _build_gateway_validation_proof(
    engine: ExecutionEngine,
    *,
    market: str,
    side: str,
    price: float,
    size: float,
) -> ExecutionValidationProof:
    return engine.build_validation_proof(
        condition_id=market,
        side=side,
        price_snapshot=price,
        size=size,
        market_type="normal",
    )


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


def test_p16_restart_safe_hard_block_persists_after_restart() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "risk_state.json"
            _seed_risk_state_file(state_path)
            trigger = _build_trigger(risk_state_path=str(state_path))
            trigger._risk_engine.update_from_snapshot(  # noqa: SLF001
                equity=9_100.0,
                realized_pnl=-2_100.0,
                open_trades=0,
                correlated_exposure_ratio=0.0,
            )
            trigger._risk_engine.record_trade_pnl(-2_100.0)  # noqa: SLF001
            restarted = _build_trigger(risk_state_path=str(state_path))
            decision = await restarted.evaluate(
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
            assert decision == "BLOCKED"
            assert restarted._risk_engine.get_state().global_trade_block is True  # noqa: SLF001

    asyncio.run(_run())


def test_p16_missing_corrupt_or_invalid_risk_state_fails_closed_with_reason() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        missing_state_path = Path(temp_dir) / "missing.json"
        missing_trigger = StrategyTrigger(
            engine=ExecutionEngine(starting_equity=10_000.0),
            config=StrategyConfig(
                market_id="MARKET-1",
                threshold=0.60,
                target_pnl=2.0,
                risk_state_persistence_path=str(missing_state_path),
            ),
        )
        missing_trigger._cooldown_seconds = 0.0  # noqa: SLF001
        missing_trigger._intelligence.evaluate_entry = lambda _snapshot: {"score": 1.0, "reasons": ["test"]}  # type: ignore[assignment] # noqa: SLF001
        assert missing_trigger.get_risk_restore_status()["ready"] is False
        assert missing_trigger.get_risk_restore_status()["reason"] == "persistence_missing"
        decision_missing = asyncio.run(
            missing_trigger.evaluate(
                market_price=0.45,
                aggregation_decision=_build_aggregation(),
                market_context={"expected_value": 0.10, "liquidity_usd": 50_000.0, "spread": 0.01, "best_bid": 0.445, "best_ask": 0.455},
            )
        )
        assert decision_missing == "BLOCKED"

        corrupt_state_path = Path(temp_dir) / "corrupt.json"
        corrupt_state_path.write_text("{not-json", encoding="utf-8")
        corrupt_trigger = StrategyTrigger(
            engine=ExecutionEngine(starting_equity=10_000.0),
            config=StrategyConfig(
                market_id="MARKET-1",
                threshold=0.60,
                target_pnl=2.0,
                risk_state_persistence_path=str(corrupt_state_path),
            ),
        )
        assert corrupt_trigger.get_risk_restore_status()["ready"] is False
        assert corrupt_trigger.get_risk_restore_status()["reason"] == "persistence_corrupt_json"

        invalid_state_path = Path(temp_dir) / "invalid.json"
        invalid_state_path.write_text('{"version":1,"equity":10000}', encoding="utf-8")
        invalid_trigger = StrategyTrigger(
            engine=ExecutionEngine(starting_equity=10_000.0),
            config=StrategyConfig(
                market_id="MARKET-1",
                threshold=0.60,
                target_pnl=2.0,
                risk_state_persistence_path=str(invalid_state_path),
            ),
        )
        assert invalid_trigger.get_risk_restore_status()["ready"] is False
        assert invalid_trigger.get_risk_restore_status()["reason"] == "persistence_invalid_structure"


def test_p16_blocked_terminal_traceability_has_single_terminal_trace_per_path() -> None:
    async def _run() -> None:
        pre_trade_trigger = _build_trigger()
        decision = await pre_trade_trigger.evaluate(
            market_price=0.45,
            aggregation_decision=_build_aggregation(),
            market_context={"expected_value": 0.0, "liquidity_usd": 20_000.0, "spread": 0.01, "best_bid": 0.44, "best_ask": 0.46},
        )
        assert decision == "BLOCKED"
        pre_trade_traces = [
            trace for trace in pre_trade_trigger._trade_traceability.values()  # noqa: SLF001
            if trace.get("outcome_data", {}).get("terminal_stage") == "pre_trade_validator_block"
        ]
        assert len(pre_trade_traces) == 1

        portfolio_trigger = _build_trigger()
        await portfolio_trigger._engine.open_position(  # noqa: SLF001
            market="MARKET-ALT",
            market_title="Alt",
            side="YES",
            price=0.5,
            size=100.0,
            validation_proof=_build_gateway_validation_proof(
                portfolio_trigger._engine,  # noqa: SLF001
                market="MARKET-ALT",
                side="YES",
                price=0.5,
                size=100.0,
            ),
        )
        decision = await portfolio_trigger.evaluate(
            market_price=0.45,
            aggregation_decision=StrategyAggregationDecision(
                selected_trade="S1",
                ranked_candidates=[
                    StrategyCandidateScore(
                        strategy_name="S1",
                        decision="ENTER",
                        reason="portfolio_guard_test",
                        edge=0.05,
                        confidence=0.9,
                        score=0.95,
                        market_metadata={"market_id": "MARKET-ALT", "title": "Alt Market"},
                    )
                ],
                selection_reason="portfolio_guard_test",
                top_score=0.95,
                decision="ENTER",
            ),
            market_context={"expected_value": 0.10, "liquidity_usd": 50_000.0, "spread": 0.01, "best_bid": 0.445, "best_ask": 0.455},
        )
        assert decision == "BLOCKED"
        portfolio_traces = [
            trace for trace in portfolio_trigger._trade_traceability.values()  # noqa: SLF001
            if trace.get("outcome_data", {}).get("terminal_stage") == "portfolio_guard_block"
        ]
        assert len(portfolio_traces) == 1

        timing_trigger = _build_trigger()
        decision = await timing_trigger.evaluate(
            market_price=0.45,
            aggregation_decision=_build_aggregation(edge=0.06),
            market_context={
                "expected_value": 0.10,
                "liquidity_usd": 50_000.0,
                "spread": 0.01,
                "best_bid": 0.445,
                "best_ask": 0.455,
                "timing_wait_cycles": 3,
                "signal_reference_price": 0.40,
            },
        )
        assert decision == "BLOCKED"
        timing_traces = [
            trace for trace in timing_trigger._trade_traceability.values()  # noqa: SLF001
            if trace.get("outcome_data", {}).get("terminal_stage") == "timing_gate_block"
        ]
        assert len(timing_traces) == 1

        quality_trigger = _build_trigger()
        decision = await quality_trigger.evaluate(
            market_price=0.45,
            aggregation_decision=_build_aggregation(edge=0.06),
            market_context={
                "expected_value": 0.10,
                "liquidity_usd": 50_000.0,
                "spread": 0.01,
                "best_bid": 0.40,
                "best_ask": 0.50,
            },
        )
        assert decision == "BLOCKED"
        quality_traces = [
            trace for trace in quality_trigger._trade_traceability.values()  # noqa: SLF001
            if trace.get("outcome_data", {}).get("terminal_stage") == "execution_quality_gate_block"
        ]
        assert len(quality_traces) == 1

        engine_reject_trigger = _build_trigger()
        original_open_position = engine_reject_trigger._engine.open_position  # noqa: SLF001

        async def _reject_open(**_kwargs: object) -> None:
            return None

        engine_reject_trigger._engine.open_position = _reject_open  # type: ignore[assignment] # noqa: SLF001
        decision = await engine_reject_trigger.evaluate(
            market_price=0.45,
            aggregation_decision=_build_aggregation(edge=0.06),
            market_context={"expected_value": 0.10, "liquidity_usd": 50_000.0, "spread": 0.01, "best_bid": 0.445, "best_ask": 0.455},
        )
        engine_reject_trigger._engine.open_position = original_open_position  # type: ignore[assignment] # noqa: SLF001
        assert decision == "BLOCKED"
        engine_traces = [
            trace for trace in engine_reject_trigger._trade_traceability.values()  # noqa: SLF001
            if trace.get("outcome_data", {}).get("terminal_stage") == "execution_engine_rejected_open"
        ]
        assert len(engine_traces) == 1

    asyncio.run(_run())


def test_p16_trade_intent_persistence_false_blocks_before_proof_and_open() -> None:
    class _FailFalseWriter:
        async def write(self, **_: object) -> bool:
            return False

    async def _run() -> None:
        trigger = _build_trigger()
        trigger._trade_intent_writer = _FailFalseWriter()  # noqa: SLF001
        proof_calls = 0
        open_calls = 0
        original_build = trigger._engine.build_validation_proof  # noqa: SLF001
        original_open = trigger._engine.open_position  # noqa: SLF001

        def _counted_build(*args: object, **kwargs: object):
            nonlocal proof_calls
            proof_calls += 1
            return original_build(*args, **kwargs)

        async def _counted_open(*args: object, **kwargs: object):
            nonlocal open_calls
            open_calls += 1
            return await original_open(*args, **kwargs)

        trigger._engine.build_validation_proof = _counted_build  # type: ignore[assignment] # noqa: SLF001
        trigger._engine.open_position = _counted_open  # type: ignore[assignment] # noqa: SLF001
        decision = await trigger.evaluate(
            market_price=0.45,
            aggregation_decision=_build_aggregation(),
            market_context={
                "expected_value": 0.12,
                "liquidity_usd": 50_000.0,
                "spread": 0.01,
                "best_bid": 0.445,
                "best_ask": 0.455,
                "timestamp": time.time(),
                "model_probability": 0.62,
                "orderbook": {"bids": [[0.44, 10_000.0]], "asks": [[0.46, 10_000.0]]},
            },
        )
        assert decision == "BLOCKED"
        assert proof_calls == 0
        assert open_calls == 0
        trace = next(iter(trigger._trade_traceability.values()))  # noqa: SLF001
        assert trace["outcome_data"]["reason"] == "trade_intent_persistence_failed"

    asyncio.run(_run())


def test_p16_trade_intent_persistence_exception_blocks_before_proof_and_open() -> None:
    class _RaiseWriter:
        async def write(self, **_: object) -> bool:
            raise RuntimeError("db down")

    async def _run() -> None:
        trigger = _build_trigger()
        trigger._trade_intent_writer = _RaiseWriter()  # noqa: SLF001
        proof_calls = 0
        open_calls = 0
        original_build = trigger._engine.build_validation_proof  # noqa: SLF001
        original_open = trigger._engine.open_position  # noqa: SLF001

        def _counted_build(*args: object, **kwargs: object):
            nonlocal proof_calls
            proof_calls += 1
            return original_build(*args, **kwargs)

        async def _counted_open(*args: object, **kwargs: object):
            nonlocal open_calls
            open_calls += 1
            return await original_open(*args, **kwargs)

        trigger._engine.build_validation_proof = _counted_build  # type: ignore[assignment] # noqa: SLF001
        trigger._engine.open_position = _counted_open  # type: ignore[assignment] # noqa: SLF001
        decision = await trigger.evaluate(
            market_price=0.45,
            aggregation_decision=_build_aggregation(),
            market_context={
                "expected_value": 0.12,
                "liquidity_usd": 50_000.0,
                "spread": 0.01,
                "best_bid": 0.445,
                "best_ask": 0.455,
                "timestamp": time.time(),
                "model_probability": 0.62,
                "orderbook": {"bids": [[0.44, 10_000.0]], "asks": [[0.46, 10_000.0]]},
            },
        )
        assert decision == "BLOCKED"
        assert proof_calls == 0
        assert open_calls == 0
        trace = next(iter(trigger._trade_traceability.values()))  # noqa: SLF001
        assert trace["outcome_data"]["reason"] == "trade_intent_persistence_failed"

    asyncio.run(_run())


def test_p16_trade_intent_persistence_success_keeps_normal_path() -> None:
    class _SuccessWriter:
        async def write(self, **_: object) -> bool:
            return True

    async def _run() -> None:
        trigger = _build_trigger()
        trigger._trade_intent_writer = _SuccessWriter()  # noqa: SLF001
        proof_calls = 0
        open_calls = 0
        original_build = trigger._engine.build_validation_proof  # noqa: SLF001
        original_open = trigger._engine.open_position  # noqa: SLF001

        def _counted_build(*args: object, **kwargs: object):
            nonlocal proof_calls
            proof_calls += 1
            return original_build(*args, **kwargs)

        async def _counted_open(*args: object, **kwargs: object):
            nonlocal open_calls
            open_calls += 1
            return await original_open(*args, **kwargs)

        trigger._engine.build_validation_proof = _counted_build  # type: ignore[assignment] # noqa: SLF001
        trigger._engine.open_position = _counted_open  # type: ignore[assignment] # noqa: SLF001
        decision = await trigger.evaluate(
            market_price=0.45,
            aggregation_decision=_build_aggregation(),
            market_context={
                "expected_value": 0.12,
                "liquidity_usd": 50_000.0,
                "spread": 0.01,
                "best_bid": 0.445,
                "best_ask": 0.455,
                "timestamp": time.time(),
                "model_probability": 0.62,
                "orderbook": {"bids": [[0.44, 10_000.0]], "asks": [[0.46, 10_000.0]]},
            },
        )
        assert decision == "OPENED"
        assert proof_calls == 1
        assert open_calls == 1

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


def test_p16_direct_engine_call_without_validation_proof_fails() -> None:
    async def _run() -> None:
        engine = ExecutionEngine(starting_equity=10_000.0)
        created = await engine.open_position(
            market="MARKET-1",
            market_title="Test Market",
            side="YES",
            price=0.45,
            size=100.0,
        )
        assert created is None

    asyncio.run(_run())


def test_p16_direct_engine_call_with_fake_validation_proof_fails() -> None:
    async def _run() -> None:
        engine = ExecutionEngine(starting_equity=10_000.0)
        fake = ExecutionValidationProof(
            proof_id="fake-trade",
            condition_id="MARKET-1",
            side="YES",
            price_snapshot=0.45,
            size=100.0,
            created_at=1.0,
            ttl_seconds=20,
            expires_at=21.0,
            context_hash="0" * 64,
            status="CREATED",
        )
        created = await engine.open_position(
            market="MARKET-1",
            market_title="Test Market",
            side="YES",
            price=0.45,
            size=100.0,
            validation_proof=fake,
        )
        assert created is None

    asyncio.run(_run())


def test_p16_direct_engine_call_with_gateway_validation_proof_passes() -> None:
    async def _run() -> None:
        engine = ExecutionEngine(starting_equity=10_000.0)
        created = await engine.open_position(
            market="MARKET-1",
            market_title="Test Market",
            side="YES",
            price=0.45,
            size=100.0,
            validation_proof=_build_gateway_validation_proof(engine, market="MARKET-1", side="YES", price=0.45, size=100.0),
        )
        assert created is not None

    asyncio.run(_run())


def test_p16_direct_engine_open_rejects_non_positive_size() -> None:
    async def _run() -> None:
        engine = ExecutionEngine(starting_equity=10_000.0)
        created = await engine.open_position(
            market="MARKET-1",
            market_title="Test Market",
            side="YES",
            price=0.45,
            size=0.0,
            validation_proof=_build_gateway_validation_proof(engine, market="MARKET-1", side="YES", price=0.45, size=0.0),
        )
        assert created is None
        rejection = engine.get_last_open_rejection()
        assert rejection is not None
        assert rejection["reason"] == "size_non_positive"

    asyncio.run(_run())


def test_p16_direct_engine_open_rejects_size_above_per_trade_cap() -> None:
    async def _run() -> None:
        engine = ExecutionEngine(starting_equity=10_000.0)
        created = await engine.open_position(
            market="MARKET-1",
            market_title="Test Market",
            side="YES",
            price=0.45,
            size=1_500.0,
            validation_proof=_build_gateway_validation_proof(engine, market="MARKET-1", side="YES", price=0.45, size=1_500.0),
        )
        assert created is None
        rejection = engine.get_last_open_rejection()
        assert rejection is not None
        assert rejection["reason"] == "max_position_size_exceeded"
        assert rejection["limit"] == 1_000.0

    asyncio.run(_run())


def test_p16_direct_engine_open_rejects_capital_risk_allowed_size_boundary() -> None:
    async def _run() -> None:
        engine = ExecutionEngine(starting_equity=10_000.0)
        engine.max_total_exposure_ratio = 0.15
        seed_created = await engine.open_position(
            market="MARKET-SEED",
            market_title="Seed Position",
            side="YES",
            price=0.40,
            size=1_000.0,
            validation_proof=_build_gateway_validation_proof(engine, market="MARKET-SEED", side="YES", price=0.40, size=1_000.0),
        )
        assert seed_created is not None
        created = await engine.open_position(
            market="MARKET-2",
            market_title="Test Market 2",
            side="YES",
            price=0.45,
            size=750.0,
            validation_proof=_build_gateway_validation_proof(engine, market="MARKET-2", side="YES", price=0.45, size=750.0),
        )
        assert created is None
        rejection = engine.get_last_open_rejection()
        assert rejection is not None
        assert rejection["reason"] == "capital_risk_allowed_size_exceeded"
        assert rejection["capital_risk_allowed_size"] == 500.0
        assert rejection["binding_constraint"] == "remaining_total_exposure"

    asyncio.run(_run())


def test_p16_strategy_trigger_records_execution_rejection_reason_for_sizing_block() -> None:
    async def _run() -> None:
        trigger = _build_trigger()
        trigger._engine.max_position_size_ratio = 0.01  # noqa: SLF001
        decision = await trigger.evaluate(
            market_price=0.45,
            aggregation_decision=_build_aggregation(edge=0.06),
            market_context={
                "expected_value": 0.10,
                "liquidity_usd": 50_000.0,
                "spread": 0.01,
                "best_bid": 0.445,
                "best_ask": 0.455,
            },
        )
        assert decision == "BLOCKED"
        trace = next(
            (
                record
                for record in trigger._trade_traceability.values()  # noqa: SLF001
                if record.get("outcome_data", {}).get("terminal_stage") == "execution_engine_rejected_open"
            ),
            None,
        )
        assert trace is not None
        assert trace["outcome_data"]["reason"] == "max_position_size_exceeded"
        assert trace["outcome_data"]["execution_rejection"]["reason"] == "max_position_size_exceeded"

    asyncio.run(_run())
