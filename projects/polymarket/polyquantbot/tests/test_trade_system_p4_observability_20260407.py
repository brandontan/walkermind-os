from __future__ import annotations

import asyncio

import pytest

from projects.polymarket.polyquantbot.core.execution import executor
from projects.polymarket.polyquantbot.core.execution.executor import TradeResult
from projects.polymarket.polyquantbot.core.signal.signal_engine import SignalResult
from projects.polymarket.polyquantbot.execution.event_logger import emit_event


@pytest.mark.parametrize(
    ("trace_id", "event_type", "component", "outcome"),
    [
        (None, "execution_attempt", "engine", "success"),
        ("", "execution_attempt", "engine", "success"),
        ("trace-1", None, "engine", "success"),
        ("trace-1", "", "engine", "success"),
        ("trace-1", "execution_attempt", None, "success"),
        ("trace-1", "execution_attempt", "", "success"),
        ("trace-1", "execution_attempt", "engine", None),
        ("trace-1", "execution_attempt", "engine", ""),
    ],
)
def test_emit_event_rejects_invalid_inputs(
    trace_id: str | None,
    event_type: str | None,
    component: str | None,
    outcome: str | None,
) -> None:
    with pytest.raises(ValueError):
        emit_event(trace_id, event_type, component, outcome)


def test_trace_id_flows_through_execution_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_events: list[dict[str, object]] = []

    def _capture_event(
        trace_id: str,
        event_type: str,
        component: str,
        outcome: str,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        event = {
            "trace_id": trace_id,
            "event_type": event_type,
            "component": component,
            "outcome": outcome,
            "payload": payload or {},
        }
        captured_events.append(event)
        return event

    async def _success_attempt(*args, **kwargs) -> TradeResult:
        signal: SignalResult = kwargs["signal"]
        trade_id: str = kwargs["trade_id"]
        return TradeResult(
            trade_id=trade_id,
            signal_id=signal.signal_id,
            market_id=signal.market_id,
            side=signal.side,
            success=True,
            mode="PAPER",
            attempted_size=signal.size_usd,
            filled_size_usd=signal.size_usd,
            fill_price=signal.p_market,
            reason="paper_simulated",
        )

    monkeypatch.setattr(executor, "emit_event", _capture_event)
    monkeypatch.setattr(executor, "_attempt_execution", _success_attempt)
    executor.reset_state()

    signal = SignalResult(
        signal_id="signal-1",
        market_id="market-1",
        side="YES",
        p_market=0.6,
        p_model=0.7,
        edge=0.1,
        ev=0.05,
        kelly_f=0.02,
        size_usd=50.0,
        liquidity_usd=20000.0,
    )

    trace_id = "trace-p4-lifecycle"
    result = asyncio.run(executor.execute_trade(signal, mode="PAPER", trace_id=trace_id))

    assert result.success is True
    assert captured_events
    assert all(event["trace_id"] == trace_id for event in captured_events)
    assert {event["event_type"] for event in captured_events} >= {
        "execution_attempt",
        "execution_result",
    }


def test_runtime_path_emits_structured_execution_events(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_events: list[dict[str, object]] = []

    def _capture_event(
        trace_id: str,
        event_type: str,
        component: str,
        outcome: str,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        event = {
            "trace_id": trace_id,
            "event_type": event_type,
            "component": component,
            "outcome": outcome,
            "payload": payload or {},
        }
        captured_events.append(event)
        return event

    async def _failing_attempt(*args, **kwargs) -> TradeResult:
        signal: SignalResult = kwargs["signal"]
        trade_id: str = kwargs["trade_id"]
        return TradeResult(
            trade_id=trade_id,
            signal_id=signal.signal_id,
            market_id=signal.market_id,
            side=signal.side,
            success=False,
            mode="PAPER",
            attempted_size=signal.size_usd,
            reason="simulated_failure",
        )

    monkeypatch.setattr(executor, "emit_event", _capture_event)
    monkeypatch.setattr(executor, "_attempt_execution", _failing_attempt)
    executor.reset_state()

    signal = SignalResult(
        signal_id="signal-2",
        market_id="market-2",
        side="NO",
        p_market=0.4,
        p_model=0.55,
        edge=0.15,
        ev=0.06,
        kelly_f=0.02,
        size_usd=40.0,
        liquidity_usd=20000.0,
    )

    result = asyncio.run(executor.execute_trade(signal, mode="PAPER", trace_id="trace-runtime"))

    assert result.success is False
    assert any(event["event_type"] == "execution_attempt" for event in captured_events)
    assert any(
        event["event_type"] == "execution_result" and event["outcome"] == "failure"
        for event in captured_events
    )
    assert all(event["component"] == "core.execution.executor" for event in captured_events)
