from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from projects.polymarket.polyquantbot.config.runtime_config import ConfigManager
from projects.polymarket.polyquantbot.core.system_state import SystemStateManager
from projects.polymarket.polyquantbot.execution import engine as execution_engine_module
from projects.polymarket.polyquantbot.telegram.command_handler import CommandHandler
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


def test_entry_execution_emits_single_strict_hierarchical_alert() -> None:
    _reset_execution_singleton()
    handler = _make_handler()
    with patch("projects.polymarket.polyquantbot.telegram.command_handler.StrategyTrigger") as trigger_cls:
        trigger = trigger_cls.return_value
        trigger.evaluate = AsyncMock(return_value="OPENED")
        result = asyncio.run(handler.handle(command="trade", value="test ENTRY1 YES 10", user_id="u-1"))

    assert result.success is True
    expected_lines = [
        "🚀 ENTRY EXECUTED",
        "|- Market: ENTRY1",
        "|- Side: YES",
        "|- Price: 0.4200",
        "|- Size: $10.00",
        "|- Edge: 50.00%",
        "|- Reason: signal threshold met",
    ]
    assert result.message.splitlines() == expected_lines
    assert result.message.count("🚀 ENTRY EXECUTED") == 1


def test_exit_execution_emits_single_strict_hierarchical_alert() -> None:
    handler = _make_handler()

    class _StubEngine:
        async def snapshot(self):
            from projects.polymarket.polyquantbot.execution.models import Position
            from types import SimpleNamespace
            return SimpleNamespace(
                positions=(
                    Position(
                        market_id="EXIT1",
                        side="NO",
                        entry_price=0.42,
                        current_price=0.42,
                        size=10.0,
                        pnl=0.0,
                        position_id="pid-1",
                    ),
                )
            )

        async def close_position(self, position, price: float) -> float:
            return 1.25

    with patch("projects.polymarket.polyquantbot.telegram.command_handler.get_execution_engine", return_value=_StubEngine()):
        with patch(
            "projects.polymarket.polyquantbot.telegram.command_handler.export_execution_payload",
            AsyncMock(return_value={"positions": [], "cash": 10001.25, "equity": 10001.25, "realized": 1.25}),
        ):
            close_result = asyncio.run(handler.handle(command="trade", value="close EXIT1", user_id="u-2"))
    assert close_result.success is True
    lines = close_result.message.splitlines()
    assert lines[0] == "🏁 EXIT EXECUTED"
    assert lines[1] == "|- Market: EXIT1"
    assert lines[2] == "|- Side: NO"
    assert lines[3] == "|- Entry: 0.4200"
    assert lines[4] == "|- Exit: 0.5000"
    assert lines[5] == "|- PnL: +$1.25"
    assert lines[6] == "|- Result: WIN"
    assert close_result.message.count("🏁 EXIT EXECUTED") == 1


def test_skipped_scenario_emits_strict_hierarchical_alert() -> None:
    _reset_execution_singleton()
    handler = _make_handler()
    with patch("projects.polymarket.polyquantbot.telegram.command_handler.StrategyTrigger") as trigger_cls:
        trigger = trigger_cls.return_value
        trigger.evaluate = AsyncMock(return_value="HOLD")
        result = asyncio.run(handler.handle(command="trade", value="test SKIP1 YES 10", user_id="u-3"))

    assert result.success is False
    assert result.message.splitlines() == [
        "⛔ TRADE SKIPPED",
        "|- Market: SKIP1",
        "|- Reason: insufficient edge",
    ]


def test_no_duplicate_alerts_across_command_and_callback_paths() -> None:
    _reset_execution_singleton()
    handler = _make_handler()
    callback_router = _make_callback_router(handler)
    with patch("projects.polymarket.polyquantbot.telegram.command_handler.StrategyTrigger") as trigger_cls:
        trigger = trigger_cls.return_value
        trigger.evaluate = AsyncMock(return_value="OPENED")
        command_result = asyncio.run(handler.handle(command="trade", value="test CMD1 YES 10", user_id="u-4"))
        callback_message, _keyboard = asyncio.run(callback_router._dispatch("trade_paper_execute", user_id=99))

    assert command_result.message.count("🚀 ENTRY EXECUTED") == 1
    assert callback_message.count("🚀 ENTRY EXECUTED") == 1


def test_format_validation_contains_pipe_line_count_and_field_order() -> None:
    _reset_execution_singleton()
    handler = _make_handler()
    with patch("projects.polymarket.polyquantbot.telegram.command_handler.StrategyTrigger") as trigger_cls:
        trigger = trigger_cls.return_value
        trigger.evaluate = AsyncMock(return_value="OPENED")
        entry = asyncio.run(handler.handle(command="trade", value="test FORMAT1 YES 10", user_id="u-5"))

    entry_lines = entry.message.splitlines()
    assert all(line.startswith("|-") for line in entry_lines[1:])
    assert len(entry_lines) == 7
    assert entry_lines[1:7] == [
        "|- Market: FORMAT1",
        "|- Side: YES",
        "|- Price: 0.4200",
        "|- Size: $10.00",
        "|- Edge: 50.00%",
        "|- Reason: signal threshold met",
    ]
