from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from projects.polymarket.polyquantbot.config.runtime_config import ConfigManager
from projects.polymarket.polyquantbot.core.system_state import SystemStateManager
from projects.polymarket.polyquantbot.interface.telegram.view_handler import render_view
from projects.polymarket.polyquantbot.telegram.handlers.callback_router import CallbackRouter


def test_render_view_home_tolerates_na_numeric_placeholders() -> None:
    payload = {
        "status": "RUNNING",
        "equity": "N/A",
        "balance": None,
        "positions": "",
        "realized": "N/A",
        "unrealized_pnl": "N/A",
        "winrate": "N/A",
        "trades": "N/A",
    }
    text = asyncio.run(render_view("home", payload))
    assert "🏠 Home Command" in text
    assert "💡 Operator Note" in text


def test_render_view_home_tolerates_sparse_payload() -> None:
    text = asyncio.run(render_view("start", {"status": "RUNNING"}))
    assert "🏠 Home Command" in text
    assert "Open Positions: 0" in text


def test_callback_router_normalized_payload_tolerates_portfolio_na_values() -> None:
    cmd_handler = MagicMock()
    state_manager = SystemStateManager()
    config_manager = ConfigManager()
    router = CallbackRouter(
        tg_api="https://api.telegram.org/botTEST",
        cmd_handler=cmd_handler,
        state_manager=state_manager,
        config_manager=config_manager,
        mode="PAPER",
    )

    portfolio_state = SimpleNamespace(
        positions=[SimpleNamespace(market_id="m1", side="yes", avg_price="N/A", size="N/A", unrealized_pnl=None)],
        equity="N/A",
        cash=None,
        pnl="",
    )
    portfolio_service = MagicMock()
    portfolio_service.get_state.return_value = portfolio_state

    with patch(
        "projects.polymarket.polyquantbot.telegram.handlers.callback_router.get_portfolio_service",
        return_value=portfolio_service,
    ):
        payload = router._build_normalized_payload("home")

    assert payload["equity"] == 0.0
    assert payload["available_balance"] == 0.0
    assert payload["pnl"] == 0.0
    assert payload["positions_count"] == 1
    assert payload["entry"] == 0.0
    assert payload["size"] == 0.0
