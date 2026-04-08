from __future__ import annotations

import asyncio
from dataclasses import dataclass

from projects.polymarket.polyquantbot.telegram.command_handler import CommandHandler
from projects.polymarket.polyquantbot.core.system_state import SystemStateManager
from projects.polymarket.polyquantbot.config.runtime_config import ConfigManager


@dataclass
class _CallTracker:
    evaluate_calls: int = 0
    mark_calls: int = 0
    merge_calls: int = 0


class _DummyEngine:
    def __init__(self, tracker: _CallTracker, delay: float = 0.0) -> None:
        self._tracker = tracker
        self._delay = delay

    async def update_mark_to_market(self, _: dict[str, float]) -> None:
        self._tracker.mark_calls += 1
        if self._delay > 0:
            await asyncio.sleep(self._delay)


class _DummyTrigger:
    def __init__(self, tracker: _CallTracker, delay: float = 0.0) -> None:
        self._tracker = tracker
        self._delay = delay

    async def evaluate(self, _: float) -> None:
        self._tracker.evaluate_calls += 1
        if self._delay > 0:
            await asyncio.sleep(self._delay)


class _Portfolio:
    def __init__(self, tracker: _CallTracker, fail_first: int = 0) -> None:
        self._tracker = tracker
        self._remaining_failures = fail_first

    def merge_execution_state(self, **_: object) -> None:
        self._tracker.merge_calls += 1
        if self._remaining_failures > 0:
            self._remaining_failures -= 1
            raise RuntimeError("merge failed")


async def _build_handler(monkeypatch, *, trigger_delay: float = 0.0, mark_delay: float = 0.0, merge_failures: int = 0):
    from projects.polymarket.polyquantbot.telegram import command_handler as mod

    tracker = _CallTracker()
    engine = _DummyEngine(tracker, delay=mark_delay)
    portfolio = _Portfolio(tracker, fail_first=merge_failures)

    def _fake_trigger(*args, **kwargs):
        return _DummyTrigger(tracker, delay=trigger_delay)

    async def _fake_export() -> dict[str, object]:
        return {"positions": [], "cash": 1000.0, "equity": 1000.0, "realized": 0.0}

    async def _fake_render_view(_: str, __: dict[str, object]) -> str:
        return "ok"

    monkeypatch.setattr(mod, "get_execution_engine", lambda: engine)
    monkeypatch.setattr(mod, "StrategyTrigger", _fake_trigger)
    monkeypatch.setattr(mod, "export_execution_payload", _fake_export)
    monkeypatch.setattr(mod, "get_portfolio_service", lambda: portfolio)
    monkeypatch.setattr(mod, "render_view", _fake_render_view)

    handler = CommandHandler(
        state_manager=SystemStateManager(),
        config_manager=ConfigManager(),
        metrics_source=None,
        telegram_sender=None,
        chat_id="",
    )
    return handler, tracker


def test_duplicate_execution_blocked(monkeypatch) -> None:
    async def _run() -> None:
        handler, tracker = await _build_handler(monkeypatch)
        r1 = await handler.handle("trade", raw_args="test MKT YES 10")
        r2 = await handler.handle("trade", raw_args="test MKT YES 10")
        assert r1.success is True
        assert r2.payload.get("status") == "duplicate_blocked"
        assert tracker.evaluate_calls == 1

    asyncio.run(_run())


def test_rapid_fire_commands_do_not_double_execute(monkeypatch) -> None:
    async def _run() -> None:
        handler, tracker = await _build_handler(monkeypatch)
        results = await asyncio.gather(*[
            handler.handle("trade", raw_args="test FAST YES 5") for _ in range(5)
        ])
        success_count = sum(1 for r in results if r.success)
        duplicate_count = sum(1 for r in results if r.payload.get("status") == "duplicate_blocked")
        assert success_count == 1
        assert duplicate_count == 4
        assert tracker.evaluate_calls == 1

    asyncio.run(_run())


def test_timeout_simulation_returns_safe_failure(monkeypatch) -> None:
    async def _run() -> None:
        handler, tracker = await _build_handler(monkeypatch, trigger_delay=2.0)
        result = await handler.handle("trade", raw_args="test SLOW YES 10")
        assert result.success is False
        assert result.payload.get("status") == "timeout"
        assert tracker.evaluate_calls == 1

    asyncio.run(_run())


def test_retry_is_safe_without_double_execution(monkeypatch) -> None:
    async def _run() -> None:
        handler, tracker = await _build_handler(monkeypatch, merge_failures=1)
        result = await handler.handle("trade", raw_args="test RETRY YES 10")
        assert result.success is True
        assert result.payload.get("status") == "executed"
        assert tracker.evaluate_calls == 1
        assert tracker.merge_calls == 2

    asyncio.run(_run())


def test_partial_failure_returns_consistent_status(monkeypatch) -> None:
    async def _run() -> None:
        handler, tracker = await _build_handler(monkeypatch, merge_failures=5)
        result = await handler.handle("trade", raw_args="test PART YES 10")
        assert result.success is False
        assert result.payload.get("status") == "partial_failure"
        assert tracker.evaluate_calls == 1

    asyncio.run(_run())


def test_concurrent_execution_requests_are_deterministic(monkeypatch) -> None:
    async def _run() -> None:
        handler, tracker = await _build_handler(monkeypatch, trigger_delay=0.2)

        async def _send() -> bool:
            res = await handler.handle("trade", raw_args="test RACE YES 2")
            return bool(res.success)

        outcomes = await asyncio.gather(*[_send() for _ in range(8)])
        assert outcomes.count(True) == 1
        assert tracker.evaluate_calls == 1

    asyncio.run(_run())
