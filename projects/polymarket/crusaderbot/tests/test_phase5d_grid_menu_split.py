"""Phase 5D / UX-V3 — menu layout + route coverage.

Updated for v3 7-button main menu (WARP/TELEGRAM-UX-V3).
Preserves full coverage intent of original Phase 5D suite:
  * grid_rows helper
  * main_menu: 7 buttons in 4 rows (3x2 + 1x1)
  * MAIN_MENU_ROUTES: all 7 v3 routes registered
  * Copy Trade route accessible via settings/secondary nav (not root)
  * menu_copytrade_handler: placeholder + inline buttons
  * dashboard_nav, wallet_menu, emergency_menu, preset_picker 2-col layouts
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from projects.polymarket.crusaderbot.bot.keyboards import (
    dashboard_nav, emergency_menu, grid_rows, main_menu, wallet_menu,
)
from projects.polymarket.crusaderbot.bot.keyboards.presets import preset_picker
from projects.polymarket.crusaderbot.bot.menus.main import MAIN_MENU_ROUTES


# ---------- grid_rows helper ------------------------------------------------

def test_grid_rows_even():
    buttons = list(range(4))
    rows = grid_rows(buttons)
    assert rows == [[0, 1], [2, 3]]


def test_grid_rows_odd():
    buttons = list(range(3))
    rows = grid_rows(buttons)
    assert rows == [[0, 1], [2]]


def test_grid_rows_single():
    rows = grid_rows([99])
    assert rows == [[99]]


def test_grid_rows_empty():
    assert grid_rows([]) == []


def test_grid_rows_custom_cols():
    buttons = list(range(6))
    rows = grid_rows(buttons, cols=3)
    assert rows == [[0, 1, 2], [3, 4, 5]]


# ---------- main_menu v3 (ReplyKeyboard) ------------------------------------

V3_BUTTONS = {
    "🏠 Dashboard",
    "💼 Portfolio",
    "🤖 Auto Trade",
    "📡 Signal Feeds",
    "📊 Insights",
    "⚙️ Settings",
    "🛑 Stop Bot",
}


def test_main_menu_has_seven_buttons():
    kb = main_menu()
    all_buttons = [btn for row in kb.keyboard for btn in row]
    assert len(all_buttons) == 7


def test_main_menu_layout_four_rows():
    """v3: 3 rows of 2 + 1 row of 1 = 4 rows total."""
    kb = main_menu()
    assert len(kb.keyboard) == 4


def test_main_menu_first_three_rows_are_pairs():
    kb = main_menu()
    for row in kb.keyboard[:3]:
        assert len(row) == 2


def test_main_menu_last_row_is_single():
    kb = main_menu()
    assert len(kb.keyboard[-1]) == 1


def test_main_menu_expected_v3_buttons():
    kb = main_menu()
    labels = {btn.text for row in kb.keyboard for btn in row}
    assert labels == V3_BUTTONS


def test_main_menu_contains_signals_button():
    kb = main_menu()
    labels = [btn.text for row in kb.keyboard for btn in row]
    assert "📡 Signal Feeds" in labels


def test_main_menu_contains_portfolio_button():
    kb = main_menu()
    labels = [btn.text for row in kb.keyboard for btn in row]
    assert "💼 Portfolio" in labels


def test_main_menu_contains_insights_button():
    kb = main_menu()
    labels = [btn.text for row in kb.keyboard for btn in row]
    assert "📊 Insights" in labels


def test_main_menu_contains_stop_bot_button():
    kb = main_menu()
    labels = [btn.text for row in kb.keyboard for btn in row]
    assert "🛑 Stop Bot" in labels


# ---------- MAIN_MENU_ROUTES v3 --------------------------------------------

def test_signals_route_registered():
    assert "📡 Signal Feeds" in MAIN_MENU_ROUTES


def test_portfolio_route_registered():
    assert "💼 Portfolio" in MAIN_MENU_ROUTES


def test_insights_route_registered():
    assert "📊 Insights" in MAIN_MENU_ROUTES


def test_auto_mode_route_registered():
    assert "🤖 Auto Trade" in MAIN_MENU_ROUTES


def test_all_seven_main_menu_routes_present():
    expected = {
        "🏠 Dashboard", "💼 Portfolio", "🤖 Auto Trade",
        "📡 Signal Feeds", "📊 Insights", "⚙️ Settings", "🛑 Stop Bot",
    }
    assert expected <= set(MAIN_MENU_ROUTES.keys())


def test_signals_and_portfolio_are_different_handlers():
    signals_handler = MAIN_MENU_ROUTES["📡 Signal Feeds"]
    portfolio_handler = MAIN_MENU_ROUTES["💼 Portfolio"]
    assert signals_handler is not portfolio_handler


def test_auto_mode_and_dashboard_are_different_handlers():
    auto_handler = MAIN_MENU_ROUTES["🤖 Auto Trade"]
    dash_handler = MAIN_MENU_ROUTES["🏠 Dashboard"]
    assert auto_handler is not dash_handler


# ---------- menu_copytrade_handler (via settings/secondary nav) ------------

def test_menu_copytrade_handler_sends_placeholder(monkeypatch):
    """Copy Trade is accessible; renders placeholder when no tasks."""
    from unittest.mock import patch, AsyncMock as _AsyncMock
    from projects.polymarket.crusaderbot.bot.handlers.copy_trade import (
        menu_copytrade_handler,
    )
    replies = []
    sent_kw = []

    async def capture(text, **kw):
        replies.append(text)
        sent_kw.append(kw)

    msg = SimpleNamespace(reply_text=AsyncMock(side_effect=capture))
    update = SimpleNamespace(
        message=msg,
        callback_query=None,
        effective_user=SimpleNamespace(id=1, username="u"),
    )
    fake_user = {"id": "00000000-0000-0000-0000-000000000001", "access_tier": 2}
    with patch(
        "projects.polymarket.crusaderbot.bot.handlers.copy_trade.upsert_user",
        return_value=fake_user,
    ), patch(
        "projects.polymarket.crusaderbot.bot.handlers.copy_trade._list_copy_tasks",
        return_value=[],
    ):
        asyncio.run(menu_copytrade_handler(update, ctx=SimpleNamespace()))
    assert len(replies) == 1
    assert "Copy Trade" in replies[0]


def test_menu_copytrade_handler_inline_buttons(monkeypatch):
    """Copy Trade empty-state shows [Add Wallet] and [Discover] buttons."""
    from unittest.mock import patch, AsyncMock as _AsyncMock
    from projects.polymarket.crusaderbot.bot.handlers.copy_trade import (
        menu_copytrade_handler,
    )
    sent_kw = []

    async def capture(text, **kw):
        sent_kw.append(kw)

    msg = SimpleNamespace(reply_text=AsyncMock(side_effect=capture))
    update = SimpleNamespace(
        message=msg,
        callback_query=None,
        effective_user=SimpleNamespace(id=1, username="u"),
    )
    fake_user = {"id": "00000000-0000-0000-0000-000000000001", "access_tier": 2}
    with patch(
        "projects.polymarket.crusaderbot.bot.handlers.copy_trade.upsert_user",
        return_value=fake_user,
    ), patch(
        "projects.polymarket.crusaderbot.bot.handlers.copy_trade._list_copy_tasks",
        return_value=[],
    ):
        asyncio.run(menu_copytrade_handler(update, ctx=SimpleNamespace()))
    kb = sent_kw[0]["reply_markup"]
    cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "copytrade:add" in cbs
    assert "copytrade:discover" in cbs


# ---------- Other keyboard 2-col layouts ------------------------------------

def test_dashboard_nav_with_trades_is_two_col():
    kb = dashboard_nav(has_trades=True)
    assert len(kb.inline_keyboard) == 2
    assert len(kb.inline_keyboard[0]) == 2
    assert len(kb.inline_keyboard[1]) == 2


def test_wallet_menu_is_two_col():
    kb = wallet_menu()
    assert len(kb.inline_keyboard[0]) == 2
    assert len(kb.inline_keyboard[1]) == 1


def test_emergency_menu_is_two_col():
    kb = emergency_menu()
    assert len(kb.inline_keyboard) == 2
    assert len(kb.inline_keyboard[0]) == 2
    assert len(kb.inline_keyboard[1]) == 2


def test_preset_picker_is_two_col():
    kb = preset_picker()
    # 2 preset grid rows + 1 Back/Home nav row
    assert len(kb.inline_keyboard) == 3
    assert len(kb.inline_keyboard[0]) == 2
    assert len(kb.inline_keyboard[1]) == 1
    # Nav row: Back and Home both use dashboard:main (no dead noop:refresh)
    nav = kb.inline_keyboard[2]
    assert len(nav) == 2
    assert all(btn.callback_data == "dashboard:main" for btn in nav)
