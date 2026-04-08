from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from projects.polymarket.polyquantbot.config.runtime_config import ConfigManager
from projects.polymarket.polyquantbot.core.system_state import SystemStateManager
from projects.polymarket.polyquantbot.telegram.command_handler import CommandHandler, CommandResult
from projects.polymarket.polyquantbot.telegram.handlers.callback_router import CallbackRouter


class _DummyEngine:
    async def update_mark_to_market(self, _payload: dict[str, float]) -> None:
        return None


def _make_command_handler() -> CommandHandler:
    return CommandHandler(
        state_manager=SystemStateManager(),
        config_manager=ConfigManager(),
    )


def _make_router(cmd_handler: CommandHandler | MagicMock) -> CallbackRouter:
    return CallbackRouter(
        tg_api="https://api.telegram.org/botTEST",
        cmd_handler=cmd_handler,
        state_manager=SystemStateManager(),
        config_manager=ConfigManager(),
        mode="PAPER",
    )


def test_callback_execute_valid_payload_reaches_shared_execution_entry() -> None:
    cmd = MagicMock()
    cmd.execute_bounded_paper_trade = AsyncMock(
        return_value=CommandResult(success=True, message="EXECUTED", payload={})
    )
    router = _make_router(cmd)

    text, _ = asyncio.run(
        router._dispatch(
            "trade_paper_execute",
            action_payload="market-1|YES|5",
            callback_signature="sig-1",
        )
    )

    assert text == "EXECUTED"
    cmd.execute_bounded_paper_trade.assert_awaited_once()


def test_callback_execute_rejects_malformed_payload_without_execution() -> None:
    cmd = MagicMock()
    cmd.execute_bounded_paper_trade = AsyncMock()
    router = _make_router(cmd)

    text, _ = asyncio.run(
        router._dispatch(
            "trade_paper_execute",
            action_payload="bad-payload",
            callback_signature="sig-1",
        )
    )

    assert "Paper Execute Blocked" in text
    assert "Malformed execute payload" in text
    cmd.execute_bounded_paper_trade.assert_not_called()


def test_callback_execute_failure_feedback_is_visible() -> None:
    cmd = MagicMock()
    cmd.execute_bounded_paper_trade = AsyncMock(
        return_value=CommandResult(success=False, message="Risk blocked execution", payload={})
    )
    router = _make_router(cmd)

    text, _ = asyncio.run(
        router._dispatch(
            "trade_paper_execute",
            action_payload="market-1|NO|2",
            callback_signature="sig-1",
        )
    )

    assert "Paper Execute Blocked" in text
    assert "Risk blocked execution" in text


def test_shared_execution_path_used_by_command_and_callback() -> None:
    cmd_handler = _make_command_handler()
    router = _make_router(cmd_handler)

    with patch.object(
        cmd_handler,
        "execute_bounded_paper_trade",
        new=AsyncMock(return_value=CommandResult(success=True, message="ok", payload={})),
    ) as execute_mock:
        asyncio.run(cmd_handler._handle_trade_test("market-1 YES 1"))
        asyncio.run(
            router._dispatch(
                "trade_paper_execute",
                action_payload="market-1|YES|1",
                callback_signature="sig-1",
            )
        )

    assert execute_mock.await_count == 2


def test_duplicate_click_protection_blocks_repeated_callback_execution() -> None:
    cmd_handler = _make_command_handler()

    with patch(
        "projects.polymarket.polyquantbot.telegram.command_handler.get_execution_engine",
        return_value=_DummyEngine(),
    ), patch(
        "projects.polymarket.polyquantbot.telegram.command_handler.export_execution_payload",
        new=AsyncMock(return_value={"positions": [], "cash": 1000.0, "equity": 1000.0, "realized": 0.0}),
    ), patch(
        "projects.polymarket.polyquantbot.telegram.command_handler.get_portfolio_service",
    ) as service_mock, patch(
        "projects.polymarket.polyquantbot.telegram.command_handler.StrategyTrigger.evaluate",
        new=AsyncMock(return_value=None),
    ) as evaluate_mock:
        service_mock.return_value.merge_execution_state = MagicMock()

        first = asyncio.run(
            cmd_handler.execute_bounded_paper_trade(
                market="market-1",
                side="YES",
                size=1.0,
                source="telegram_callback_trade_paper_execute",
                dedup_key="callback:same",
            )
        )
        second = asyncio.run(
            cmd_handler.execute_bounded_paper_trade(
                market="market-1",
                side="YES",
                size=1.0,
                source="telegram_callback_trade_paper_execute",
                dedup_key="callback:same",
            )
        )

    assert first.success is True
    assert second.success is False
    assert "Duplicate execute request blocked" in second.message
    assert evaluate_mock.await_count == 1
