from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from projects.polymarket.polyquantbot.core.risk.pre_trade_validator import PreTradeValidator
from projects.polymarket.polyquantbot.core.risk.risk_engine import RiskEngine
from projects.polymarket.polyquantbot.execution.engine import ExecutionEngine
from projects.polymarket.polyquantbot.execution.gateway import ExecutionGateway
from projects.polymarket.polyquantbot.execution.strategy_trigger import (
    StrategyAggregationDecision,
    StrategyCandidateScore,
    StrategyConfig,
    StrategyTrigger,
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


def _build_aggregation() -> StrategyAggregationDecision:
    candidate = StrategyCandidateScore(
        strategy_name="S1",
        decision="ENTER",
        reason="test_signal",
        edge=0.05,
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


def test_p17_direct_execution_open_position_is_blocked() -> None:
    async def _run() -> None:
        engine = ExecutionEngine(starting_equity=10_000.0)
        try:
            await engine.open_position(
                market="MKT-DIRECT",
                market_title="Direct Call",
                side="YES",
                price=0.50,
                size=100.0,
            )
            raise AssertionError("Expected direct execution to fail.")
        except RuntimeError as exc:
            assert "execution_gateway_required_for_open_position" in str(exc)

    asyncio.run(_run())


def test_p17_execution_via_gateway_succeeds() -> None:
    async def _run() -> None:
        engine = ExecutionEngine(starting_equity=10_000.0)
        gateway = ExecutionGateway(
            engine=engine,
            pre_trade_validator=PreTradeValidator(),
            risk_engine=RiskEngine(),
        )
        result = await gateway.open_validated_position(
            market="MKT-GATEWAY",
            market_title="Gateway Call",
            side="YES",
            price=0.50,
            size=100.0,
            signal_data={"expected_value": 0.10, "edge": 0.05, "liquidity_usd": 20_000.0},
            decision_data={"position_size": 100.0, "target_market_id": "MKT-GATEWAY", "strategy_source": "S1"},
        )
        assert result.validation_decision == "ALLOW"
        assert result.position is not None

    asyncio.run(_run())


def test_p17_strategy_trigger_path_still_opens_via_gateway() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "risk_state.json"
            _seed_risk_state_file(state_path)
            trigger = StrategyTrigger(
                engine=ExecutionEngine(starting_equity=10_000.0),
                config=StrategyConfig(
                    market_id="MARKET-1",
                    threshold=0.60,
                    target_pnl=2.0,
                    risk_state_persistence_path=str(state_path),
                ),
            )
            trigger._cooldown_seconds = 0.0  # noqa: SLF001
            trigger._intelligence.evaluate_entry = lambda _snapshot: {"score": 1.0, "reasons": ["test"]}  # type: ignore[assignment] # noqa: SLF001
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

    asyncio.run(_run())
