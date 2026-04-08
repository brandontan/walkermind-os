from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from projects.polymarket.polyquantbot.config.runtime_config import ConfigManager
from projects.polymarket.polyquantbot.core.system_state import SystemStateManager
from projects.polymarket.polyquantbot.execution import engine as execution_engine_module
from projects.polymarket.polyquantbot.execution.engine import get_execution_engine
from projects.polymarket.polyquantbot.telegram.command_handler import CommandHandler, CommandResult
from projects.polymarket.polyquantbot.telegram.command_router import CommandRouter
from projects.polymarket.polyquantbot.telegram.handlers.callback_router import CallbackRouter


def _reset_execution_singleton() -> None:
    execution_engine_module._engine_singleton = None  # type: ignore[attr-defined]


def _make_handler() -> CommandHandler:
    return CommandHandler(
        state_manager=SystemStateManager(),
        config_manager=ConfigManager(),
        metrics_source=None,
        telegram_sender=None,
        chat_id="",
    )


def _make_callback_router(handler: CommandHandler) -> CallbackRouter:
    return CallbackRouter(
        tg_api="https://api.telegram.org/botTEST",
        cmd_handler=handler,
        state_manager=SystemStateManager(),
        config_manager=ConfigManager(),
        mode="PAPER",
    )


def test_command_path_execution_reaches_strategy_trigger_without_snapshot_attribute_crash() -> None:
    _reset_execution_singleton()
    handler = _make_handler()
    result = asyncio.run(handler.handle(command="trade", value="test CONTRACT YES 10", user_id="u-1"))
    assert result.success is True
    assert "implied_prob" not in result.message
    assert "volatility" not in result.message


def test_callback_path_execution_reaches_strategy_trigger_without_snapshot_attribute_crash() -> None:
    _reset_execution_singleton()
    handler = _make_handler()
    router = _make_callback_router(handler)
    message, _keyboard = asyncio.run(router._dispatch("trade_paper_execute", user_id=7))
    assert "implied_prob" not in message
    assert "volatility" not in message


def test_command_and_callback_share_same_command_handler_trade_path() -> None:
    _reset_execution_singleton()
    handler = _make_handler()
    router = CommandRouter(handler=handler)

    calls: list[tuple[str, object]] = []
    original_handle = handler.handle

    async def spy_handle(command: str, value: object = None, user_id: str | None = None, correlation_id: str | None = None) -> CommandResult:  # type: ignore[override]
        calls.append((command, value))
        return await original_handle(command=command, value=value, user_id=user_id, correlation_id=correlation_id)

    handler.handle = spy_handle  # type: ignore[method-assign]

    callback_router = _make_callback_router(handler)
    asyncio.run(router.route_update({"command": "trade", "value": "test SHARED YES 10"}))
    asyncio.run(callback_router._dispatch("trade_paper_execute", user_id=42))

    assert ("trade", "test SHARED YES 10") in calls
    assert ("trade", "test PAPER_MARKET YES 10") in calls


def test_duplicate_trade_intent_is_blocked() -> None:
    _reset_execution_singleton()
    handler = _make_handler()
    first = asyncio.run(handler.handle(command="trade", value="test DUP YES 10", user_id="dup-user"))
    second = asyncio.run(handler.handle(command="trade", value="test DUP YES 10", user_id="dup-user"))

    assert first.success is True
    assert second.success is False
    assert "duplicate_blocked" in second.message


def test_callback_edit_timeout_retry_still_succeeds() -> None:
    class _FakeResp:
        async def json(self) -> dict[str, object]:
            return {"ok": True}

    class _FakeSession:
        def __init__(self) -> None:
            self.calls = 0

        async def post(self, _url: str, json: dict[str, object]) -> _FakeResp:
            self.calls += 1
            if self.calls == 1:
                raise asyncio.TimeoutError()
            assert "chat_id" in json
            return _FakeResp()

    _reset_execution_singleton()
    handler = _make_handler()
    callback_router = _make_callback_router(handler)
    fake_session = _FakeSession()
    ok = asyncio.run(
        callback_router._edit_message(
            session=fake_session,  # type: ignore[arg-type]
            chat_id=1,
            message_id=10,
            text="retry-test",
            keyboard=[],
        )
    )
    assert ok is True
    assert fake_session.calls == 2


def test_partial_failure_feedback_remains_explicit() -> None:
    handler = _make_handler()
    handler.handle = AsyncMock(  # type: ignore[method-assign]
        return_value=CommandResult(
            success=False,
            message="partial_failure: post-process failed",
        )
    )
    callback_router = _make_callback_router(handler)
    message, _keyboard = asyncio.run(callback_router._dispatch("trade_paper_execute", user_id=11))
    assert "partial_failure" in message


def test_execution_snapshot_contract_exposes_required_fields() -> None:
    _reset_execution_singleton()
    engine = get_execution_engine()
    snapshot = asyncio.run(engine.snapshot())
    assert hasattr(snapshot, "implied_prob")
    assert hasattr(snapshot, "volatility")
