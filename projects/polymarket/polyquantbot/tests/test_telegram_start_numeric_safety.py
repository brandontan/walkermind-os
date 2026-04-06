from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from projects.polymarket.polyquantbot.config.runtime_config import ConfigManager
from projects.polymarket.polyquantbot.core import market_scope
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


def test_callback_router_home_render_tolerates_malformed_portfolio_payload() -> None:
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
    malformed_portfolio_state = {
        "positions": [
            {"market_id": "m1", "side": "YES", "entry_price": "N/A", "size": "N/A", "unrealized_pnl": ""},
            {"market_id": None, "side": None, "entry_price": "bad-value", "size": None},
        ],
        "equity": "N/A",
        "cash": "",
        "pnl": "broken-number",
    }
    portfolio_service = MagicMock()
    portfolio_service.get_state.return_value = malformed_portfolio_state

    with patch(
        "projects.polymarket.polyquantbot.telegram.handlers.callback_router.get_portfolio_service",
        return_value=portfolio_service,
    ):
        text, _ = asyncio.run(router._render_normalized_callback("home"))

    assert "🏠 Home Command" in text
    assert "Open Positions: 2" in text
    assert "Total Value: $0.00" in text


def test_callback_router_start_to_home_transition_safe_with_sparse_payload() -> None:
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
    portfolio_service = MagicMock()
    portfolio_service.get_state.return_value = {"positions": None, "equity": None, "cash": None, "pnl": None}

    with patch(
        "projects.polymarket.polyquantbot.telegram.handlers.callback_router.get_portfolio_service",
        return_value=portfolio_service,
    ):
        text, _ = asyncio.run(router._render_normalized_callback("start"))

    assert "🏠 Home Command" in text
    assert "Open Positions: 0" in text


def test_home_render_after_scope_state_restore_tolerates_sparse_file(tmp_path) -> None:
    state_file = tmp_path / "market_scope_state.json"
    state_file.write_text(
        '{"all_markets_enabled": false, "enabled_categories": ["Crypto", null, "", 42]}',
        encoding="utf-8",
    )

    original_file = market_scope._SCOPE_STATE_FILE
    original_loaded = market_scope._scope_state_loaded
    original_all = market_scope._all_markets_enabled
    original_categories = set(market_scope._enabled_categories)
    try:
        market_scope._SCOPE_STATE_FILE = state_file
        market_scope._scope_state_loaded = False
        market_scope._all_markets_enabled = True
        market_scope._enabled_categories = set()

        text = asyncio.run(render_view("home", market_scope.get_market_scope_snapshot()))
        assert "🏠 Home Command" in text
        assert "Scope: Categories (1)" in text
    finally:
        market_scope._SCOPE_STATE_FILE = original_file
        market_scope._scope_state_loaded = original_loaded
        market_scope._all_markets_enabled = original_all
        market_scope._enabled_categories = original_categories
