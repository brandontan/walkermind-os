from __future__ import annotations

import asyncio
import json
from pathlib import Path
import tempfile

from projects.polymarket.polyquantbot.core.risk.risk_engine import RiskEngine
from projects.polymarket.polyquantbot.execution.engine import ExecutionEngine
from projects.polymarket.polyquantbot.execution.strategy_trigger import (
    EntryExecutionReadiness,
    PortfolioExposureDecision,
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


def _build_trigger(
    *,
    state_file: Path,
    starting_equity: float = 10_000.0,
) -> StrategyTrigger:
    trigger = StrategyTrigger(
        engine=ExecutionEngine(starting_equity=starting_equity),
        config=StrategyConfig(market_id="MARKET-1", threshold=0.60, target_pnl=2.0),
    )
    trigger._risk_engine = RiskEngine(state_file=str(state_file))  # noqa: SLF001
    trigger._cooldown_seconds = 0.0  # noqa: SLF001
    trigger._intelligence.evaluate_entry = lambda _snapshot: {"score": 1.0, "reasons": ["test"]}  # type: ignore[assignment] # noqa: SLF001
    return trigger


def _latest_trade_id(trigger: StrategyTrigger) -> str:
    keys = list(trigger._trade_traceability.keys())  # noqa: SLF001
    return keys[-1]


def _default_market_context() -> dict[str, float]:
    return {
        "expected_value": 0.10,
        "liquidity_usd": 50_000.0,
        "spread": 0.01,
        "best_bid": 0.445,
        "best_ask": 0.455,
        "signal_reference_price": 0.45,
    }


def test_p16_pre_trade_block_when_ev_non_positive_records_terminal_trace() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            trigger = _build_trigger(state_file=Path(tmpdir) / "risk_state.json")
            context = _default_market_context()
            context["expected_value"] = 0.0
            decision = await trigger.evaluate(
                market_price=0.45,
                aggregation_decision=_build_aggregation(),
                market_context=context,
            )
            snapshot = await trigger._engine.snapshot()  # noqa: SLF001
            trade_id = _latest_trade_id(trigger)
            trace = trigger.get_trade_trace(trade_id)
            assert decision == "BLOCKED"
            assert len(snapshot.positions) == 0
            assert trace["outcome_data"]["terminal"] is True
            assert trace["outcome_data"]["status"] == "BLOCKED"
            assert trace["outcome_data"]["reason"].startswith("pre_trade_validator:")

    asyncio.run(_run())


def test_p16_successful_trade_records_execution_trace_regression() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            trigger = _build_trigger(state_file=Path(tmpdir) / "risk_state.json")
            decision = await trigger.evaluate(
                market_price=0.45,
                aggregation_decision=_build_aggregation(),
                market_context=_default_market_context(),
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


def test_p16_restart_persistence_keeps_global_block_active() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        state_path = Path(tmpdir) / "risk_state.json"
        first = RiskEngine(state_file=str(state_path))
        first.update_from_snapshot(
            equity=9_100.0,
            realized_pnl=-2_100.0,
            open_trades=0,
            correlated_exposure_ratio=0.0,
        )
        first.record_trade_pnl(-2_100.0)
        assert first.get_state().global_trade_block is True

        second = RiskEngine(state_file=str(state_path))
        restored = second.get_state()
        assert restored.global_trade_block is True


def test_p16_restart_missing_state_file_fails_safe() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        state_path = Path(tmpdir) / "risk_state.json"
        bootstrap = RiskEngine(state_file=str(state_path))
        bootstrap.update_from_snapshot(
            equity=10_000.0,
            realized_pnl=0.0,
            open_trades=0,
            correlated_exposure_ratio=0.0,
        )
        state_path.unlink()
        restarted = RiskEngine(state_file=str(state_path))
        state = restarted.get_state()
        assert state.global_trade_block is True
        assert restarted.as_dict().get("persistence_block_reason") == "risk_state_missing_on_startup"


def test_p16_restart_corrupt_state_file_fails_safe() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        state_path = Path(tmpdir) / "risk_state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text("{not-valid-json", encoding="utf-8")
        marker = state_path.with_suffix(".json.initialized")
        marker.write_text("initialized\n", encoding="utf-8")
        restarted = RiskEngine(state_file=str(state_path))
        state = restarted.get_state()
        assert state.global_trade_block is True
        assert restarted.as_dict().get("persistence_block_reason") == "risk_state_unreadable_on_startup"


def test_p16_blocked_traceability_portfolio_guard_block() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            trigger = _build_trigger(state_file=Path(tmpdir) / "risk_state.json")
            trigger.evaluate_portfolio_exposure_and_correlation = (  # type: ignore[assignment]
                lambda **_: PortfolioExposureDecision(
                    final_decision="SKIP",
                    adjusted_size=0.0,
                    reason="same_market_conflict",
                    flags=("same_market",),
                )
            )
            decision = await trigger.evaluate(
                market_price=0.45,
                aggregation_decision=_build_aggregation(),
                market_context=_default_market_context(),
            )
            trace = trigger.get_trade_trace(_latest_trade_id(trigger))
            assert decision == "BLOCKED"
            assert trace["outcome_data"]["reason"].startswith("portfolio_guard:")

    asyncio.run(_run())


def test_p16_blocked_traceability_timing_gate_block() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            trigger = _build_trigger(state_file=Path(tmpdir) / "risk_state.json")
            trigger.evaluate_entry_execution_readiness = (  # type: ignore[assignment]
                lambda **_: EntryExecutionReadiness(
                    timing_decision="SKIP",
                    timing_reason="anti_chase_timeout_skip",
                    reference_price=0.45,
                    reevaluation_window=10,
                    final_execution_readiness=False,
                    execution_quality_decision="NOT_EVALUATED",
                    execution_quality_reason="timing_gate_blocked",
                    adjusted_size=0.0,
                    expected_fill_price=0.45,
                    expected_slippage=0.0,
                )
            )
            decision = await trigger.evaluate(
                market_price=0.45,
                aggregation_decision=_build_aggregation(),
                market_context=_default_market_context(),
            )
            trace = trigger.get_trade_trace(_latest_trade_id(trigger))
            assert decision == "BLOCKED"
            assert trace["outcome_data"]["reason"].startswith("timing_gate_skip:")

    asyncio.run(_run())


def test_p16_blocked_traceability_execution_quality_block() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            trigger = _build_trigger(state_file=Path(tmpdir) / "risk_state.json")
            trigger.evaluate_entry_execution_readiness = (  # type: ignore[assignment]
                lambda **_: EntryExecutionReadiness(
                    timing_decision="ENTER_NOW",
                    timing_reason="stable_entry_window",
                    reference_price=0.45,
                    reevaluation_window=10,
                    final_execution_readiness=False,
                    execution_quality_decision="SKIP",
                    execution_quality_reason="slippage_too_high",
                    adjusted_size=100.0,
                    expected_fill_price=0.46,
                    expected_slippage=0.05,
                )
            )
            decision = await trigger.evaluate(
                market_price=0.45,
                aggregation_decision=_build_aggregation(),
                market_context=_default_market_context(),
            )
            trace = trigger.get_trade_trace(_latest_trade_id(trigger))
            assert decision == "BLOCKED"
            assert trace["outcome_data"]["reason"].startswith("execution_quality_gate:")

    asyncio.run(_run())


def test_p16_blocked_traceability_execution_engine_failure() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            trigger = _build_trigger(state_file=Path(tmpdir) / "risk_state.json")
            async def _fail_open_position(**_: object) -> None:
                return None

            trigger._engine.open_position = _fail_open_position  # type: ignore[assignment] # noqa: SLF001
            decision = await trigger.evaluate(
                market_price=0.45,
                aggregation_decision=_build_aggregation(),
                market_context=_default_market_context(),
            )
            trace = trigger.get_trade_trace(_latest_trade_id(trigger))
            assert decision == "BLOCKED"
            assert trace["outcome_data"]["reason"] == "execution_engine_open_rejected_or_failed"
            assert trace["execution_data"]["expected_price"] is not None
            assert trace["execution_data"].get("actual_fill_price") is None

    asyncio.run(_run())


def test_p16_terminal_outcome_is_unique_for_single_attempt() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            trigger = _build_trigger(state_file=Path(tmpdir) / "risk_state.json")
            trigger.evaluate_portfolio_exposure_and_correlation = (  # type: ignore[assignment]
                lambda **_: PortfolioExposureDecision(
                    final_decision="SKIP",
                    adjusted_size=0.0,
                    reason="same_market_conflict",
                    flags=("same_market",),
                )
            )
            _ = await trigger.evaluate(
                market_price=0.45,
                aggregation_decision=_build_aggregation(),
                market_context=_default_market_context(),
            )
            trace = trigger.get_trade_trace(_latest_trade_id(trigger))
            assert trace["outcome_data"]["terminal"] is True
            assert set(trace["outcome_data"].keys()) == {"terminal", "status", "reason"}

    asyncio.run(_run())


def test_p16_daily_loss_persistence_restores_current_day_state() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        state_path = Path(tmpdir) / "risk_state.json"
        initial = RiskEngine(state_file=str(state_path))
        initial.update_from_snapshot(
            equity=10_000.0,
            realized_pnl=0.0,
            open_trades=0,
            correlated_exposure_ratio=0.0,
        )
        initial.record_trade_pnl(-500.0)
        initial.record_trade_pnl(-600.0)

        restarted = RiskEngine(state_file=str(state_path))
        assert restarted.get_state().daily_loss == -1_100.0


def test_p16_drawdown_persistence_restores_peak_reference() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        state_path = Path(tmpdir) / "risk_state.json"
        initial = RiskEngine(state_file=str(state_path))
        initial.update_from_snapshot(
            equity=10_000.0,
            realized_pnl=0.0,
            open_trades=0,
            correlated_exposure_ratio=0.0,
        )
        initial.update_from_snapshot(
            equity=9_100.0,
            realized_pnl=-900.0,
            open_trades=0,
            correlated_exposure_ratio=0.0,
        )
        first_drawdown = initial.get_state().drawdown_ratio
        assert first_drawdown > 0.08

        restarted = RiskEngine(state_file=str(state_path))
        assert restarted.get_state().drawdown_ratio == first_drawdown


def test_p16_risk_state_file_has_minimum_authoritative_fields() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        state_path = Path(tmpdir) / "risk_state.json"
        risk_engine = RiskEngine(state_file=str(state_path))
        risk_engine.update_from_snapshot(
            equity=9_500.0,
            realized_pnl=-500.0,
            open_trades=1,
            correlated_exposure_ratio=0.2,
        )
        risk_engine.record_trade_pnl(-400.0)

        payload = json.loads(state_path.read_text(encoding="utf-8"))
        assert "peak_equity" in payload
        assert "daily_pnl_by_day" in payload
        assert "global_trade_block" in payload
