from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from projects.polymarket.polyquantbot.config.runtime_config import ConfigManager
from projects.polymarket.polyquantbot.core.system_state import SystemStateManager
from projects.polymarket.polyquantbot.telegram.handlers.callback_router import CallbackRouter


def _callback_values(keyboard: list[list[dict[str, str]]]) -> set[str]:
    return {button["callback_data"] for row in keyboard for button in row}


def _make_router() -> CallbackRouter:
    return CallbackRouter(
        tg_api="https://api.telegram.org/botTEST",
        cmd_handler=MagicMock(),
        state_manager=SystemStateManager(),
        config_manager=ConfigManager(),
        mode="PAPER",
    )


def test_trade_menu_routing_contract_routes_without_home_fallback() -> None:
    router = _make_router()
    expected_trade_keyboard = {
        "action:trade_signal",
        "action:trade_paper_execute",
        "action:trade_kill_switch",
        "action:trade_status",
    }
    routes = {
        "portfolio_trade": "🎯 Trade Detail",
        "trade_signal": "🎯 Trade Detail",
        "trade_paper_execute": "🎯 Trade Detail",
        "trade_kill_switch": "🎛️ Control",
        "trade_status": "🧠 System Status",
    }

    for action, expected_title in routes.items():
        text, keyboard = asyncio.run(router._dispatch(action))
        assert "🏠 Home Command" not in text
        assert expected_title in text
        assert _callback_values(keyboard) == expected_trade_keyboard
