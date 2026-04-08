from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from projects.polymarket.polyquantbot.config.runtime_config import ConfigManager
from projects.polymarket.polyquantbot.core.system_state import SystemStateManager
from projects.polymarket.polyquantbot.telegram.command_handler import CommandHandler
from projects.polymarket.polyquantbot.telegram.command_router import CommandRouter
from projects.polymarket.polyquantbot.telegram.execution_entry_contract import (
    ExecutionEntry,
    ExecutionEntryResult,
    get_telegram_execution_entry_service,
)
from projects.polymarket.polyquantbot.telegram.handlers.callback_router import CallbackRouter


def _reset_entry_service_state() -> None:
    service = get_telegram_execution_entry_service()
    service._seen_signatures.clear()  # noqa: SLF001


def _make_command_handler() -> CommandHandler:
    return CommandHandler(
        state_manager=SystemStateManager(),
        config_manager=ConfigManager(),
        mode="PAPER",
    )


def _make_callback_router(cmd_handler: CommandHandler | None = None) -> CallbackRouter:
    return CallbackRouter(
        tg_api="https://api.telegram.org/botTEST",
        cmd_handler=cmd_handler or _make_command_handler(),
        state_manager=SystemStateManager(),
        config_manager=ConfigManager(),
        mode="PAPER",
    )


def test_valid_trade_command_reaches_shared_execution_entry(monkeypatch) -> None:
    _reset_entry_service_state()
    handler = _make_command_handler()
    router = CommandRouter(handler=handler)
    service = get_telegram_execution_entry_service()

    called: list[str] = []

    async def fake_execute(entry: ExecutionEntry, engine=None) -> ExecutionEntryResult:
        called.append(entry.source)
        return ExecutionEntryResult(
            success=True,
            message="ok",
            reason="executed",
            payload={"positions": []},
            pipeline_path=("entry", "risk", "execution"),
        )

    monkeypatch.setattr(service, "execute", fake_execute)

    update = {"update_id": 1, "message": {"from": {"id": 123}, "text": "/trade test market_alpha YES 10"}}
    result = asyncio.run(router.route_update(update))

    assert result is not None
    assert result.success is True
    assert called == ["telegram_command"]


def test_valid_callback_reaches_same_shared_execution_entry(monkeypatch) -> None:
    _reset_entry_service_state()
    service = get_telegram_execution_entry_service()
    called: list[str] = []

    async def fake_execute(entry: ExecutionEntry, engine=None) -> ExecutionEntryResult:
        called.append(entry.source)
        return ExecutionEntryResult(
            success=True,
            message="ok",
            reason="executed",
            payload={"positions": []},
            pipeline_path=("entry", "risk", "execution"),
        )

    monkeypatch.setattr(service, "execute", fake_execute)

    router = _make_callback_router()
    text, _ = asyncio.run(router._dispatch("trade_paper_execute"))

    assert "Trade Detail" in text
    assert called == ["telegram_callback"]


def test_shared_path_proof_command_and_callback_use_identical_service(monkeypatch) -> None:
    _reset_entry_service_state()
    service = get_telegram_execution_entry_service()
    calls: list[tuple[str, tuple[str, str, str]]] = []

    async def fake_execute(entry: ExecutionEntry, engine=None) -> ExecutionEntryResult:
        path = ("entry", "risk", "execution")
        calls.append((entry.source, path))
        return ExecutionEntryResult(True, "ok", "executed", {"positions": []}, path)

    monkeypatch.setattr(service, "execute", fake_execute)

    command_router = CommandRouter(handler=_make_command_handler())
    callback_router = _make_callback_router()

    update = {"update_id": 2, "message": {"from": {"id": 555}, "text": "/trade test market_beta NO 5"}}
    result = asyncio.run(command_router.route_update(update))
    assert result is not None and result.success

    asyncio.run(callback_router._dispatch("trade_paper_execute"))

    assert [c[0] for c in calls] == ["telegram_command", "telegram_callback"]
    assert all(path == ("entry", "risk", "execution") for _, path in calls)


def test_invalid_command_is_rejected_without_execution(monkeypatch) -> None:
    _reset_entry_service_state()
    handler = _make_command_handler()
    router = CommandRouter(handler=handler)
    service = get_telegram_execution_entry_service()

    execute_mock = MagicMock()
    monkeypatch.setattr(service, "execute", execute_mock)

    update = {"update_id": 3, "message": {"from": {"id": 123}, "text": "/trade test bad_market MAYBE 10"}}
    result = asyncio.run(router.route_update(update))

    assert result is not None
    assert result.success is False
    assert execute_mock.call_count == 0


def test_invalid_callback_is_rejected_without_execution(monkeypatch) -> None:
    _reset_entry_service_state()
    service = get_telegram_execution_entry_service()
    execute_mock = MagicMock()
    monkeypatch.setattr(service, "execute", execute_mock)

    router = _make_callback_router()
    asyncio.run(router._dispatch("trade_paper_execute:malformed"))

    assert execute_mock.call_count == 0


def test_duplicate_protection_blocks_repeat_execution() -> None:
    _reset_entry_service_state()
    service = get_telegram_execution_entry_service()

    class _StubEngine:
        max_position_size_ratio = 0.10

        def __init__(self) -> None:
            self.calls = 0

        async def snapshot(self):
            return SimpleNamespace(positions=(), equity=1000.0)

        async def open_position(self, **kwargs):
            self.calls += 1
            return SimpleNamespace(position_id="p1")

        async def update_mark_to_market(self, _prices):
            return 0.0

    entry = ExecutionEntry(
        market="market_dup",
        side="YES",
        size=10.0,
        source="telegram_command",
        signature="market_dup:YES:10.000000",
    )

    engine = _StubEngine()
    first = asyncio.run(service.execute(entry, engine=engine))
    second = asyncio.run(service.execute(entry, engine=engine))

    assert first.success is True
    assert second.success is False
    assert second.reason == "duplicate_entry"
    assert engine.calls == 1


def test_failure_path_feedback_is_visible() -> None:
    _reset_entry_service_state()
    service = get_telegram_execution_entry_service()

    class _StubBlockedEngine:
        max_position_size_ratio = 0.10

        async def snapshot(self):
            return SimpleNamespace(positions=(), equity=1000.0)

        async def open_position(self, **kwargs):
            return None

    entry = ExecutionEntry(
        market="market_fail",
        side="YES",
        size=10.0,
        source="telegram_callback",
        signature="market_fail:YES:10.000000",
    )
    result = asyncio.run(service.execute(entry, engine=_StubBlockedEngine()))

    assert result.success is False
    assert "blocked" in result.message.lower()
    assert result.pipeline_path == ("entry", "risk", "execution")
