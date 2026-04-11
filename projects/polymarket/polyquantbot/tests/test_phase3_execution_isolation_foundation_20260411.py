from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

from projects.polymarket.polyquantbot.execution.engine import ExecutionEngine
from projects.polymarket.polyquantbot.execution.models import Position
from projects.polymarket.polyquantbot.execution.strategy_trigger import (
    StrategyAggregationDecision,
    StrategyCandidateScore,
    StrategyConfig,
    StrategyTrigger,
)


def _build_aggregation() -> StrategyAggregationDecision:
    candidate = StrategyCandidateScore(
        strategy_name="S1",
        decision="ENTER",
        reason="test_signal",
        edge=0.06,
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


def _build_trigger() -> StrategyTrigger:
    state_file = Path(tempfile.mkstemp(suffix="_phase3_execution_isolation_risk_state.json")[1])
    _seed_risk_state_file(state_file)
    trigger = StrategyTrigger(
        engine=ExecutionEngine(starting_equity=10_000.0),
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


def _market_context() -> dict[str, Any]:
    return {
        "expected_value": 0.10,
        "liquidity_usd": 50_000.0,
        "spread": 0.01,
        "best_bid": 0.445,
        "best_ask": 0.455,
    }


def test_manual_trade_open_source_is_distinct_from_autonomous_source() -> None:
    async def _run() -> None:
        trigger = _build_trigger()
        captured_contexts: list[dict[str, Any]] = []

        async def _open_position_spy(**kwargs: Any) -> Position:
            captured_contexts.append(dict(kwargs.get("position_context") or {}))
            return Position(
                market_id="MARKET-1",
                market_title="Test Market",
                side="YES",
                entry_price=0.45,
                current_price=0.45,
                size=100.0,
                position_id=str(kwargs.get("position_id", "manual-id")),
            )

        trigger._engine.open_position = _open_position_spy  # type: ignore[assignment] # noqa: SLF001

        manual_result = await trigger.evaluate(
            market_price=0.45,
            aggregation_decision=_build_aggregation(),
            market_context=_market_context(),
            open_source="execution.command_handler.trade_open.manual",
        )

        assert manual_result == "OPENED"
        assert captured_contexts[0]["open_source"] == "execution.command_handler.trade_open.manual"

    asyncio.run(_run())


def test_autonomous_open_source_remains_strategy_trigger_default() -> None:
    async def _run() -> None:
        trigger = _build_trigger()
        captured_contexts: list[dict[str, Any]] = []

        async def _open_position_spy(**kwargs: Any) -> Position:
            captured_contexts.append(dict(kwargs.get("position_context") or {}))
            return Position(
                market_id="MARKET-1",
                market_title="Test Market",
                side="YES",
                entry_price=0.45,
                current_price=0.45,
                size=100.0,
                position_id=str(kwargs.get("position_id", "auto-id")),
            )

        trigger._engine.open_position = _open_position_spy  # type: ignore[assignment] # noqa: SLF001

        autonomous_result = await trigger.evaluate(
            market_price=0.45,
            aggregation_decision=_build_aggregation(),
            market_context=_market_context(),
        )

        assert autonomous_result == "OPENED"
        assert captured_contexts[0]["open_source"] == "execution.strategy_trigger.autonomous"

    asyncio.run(_run())


def test_blocked_open_rejection_payload_schema_stays_flat() -> None:
    async def _run() -> None:
        trigger = _build_trigger()

        async def _reject_open(**_kwargs: Any) -> None:
            return None

        trigger._engine.open_position = _reject_open  # type: ignore[assignment] # noqa: SLF001
        trigger._engine.get_last_open_rejection = lambda: {  # type: ignore[assignment] # noqa: SLF001
            "execution_rejection": {
                "reason": "max_position_size_exceeded",
                "position_size": 1500.0,
            },
        }

        result = await trigger.evaluate(
            market_price=0.45,
            aggregation_decision=_build_aggregation(),
            market_context=_market_context(),
        )

        assert result == "BLOCKED"
        trace = next(iter(trigger._trade_traceability.values()))  # noqa: SLF001
        rejection_payload = trace["outcome_data"]["execution_rejection"]
        assert rejection_payload["reason"] == "max_position_size_exceeded"
        assert "execution_rejection" not in rejection_payload

    asyncio.run(_run())
