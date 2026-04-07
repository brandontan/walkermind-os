from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from projects.polymarket.polyquantbot.config.runtime_config import ConfigManager
from projects.polymarket.polyquantbot.core.system_state import SystemStateManager
from projects.polymarket.polyquantbot.telegram.handlers.callback_router import CallbackRouter


def _router() -> CallbackRouter:
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


def test_trade_menu_route_returns_mvp_keyboard() -> None:
    text, kb = asyncio.run(_router()._dispatch("portfolio_trade"))
    callback_data = {btn["callback_data"] for row in kb for btn in row}
    assert "TRADE MENU" in text
    assert callback_data == {
        "action:trade_signal",
        "action:trade_paper_execute",
        "action:trade_kill_switch",
        "action:trade_status",
        "action:portfolio",
    }


def test_trade_status_handles_missing_paper_engine_safely() -> None:
    text, kb = asyncio.run(_router()._dispatch("trade_status"))
    callback_data = {btn["callback_data"] for row in kb for btn in row}
    assert "unavailable" in text.lower()
    assert "action:trade_status" in callback_data
