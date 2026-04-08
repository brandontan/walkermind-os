from __future__ import annotations

import asyncio

from projects.polymarket.polyquantbot.telegram.command_handler import CommandHandler
from projects.polymarket.polyquantbot.execution import observability
from projects.polymarket.polyquantbot.execution.strategy_trigger import StrategyTrigger


class _DummyStateManager:
    async def pause(self, reason: str) -> None:
        _ = reason

    def snapshot(self) -> dict[str, str]:
        return {"state": "RUNNING"}


class _DummyConfigManager:
    def snapshot(self):
        class _Cfg:
            risk_multiplier = 0.25
            max_position = 0.10

        return _Cfg()


class _SpyLog:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def info(self, event: str, **kwargs) -> None:
        self.events.append(("info", event, kwargs))

    def warning(self, event: str, **kwargs) -> None:
        self.events.append(("warning", event, kwargs))

    def error(self, event: str, **kwargs) -> None:
        self.events.append(("error", event, kwargs))


def _build_handler() -> CommandHandler:
    return CommandHandler(
        state_manager=_DummyStateManager(),  # type: ignore[arg-type]
        config_manager=_DummyConfigManager(),  # type: ignore[arg-type]
    )


def _stage_names(events: list[tuple[str, str, dict]], trace_id: str) -> list[str]:
    return [
        payload["stage"]
        for level, event, payload in events
        if level == "info"
        and event == "execution_stage_trace"
        and payload.get("trace_id") == trace_id
    ]


def _outcomes(events: list[tuple[str, str, dict]], trace_id: str) -> list[str]:
    return [
        payload["outcome"]
        for level, event, payload in events
        if level == "info"
        and event == "execution_outcome"
        and payload.get("trace_id") == trace_id
    ]


def test_successful_execution_trace(monkeypatch):
    spy = _SpyLog()
    monkeypatch.setattr(observability, "log", spy)
    handler = _build_handler()

    result = asyncio.run(
        handler.handle("trade", value="test PM1 YES 10", correlation_id="trace-success")
    )

    assert result.success is True
    stages = _stage_names(spy.events, "trace-success")
    assert stages[0] == "ENTRY"
    assert "VALIDATION" in stages
    assert "RISK" in stages
    assert "EXECUTION" in stages
    assert stages[-1] == "RESULT"
    assert _outcomes(spy.events, "trace-success")[-1] == "SUCCESS"


def test_failure_trace_structured_error(monkeypatch):
    spy = _SpyLog()
    monkeypatch.setattr(observability, "log", spy)
    handler = _build_handler()

    async def _raise_export_error() -> dict:
        raise RuntimeError("payload_export_failed")

    monkeypatch.setattr(
        "projects.polymarket.polyquantbot.telegram.command_handler.export_execution_payload",
        _raise_export_error,
    )

    result = asyncio.run(
        handler.handle("trade", value="test PM2 YES 10", correlation_id="trace-failure")
    )

    assert result.success is False
    assert _outcomes(spy.events, "trace-failure")[-1] == "FAILED"
    error_events = [
        payload
        for level, event, payload in spy.events
        if level == "error" and event == "execution_failure"
    ]
    assert error_events
    assert error_events[-1]["error_type"] == "RuntimeError"
    assert error_events[-1]["execution_stage"] == "EXECUTION"
    assert error_events[-1]["trace_id"] == "trace-failure"


def test_timeout_trace(monkeypatch):
    spy = _SpyLog()
    monkeypatch.setattr(observability, "log", spy)
    handler = _build_handler()

    async def _slow_eval(self, market_price: float, trace_id: str | None = None) -> str:
        _ = self, market_price, trace_id
        await asyncio.sleep(5.2)
        return "OPENED"

    monkeypatch.setattr(StrategyTrigger, "evaluate", _slow_eval)

    result = asyncio.run(
        handler.handle("trade", value="test PM3 YES 10", correlation_id="trace-timeout")
    )

    assert result.success is False
    assert _outcomes(spy.events, "trace-timeout")[-1] == "TIMEOUT"


def test_duplicate_prevention_trace(monkeypatch):
    spy = _SpyLog()
    monkeypatch.setattr(observability, "log", spy)
    handler = _build_handler()

    first = asyncio.run(
        handler.handle("trade", value="test PM4 YES 10", correlation_id="trace-dup-1")
    )
    second = asyncio.run(
        handler.handle("trade", value="test PM4 YES 10", correlation_id="trace-dup-2")
    )

    assert first.success is True
    assert second.success is False
    assert _outcomes(spy.events, "trace-dup-2")[-1] == "DUPLICATE_PREVENTED"


def test_invalid_input_trace(monkeypatch):
    spy = _SpyLog()
    monkeypatch.setattr(observability, "log", spy)
    handler = _build_handler()

    result = asyncio.run(
        handler.handle("trade", value="test PM5 YES bad-size", correlation_id="trace-invalid")
    )

    assert result.success is False
    assert _outcomes(spy.events, "trace-invalid")[-1] == "INVALID_INPUT"
