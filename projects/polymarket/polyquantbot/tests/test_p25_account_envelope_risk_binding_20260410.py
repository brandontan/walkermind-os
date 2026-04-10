from __future__ import annotations

import asyncio
from dataclasses import dataclass
import tempfile
import time
from pathlib import Path
from typing import Any

from projects.polymarket.polyquantbot.execution.engine import ExecutionEngine
from projects.polymarket.polyquantbot.execution.strategy_trigger import (
    AccountEnvelope,
    StrategyAggregationDecision,
    StrategyCandidateScore,
    StrategyConfig,
    StrategyTrigger,
)


@dataclass(frozen=True)
class _OpenedPosition:
    position_id: str
    entry_price: float


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


def _base_market_context() -> dict[str, float | dict[str, object] | str]:
    return {
        "expected_value": 0.10,
        "liquidity_usd": 50_000.0,
        "spread": 0.01,
        "best_bid": 0.445,
        "best_ask": 0.455,
        "timestamp": int(time.time()),
        "model_probability": 0.62,
        "orderbook": {"bid_depth_usd": 25_000.0, "ask_depth_usd": 25_000.0},
        "account_id": "acct-001",
        "risk_profile_binding": {},
    }


def _build_trigger(*, trade_intent_writer: Any, state_path: str) -> StrategyTrigger:
    trigger = StrategyTrigger(
        engine=ExecutionEngine(starting_equity=10_000.0),
        config=StrategyConfig(
            market_id="MARKET-1",
            threshold=0.60,
            target_pnl=2.0,
            risk_state_persistence_path=state_path,
        ),
        trade_intent_writer=trade_intent_writer,
    )
    trigger._cooldown_seconds = 0.0  # noqa: SLF001
    trigger._intelligence.evaluate_entry = lambda _snapshot: {"score": 1.0, "reasons": ["test"]}  # type: ignore[assignment] # noqa: SLF001
    return trigger


def test_trade_intent_persistence_false_blocks_before_proof_and_open() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "risk_state.json"
            _seed_risk_state_file(state_path)
            calls = {"proof": 0, "open": 0}
            persisted_payloads: list[dict[str, object]] = []

            def _writer(payload: dict[str, object]) -> bool:
                persisted_payloads.append(payload)
                return False

            trigger = _build_trigger(trade_intent_writer=_writer, state_path=str(state_path))

            original_build_proof = trigger._engine.build_validation_proof  # noqa: SLF001
            original_open = trigger._engine.open_position  # noqa: SLF001

            def _counted_build_proof(*args: Any, **kwargs: Any) -> Any:
                calls["proof"] += 1
                return original_build_proof(*args, **kwargs)

            async def _counted_open(*args: Any, **kwargs: Any) -> Any:
                calls["open"] += 1
                return await original_open(*args, **kwargs)

            trigger._engine.build_validation_proof = _counted_build_proof  # type: ignore[assignment] # noqa: SLF001
            trigger._engine.open_position = _counted_open  # type: ignore[assignment] # noqa: SLF001

            decision = await trigger.evaluate(
                market_price=0.45,
                aggregation_decision=_build_aggregation(),
                market_context=_base_market_context(),
            )

            assert decision == "BLOCKED"
            assert len(persisted_payloads) == 1
            assert calls["proof"] == 0
            assert calls["open"] == 0

    asyncio.run(_run())


def test_trade_intent_persistence_exception_blocks_before_proof_and_open() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "risk_state.json"
            _seed_risk_state_file(state_path)
            calls = {"proof": 0, "open": 0}

            def _writer(_payload: dict[str, object]) -> bool:
                raise RuntimeError("writer failed")

            trigger = _build_trigger(trade_intent_writer=_writer, state_path=str(state_path))

            original_build_proof = trigger._engine.build_validation_proof  # noqa: SLF001
            original_open = trigger._engine.open_position  # noqa: SLF001

            def _counted_build_proof(*args: Any, **kwargs: Any) -> Any:
                calls["proof"] += 1
                return original_build_proof(*args, **kwargs)

            async def _counted_open(*args: Any, **kwargs: Any) -> Any:
                calls["open"] += 1
                return await original_open(*args, **kwargs)

            trigger._engine.build_validation_proof = _counted_build_proof  # type: ignore[assignment] # noqa: SLF001
            trigger._engine.open_position = _counted_open  # type: ignore[assignment] # noqa: SLF001

            decision = await trigger.evaluate(
                market_price=0.45,
                aggregation_decision=_build_aggregation(),
                market_context=_base_market_context(),
            )

            assert decision == "BLOCKED"
            assert calls["proof"] == 0
            assert calls["open"] == 0

    asyncio.run(_run())


def test_trade_intent_persistence_success_keeps_normal_path() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "risk_state.json"
            _seed_risk_state_file(state_path)
            persisted_payloads: list[dict[str, object]] = []
            calls = {"proof": 0, "open": 0}

            def _writer(payload: dict[str, object]) -> bool:
                persisted_payloads.append(payload)
                return True

            trigger = _build_trigger(trade_intent_writer=_writer, state_path=str(state_path))
            original_build_proof = trigger._engine.build_validation_proof  # noqa: SLF001

            def _counted_build_proof(*args: Any, **kwargs: Any) -> Any:
                calls["proof"] += 1
                return original_build_proof(*args, **kwargs)

            async def _fake_open(*args: Any, **kwargs: Any) -> _OpenedPosition:
                calls["open"] += 1
                return _OpenedPosition(
                    position_id=str(kwargs.get("position_id", "trade-id")),
                    entry_price=float(kwargs.get("price", 0.45)),
                )

            trigger._engine.build_validation_proof = _counted_build_proof  # type: ignore[assignment] # noqa: SLF001
            trigger._engine.open_position = _fake_open  # type: ignore[assignment] # noqa: SLF001
            decision = await trigger.evaluate(
                market_price=0.45,
                aggregation_decision=_build_aggregation(),
                market_context=_base_market_context(),
            )

            assert decision == "OPENED"
            assert len(persisted_payloads) == 1
            assert calls["proof"] == 1
            assert calls["open"] == 1

    asyncio.run(_run())


def test_bound_risk_profile_empty_config_is_valid() -> None:
    envelope = AccountEnvelope(account_id="acct-1", risk_profile_present=True, risk_profile_binding={})
    assert envelope.risk_profile_present is True
    assert envelope.risk_profile_binding == {}


def test_missing_risk_profile_binding_blocks_fail_closed() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "risk_state.json"
            _seed_risk_state_file(state_path)
            writer_calls = {"count": 0}

            def _writer(_payload: dict[str, object]) -> bool:
                writer_calls["count"] += 1
                return True

            trigger = _build_trigger(trade_intent_writer=_writer, state_path=str(state_path))
            context = _base_market_context()
            context.pop("risk_profile_binding", None)

            decision = await trigger.evaluate(
                market_price=0.45,
                aggregation_decision=_build_aggregation(),
                market_context=context,
            )

            assert decision == "BLOCKED"
            assert writer_calls["count"] == 0
            traces = list(trigger._trade_traceability.values())  # noqa: SLF001
            assert traces
            assert traces[-1].get("outcome_data", {}).get("reason") == "risk_profile_binding_missing"

    asyncio.run(_run())
