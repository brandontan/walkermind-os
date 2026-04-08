from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from projects.polymarket.polyquantbot.config.runtime_config import ConfigManager
from projects.polymarket.polyquantbot.core.system_state import SystemStateManager
from projects.polymarket.polyquantbot.telegram.command_handler import CommandResult
from projects.polymarket.polyquantbot.telegram.handlers.callback_router import CallbackRouter


def _make_router() -> CallbackRouter:
    cmd_handler = MagicMock()
    cmd_handler.handle = AsyncMock(
        return_value=CommandResult(success=True, message="✅ Paper execution OK")
    )
    return CallbackRouter(
        tg_api="https://api.telegram.org/botTEST",
        cmd_handler=cmd_handler,
        state_manager=SystemStateManager(),
        config_manager=ConfigManager(),
        mode="PAPER",
    )


def test_callback_builds_default_trade_command() -> None:
    assert (
        CallbackRouter._build_trade_test_command("trade_paper_execute")
        == "/trade test market1 YES 10"
    )


def test_callback_blocks_invalid_trade_payload() -> None:
    router = _make_router()

    text, keyboard = asyncio.run(
        router._route_trade_callback_via_command(
            action="trade_paper_execute|market1|MAYBE|10",
            user_id=12345,
        )
    )

    assert text.startswith("❌")
    assert router._cmd.handle.await_count == 0
    assert any(
        button["callback_data"] == "action:trade_paper_execute"
        for row in keyboard
        for button in row
    )


def test_callback_routes_via_command_handler_and_returns_trade_menu() -> None:
    router = _make_router()

    text, keyboard = asyncio.run(router._dispatch("trade_paper_execute", user_id=42))

    assert text == "✅ Paper execution OK"
    router._cmd.handle.assert_awaited_once_with(
        command="/trade",
        value="test market1 YES 10",
        user_id="42",
    )
    assert any(
        button["callback_data"] == "action:trade_paper_execute"
        for row in keyboard
        for button in row
    )


def test_duplicate_callback_keeps_single_execution_path() -> None:
    router = _make_router()

    asyncio.run(router._dispatch("trade_paper_execute", user_id=7))
    asyncio.run(router._dispatch("trade_paper_execute", user_id=7))

    assert router._cmd.handle.await_count == 2
    for call in router._cmd.handle.await_args_list:
        assert call.kwargs["command"] == "/trade"
        assert call.kwargs["value"] == "test market1 YES 10"
