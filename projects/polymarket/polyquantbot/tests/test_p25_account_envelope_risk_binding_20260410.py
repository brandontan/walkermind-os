from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path

from projects.polymarket.polyquantbot.execution.engine import ExecutionEngine
from projects.polymarket.polyquantbot.execution.strategy_trigger import (
    AccountEnvelope,
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


def _build_trigger(*, risk_state_path: str | None = None) -> StrategyTrigger:
    state_file = Path(risk_state_path) if risk_state_path else Path(tempfile.mkstemp(suffix="_p25_risk_state.json")[1])
    if not state_file.exists() or state_file.stat().st_size == 0:
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


def _aggregation() -> StrategyAggregationDecision:
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


def _market_context() -> dict[str, float]:
    return {
        "expected_value": 0.15,
        "liquidity_usd": 50_000.0,
        "spread": 0.01,
        "best_bid": 0.445,
        "best_ask": 0.455,
        "timestamp": float(time.time()),
        "model_probability": 0.60,
        "orderbook": {
            "bids": [[0.44, 15_000.0]],
            "asks": [[0.46, 15_000.0]],
        },
    }


def test_bound_risk_profile_empty_config_is_valid() -> None:
    async def _run() -> None:
        trigger = _build_trigger()
        decision = await trigger.evaluate(
            market_price=0.45,
            aggregation_decision=_aggregation(),
            market_context=_market_context(),
            account_envelope=AccountEnvelope(
                account_id="acct-1",
                risk_profile_present=True,
                risk_profile_config={},
            ),
        )
        assert decision == "OPENED"

    asyncio.run(_run())


def test_bound_risk_profile_populated_config_is_valid() -> None:
    async def _run() -> None:
        trigger = _build_trigger()
        decision = await trigger.evaluate(
            market_price=0.45,
            aggregation_decision=_aggregation(),
            market_context=_market_context(),
            account_envelope=AccountEnvelope(
                account_id="acct-1",
                risk_profile_present=True,
                risk_profile_config={"level": "balanced", "max_position_ratio": 0.1},
            ),
        )
        assert decision == "OPENED"

    asyncio.run(_run())


def test_missing_risk_profile_binding_blocks_fail_closed() -> None:
    async def _run() -> None:
        trigger = _build_trigger()
        decision = await trigger.evaluate(
            market_price=0.45,
            aggregation_decision=_aggregation(),
            market_context=_market_context(),
            account_envelope=AccountEnvelope(
                account_id="acct-1",
                risk_profile_present=False,
                risk_profile_config={},
            ),
        )
        assert decision == "BLOCKED"
        traces = [
            trace
            for trace in trigger._trade_traceability.values()  # noqa: SLF001
            if trace.get("outcome_data", {}).get("terminal_stage") == "risk_profile_binding_block"
        ]
        assert len(traces) == 1
        assert traces[0]["outcome_data"]["reason"] == "risk_profile_binding_missing"

    asyncio.run(_run())


def test_regression_persistence_gate_still_blocks_before_binding() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        missing_state_path = Path(temp_dir) / "missing.json"
        trigger = StrategyTrigger(
            engine=ExecutionEngine(starting_equity=10_000.0),
            config=StrategyConfig(
                market_id="MARKET-1",
                threshold=0.60,
                target_pnl=2.0,
                risk_state_persistence_path=str(missing_state_path),
            ),
        )
        trigger._cooldown_seconds = 0.0  # noqa: SLF001
        trigger._intelligence.evaluate_entry = lambda _snapshot: {"score": 1.0, "reasons": ["test"]}  # type: ignore[assignment] # noqa: SLF001
        decision = asyncio.run(
            trigger.evaluate(
                market_price=0.45,
                aggregation_decision=_aggregation(),
                market_context=_market_context(),
                account_envelope=AccountEnvelope(
                    account_id="acct-1",
                    risk_profile_present=True,
                    risk_profile_config={},
                ),
            )
        )
        assert trigger.get_risk_restore_status()["ready"] is False
        assert decision == "BLOCKED"
