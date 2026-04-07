from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from projects.polymarket.polyquantbot.config.runtime_config import ConfigManager
from projects.polymarket.polyquantbot.core.system_state import SystemStateManager
from projects.polymarket.polyquantbot.telegram.handlers.callback_router import CallbackRouter
from projects.polymarket.polyquantbot.telegram.ui.keyboard import build_paper_wallet_menu


def _router() -> CallbackRouter:
    return CallbackRouter(
        tg_api="https://api.telegram.org/botTEST",
        cmd_handler=MagicMock(),
        state_manager=SystemStateManager(),
        config_manager=ConfigManager(),
        mode="PAPER",
    )


def test_portfolio_trade_opens_trade_submenu_contract() -> None:
    router = _router()
    portfolio_service = MagicMock()
    portfolio_service.get_state.return_value = None
    with patch(
        "projects.polymarket.polyquantbot.telegram.handlers.callback_router.get_portfolio_service",
        return_value=portfolio_service,
    ):
        _, keyboard = asyncio.run(router._render_normalized_callback("portfolio_trade"))
    assert keyboard == build_paper_wallet_menu()


def test_trade_actions_render_intended_trade_views_without_home_fallback() -> None:
    router = _router()
    portfolio_service = MagicMock()
    portfolio_service.get_state.return_value = None
    titles = {
        "trade_signal": "📡 Trade Signal",
        "trade_paper_execute": "🧪 Paper Execute",
        "trade_kill_switch": "🛑 Kill Switch",
        "trade_status": "📊 Trade Status",
    }
    with patch(
        "projects.polymarket.polyquantbot.telegram.handlers.callback_router.get_portfolio_service",
        return_value=portfolio_service,
    ):
        for action, title in titles.items():
            text, keyboard = asyncio.run(router._render_normalized_callback(action))
            assert title in text
            assert "🏠 Home Command" not in text
            assert keyboard == build_paper_wallet_menu()
