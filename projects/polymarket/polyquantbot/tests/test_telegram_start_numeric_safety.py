from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from projects.polymarket.polyquantbot.config.runtime_config import ConfigManager
from projects.polymarket.polyquantbot.core import market_scope
from projects.polymarket.polyquantbot.core.system_state import SystemStateManager
from projects.polymarket.polyquantbot.telegram.command_handler import CommandHandler
from projects.polymarket.polyquantbot.telegram.command_router import CommandRouter
from projects.polymarket.polyquantbot.telegram.view_handler import render_view
from projects.polymarket.polyquantbot.telegram.handlers.callback_router import CallbackRouter
from projects.polymarket.polyquantbot.telegram.ui.reply_keyboard import REPLY_MENU_MAP


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


def test_command_router_start_live_path_tolerates_na_metrics_payload() -> None:
    state_manager = SystemStateManager()
    config_manager = ConfigManager()
    metrics_source = SimpleNamespace(
        snapshot=lambda: {
            "cash": "N/A",
            "equity": None,
            "open_positions": "N/A",
            "unrealized_pnl": "",
            "pnl": "bad-number",
        }
    )
    handler = CommandHandler(
        state_manager=state_manager,
        config_manager=config_manager,
        metrics_source=metrics_source,
        mode="PAPER",
    )
    router = CommandRouter(handler=handler)

    result = asyncio.run(
        router.route_update(
            {
                "update_id": 1,
                "message": {
                    "text": "/start",
                    "from": {"id": 1001},
                    "chat": {"id": 1001},
                },
            }
        )
    )

    assert result is not None
    assert result.success is True
    assert "🏠 Home Command" in result.message
    assert "CRITICAL ERROR" not in result.message
    assert "_keyboard" in result.payload


def test_command_router_help_uses_public_command_guidance() -> None:
    state_manager = SystemStateManager()
    config_manager = ConfigManager()
    handler = CommandHandler(
        state_manager=state_manager,
        config_manager=config_manager,
        mode="PAPER",
    )
    router = CommandRouter(handler=handler)

    result = asyncio.run(
        router.route_update(
            {
                "update_id": 2,
                "message": {"text": "/help", "from": {"id": 1001}, "chat": {"id": 1001}},
            }
        )
    )

    assert result is not None
    assert "❓ Help Center" in result.message
    assert "/start · /help · /status · /paper · /about · /risk · /account" in result.message


def test_command_router_status_routes_to_system_snapshot() -> None:
    state_manager = SystemStateManager()
    config_manager = ConfigManager()
    handler = CommandHandler(
        state_manager=state_manager,
        config_manager=config_manager,
        mode="PAPER",
    )
    router = CommandRouter(handler=handler)

    result = asyncio.run(
        router.route_update(
            {
                "update_id": 3,
                "message": {"text": "/status", "from": {"id": 1001}, "chat": {"id": 1001}},
            }
        )
    )

    assert result is not None
    assert "🧠 System Status" in result.message
    assert "paper-only boundary enforced" in result.message.lower()


def test_unknown_command_returns_help_style_fallback() -> None:
    state_manager = SystemStateManager()
    config_manager = ConfigManager()
    handler = CommandHandler(
        state_manager=state_manager,
        config_manager=config_manager,
        mode="PAPER",
    )
    router = CommandRouter(handler=handler)

    result = asyncio.run(
        router.route_update(
            {
                "update_id": 4,
                "message": {"text": "/unsupported", "from": {"id": 1001}, "chat": {"id": 1001}},
            }
        )
    )

    assert result is not None
    assert "❓ Help Center" in result.message
    assert "Unknown command '/unsupported'" in result.message


def test_start_deep_link_unlinked_reduces_onboarding_friction_guidance() -> None:
    state_manager = SystemStateManager()
    config_manager = ConfigManager()
    handler = CommandHandler(
        state_manager=state_manager,
        config_manager=config_manager,
        mode="PAPER",
    )
    router = CommandRouter(handler=handler)

    result = asyncio.run(
        router.route_update(
            {
                "update_id": 5,
                "message": {"text": "/start unlinked", "from": {"id": 1001}, "chat": {"id": 1001}},
            }
        )
    )

    assert result is not None
    assert "🏠 Home Command" in result.message
    assert "no account link" in result.message.lower()


@pytest.mark.parametrize(
    ("command", "marker"),
    [
        ("/paper", "paper mode is the only public runtime boundary"),
        ("/about", "public beta exposes runtime visibility"),
        ("/risk", "risk controls remain active in paper mode"),
        ("/account", "account-link guidance only"),
        ("/link", "account-link guidance only"),
    ],
)
def test_public_safe_commands_resolve_on_active_runtime_path(command: str, marker: str) -> None:
    state_manager = SystemStateManager()
    config_manager = ConfigManager()
    handler = CommandHandler(
        state_manager=state_manager,
        config_manager=config_manager,
        mode="PAPER",
    )
    router = CommandRouter(handler=handler)

    result = asyncio.run(
        router.route_update(
            {
                "update_id": 66,
                "message": {"text": command, "from": {"id": 1001}, "chat": {"id": 1001}},
            }
        )
    )

    assert result is not None
    assert marker in result.message.lower()


def test_reply_keyboard_routes_align_with_root_menu_actions() -> None:
    assert set(REPLY_MENU_MAP.values()) == {"dashboard", "portfolio", "markets", "settings", "help"}


def test_callback_router_route_home_callback_live_aligned_path() -> None:
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

    class _StubResponse:
        async def json(self) -> dict:
            return {"ok": True, "result": {"message_id": 22}}

    class _StubSession:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        async def post(self, url: str, json: dict) -> _StubResponse:
            self.calls.append((url, json))
            return _StubResponse()

    session = _StubSession()
    cq = {
        "id": "cb-home-1",
        "data": "action:home",
        "from": {"id": 1001},
        "message": {"chat": {"id": 1001}, "message_id": 777},
    }

    asyncio.run(router.route(session, cq))

    assert any("editMessageText" in url for url, _ in session.calls)
    edit_payloads = [body for url, body in session.calls if "editMessageText" in url]
    assert edit_payloads
    assert "🏠 Home Command" in edit_payloads[-1]["text"]
