from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from projects.polymarket.polyquantbot.config.runtime_config import ConfigManager
from projects.polymarket.polyquantbot.core.system_state import SystemStateManager
from projects.polymarket.polyquantbot.telegram.command_handler import CommandHandler
from projects.polymarket.polyquantbot.telegram.command_router import CommandRouter
from projects.polymarket.polyquantbot.telegram.handlers.callback_router import CallbackRouter


def _make_command_handler() -> CommandHandler:
    return CommandHandler(
        state_manager=SystemStateManager(),
        config_manager=ConfigManager(),
        mode="PAPER",
    )


def _make_callback_router() -> CallbackRouter:
    cmd_handler = MagicMock()
    cmd_handler._runner = None
    cmd_handler._multi_metrics = None
    cmd_handler._allocator = None
    cmd_handler._risk_guard = None
    return CallbackRouter(
        tg_api="https://api.telegram.org/botTEST",
        cmd_handler=cmd_handler,
        state_manager=SystemStateManager(),
        config_manager=ConfigManager(),
        mode="PAPER",
    )


def test_valid_trade_execution_path_no_implied_prob_runtime_failure() -> None:
    handler = _make_command_handler()

    with patch(
        "projects.polymarket.polyquantbot.telegram.command_handler.render_view",
        new=AsyncMock(return_value="ok"),
    ):
        result = asyncio.run(handler._handle_trade_test("market-1 YES 100"))

    assert result.success is True
    assert "implied_prob" not in result.message


def test_shared_strategy_trigger_path_is_used_by_trade_test_entry() -> None:
    handler = _make_command_handler()

    with patch(
        "projects.polymarket.polyquantbot.telegram.command_handler.StrategyTrigger.evaluate",
        new=AsyncMock(return_value="OPENED"),
    ) as evaluate_mock, patch(
        "projects.polymarket.polyquantbot.telegram.command_handler.render_view",
        new=AsyncMock(return_value="ok"),
    ):
        result = asyncio.run(handler._handle_trade_test("market-2 NO 100"))

    assert result.success is True
    evaluate_mock.assert_awaited_once()


def test_duplicate_update_id_blocks_duplicate_command_execution() -> None:
    handler = _make_command_handler()
    handler.handle = AsyncMock(return_value=MagicMock(success=True, message="ok"))
    router = CommandRouter(handler=handler)

    update = {
        "update_id": 123,
        "message": {
            "from": {"id": 999},
            "text": "/status",
        },
    }

    first = asyncio.run(router.route_update(update))
    second = asyncio.run(router.route_update(update))

    assert first is not None
    assert second is None
    assert handler.handle.await_count == 1


def test_invalid_callback_payload_is_blocked_without_dispatch() -> None:
    router = _make_callback_router()

    with patch.object(router, "_answer_callback", new=AsyncMock()), patch.object(
        router,
        "_dispatch",
        new=AsyncMock(),
    ) as dispatch_mock, patch.object(router, "_edit_message", new=AsyncMock(return_value=True)):
        asyncio.run(
            router.route(
                session=MagicMock(),
                cq={
                    "id": "cb-1",
                    "data": "bad_payload",
                    "message": {"chat": {"id": 1}, "message_id": 10},
                    "from": {"id": 777},
                },
            )
        )

    dispatch_mock.assert_not_called()


def test_failure_path_returns_visible_feedback_message() -> None:
    handler = _make_command_handler()

    with patch(
        "projects.polymarket.polyquantbot.telegram.command_handler.StrategyTrigger.evaluate",
        new=AsyncMock(side_effect=RuntimeError("ExecutionSnapshot contract mismatch")),
    ):
        result = asyncio.run(handler._handle_trade_test("market-3 YES 100"))

    assert result.success is False
    assert "Paper execution failed" in result.message
