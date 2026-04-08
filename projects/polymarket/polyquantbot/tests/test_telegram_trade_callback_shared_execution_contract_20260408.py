from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from projects.polymarket.polyquantbot.config.runtime_config import ConfigManager
from projects.polymarket.polyquantbot.core.system_state import SystemStateManager
from projects.polymarket.polyquantbot.telegram.command_handler import CommandHandler, CommandResult
from projects.polymarket.polyquantbot.telegram.handlers.callback_router import CallbackRouter


def _make_router() -> CallbackRouter:
    cmd = MagicMock()
    cmd.execute_trade_test_contract = AsyncMock(
        return_value=CommandResult(success=True, message="✅ executed")
    )
    return CallbackRouter(
        tg_api="https://api.telegram.org/botTEST",
        cmd_handler=cmd,
        state_manager=SystemStateManager(),
        config_manager=ConfigManager(),
        mode="PAPER",
    )


def test_valid_callback_execute_path_reaches_shared_execution_contract() -> None:
    router = _make_router()
    text, keyboard = asyncio.run(router._dispatch("trade_paper_execute", user_id=77))
    assert "executed" in text
    assert any(btn["callback_data"] == "action:trade_paper_execute" for row in keyboard for btn in row)
    router._cmd.execute_trade_test_contract.assert_awaited_once_with(
        market="paper-test-market",
        side="YES",
        size=1.0,
    )


def test_trade_test_command_uses_shared_execution_contract() -> None:
    handler = CommandHandler(
        state_manager=SystemStateManager(),
        config_manager=ConfigManager(),
    )
    handler.execute_trade_test_contract = AsyncMock(
        return_value=CommandResult(success=True, message="shared-path")
    )

    result = asyncio.run(handler._handle_trade_test("mkt-1 YES 2"))

    assert result.success is True
    assert result.message == "shared-path"
    handler.execute_trade_test_contract.assert_awaited_once_with(
        market="mkt-1",
        side="YES",
        size=2.0,
    )


def test_duplicate_click_protection_blocks_parallel_execution() -> None:
    router = _make_router()
    gate = asyncio.Event()

    async def slow_execute(*, market: str, side: str, size: float) -> CommandResult:
        await gate.wait()
        return CommandResult(success=True, message=f"{market}-{side}-{size}")

    router._cmd.execute_trade_test_contract = AsyncMock(side_effect=slow_execute)

    async def _run() -> tuple[tuple[str, list], tuple[str, list]]:
        first = asyncio.create_task(router._dispatch("trade_paper_execute", user_id=11))
        await asyncio.sleep(0.01)
        second = asyncio.create_task(router._dispatch("trade_paper_execute", user_id=11))
        await asyncio.sleep(0.01)
        gate.set()
        return await first, await second

    first_result, second_result = asyncio.run(_run())
    assert router._cmd.execute_trade_test_contract.await_count == 1
    assert "Execution already in progress" in second_result[0]
    assert "paper-test-market-YES-1.0" in first_result[0]


def test_invalid_payload_is_rejected_without_execution() -> None:
    router = _make_router()
    text, _ = asyncio.run(router._dispatch("trade_paper_execute::YES:1", user_id=1))
    assert "Invalid trade payload" in text
    assert router._cmd.execute_trade_test_contract.await_count == 0


def test_failed_execution_returns_visible_feedback() -> None:
    router = _make_router()
    router._cmd.execute_trade_test_contract = AsyncMock(
        return_value=CommandResult(success=False, message="Risk blocked: daily loss limit reached")
    )
    text, _ = asyncio.run(router._dispatch("trade_paper_execute", user_id=1))
    assert "Paper execution blocked" in text
    assert "Risk blocked: daily loss limit reached" in text
