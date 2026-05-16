"""V5 AUTOBOT — menu layout + route coverage.

Updated for V5 fixed 5-button main menu (WARP/telegram-ux-v5-overhaul).
  * grid_rows helper
  * main_menu: 5 buttons in 3 rows (2+2+1) — fixed layout, no state-driving
  * MAIN_MENU_ROUTES: V5 routes + backward-compat aliases
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


# ---------- main_menu V5 AUTOBOT (ReplyKeyboard) -----------------------------

V5_MENU_BUTTONS = {
    "📊 Dashboard",
    "💼 Portfolio",
    "🤖 Auto Mode",
    "⚙️ Settings",
    "❓ Help",
}


def test_main_menu_has_five_buttons():
    # V5 fixed grid: 5 buttons regardless of bot state
    kb = main_menu(strategy_key="signal_sniper", auto_on=True)
    all_buttons = [btn for row in kb.keyboard for btn in row]
    assert len(all_buttons) == 5


def test_main_menu_layout_three_rows():
    # V5: 3 rows (2+2+1)
    kb = main_menu()
    assert len(kb.keyboard) == 3


def test_main_menu_row0_is_dashboard_and_portfolio():
    # V5: row0=[Dashboard, Portfolio]
    kb = main_menu()
    assert len(kb.keyboard[0]) == 2
    labels_row0 = {btn.text for btn in kb.keyboard[0]}
    assert labels_row0 == {"📊 Dashboard", "💼 Portfolio"}


def test_main_menu_row1_is_automode_and_settings():
    # V5: row1=[Auto Mode, Settings]
    kb = main_menu()
    assert len(kb.keyboard[1]) == 2
    labels_row1 = {btn.text for btn in kb.keyboard[1]}
    assert labels_row1 == {"🤖 Auto Mode", "⚙️ Settings"}


def test_main_menu_last_row_is_help():
    # V5: last row is [❓ Help] (single)
    kb = main_menu()
    assert len(kb.keyboard[-1]) == 1
    assert kb.keyboard[-1][0].text == "❓ Help"


def test_main_menu_v5_buttons():
    kb = main_menu(strategy_key="signal_sniper", auto_on=True)
    labels = {btn.text for row in kb.keyboard for btn in row}
    assert labels == V5_MENU_BUTTONS


def test_main_menu_signals_removed():
    kb = main_menu()
    labels = [btn.text for row in kb.keyboard for btn in row]
    assert "📡 Signal Feeds" not in labels


def test_main_menu_contains_portfolio_button():
    kb = main_menu()
    labels = [btn.text for row in kb.keyboard for btn in row]
    assert "💼 Portfolio" in labels


def test_main_menu_contains_settings_not_old_autotrade():
    # V5: Settings present; old "🤖 Auto-Trade" label gone
    kb = main_menu(strategy_key="signal_sniper", auto_on=True)
    labels = [btn.text for row in kb.keyboard for btn in row]
    assert "⚙️ Settings" in labels
    assert "📈 My Trades" not in labels
    assert "🤖 Auto-Trade" not in labels


def test_main_menu_fixed_layout_ignores_state():
    # V5: layout is identical regardless of auto_on / strategy_key
    kb_off = main_menu(strategy_key=None, auto_on=False)
    kb_on = main_menu(strategy_key="full_auto", auto_on=True)
    labels_off = {btn.text for row in kb_off.keyboard for btn in row}
    labels_on = {btn.text for row in kb_on.keyboard for btn in row}
    assert labels_off == labels_on == V5_MENU_BUTTONS


# ---------- MAIN_MENU_ROUTES V5 -------------------------------------------

def test_signals_route_removed():
    assert "📡 Signal Feeds" not in MAIN_MENU_ROUTES


def test_portfolio_route_registered():
    assert "💼 Portfolio" in MAIN_MENU_ROUTES


def test_v5_dashboard_route_registered():
    # V5: "📊 Dashboard" is now the primary route
    assert "📊 Dashboard" in MAIN_MENU_ROUTES


def test_v5_auto_mode_route_registered():
    assert "🤖 Auto Mode" in MAIN_MENU_ROUTES


def test_v5_help_route_registered():
    assert "❓ Help" in MAIN_MENU_ROUTES


def test_auto_trade_label_not_a_route():
    # Old "🤖 Auto-Trade" label gone
    assert "🤖 Auto-Trade" not in MAIN_MENU_ROUTES


def test_emergency_route_not_in_text_router():
    # Emergency in group=-1 dispatcher — not in text router
    assert "🚨 Emergency" not in MAIN_MENU_ROUTES


def test_all_v5_main_menu_routes_present():
    expected = {
        "📊 Dashboard", "💼 Portfolio", "🤖 Auto Mode",
        "⚙️ Settings", "❓ Help",
    }
    assert expected <= set(MAIN_MENU_ROUTES.keys())


def test_backward_compat_aliases_present():
    # Old labels still resolve so existing deep-links / cached keyboards don't break
    for alias in ("📊 Active Monitor", "🚀 Start Autobot", "⚙️ Configure Strategy"):
        assert alias in MAIN_MENU_ROUTES, f"backward-compat alias missing: {alias}"


def test_dashboard_and_portfolio_are_different_handlers():
    assert MAIN_MENU_ROUTES["📊 Dashboard"] is not MAIN_MENU_ROUTES["💼 Portfolio"]


def test_dashboard_and_settings_are_different_handlers():
    assert MAIN_MENU_ROUTES["📊 Dashboard"] is not MAIN_MENU_ROUTES["⚙️ Settings"]


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
    # 5 presets → 3 preset grid rows + 1 Back/Home nav row = 4 total
    assert len(kb.inline_keyboard) == 4
    assert len(kb.inline_keyboard[0]) == 2
    assert len(kb.inline_keyboard[1]) == 2
    assert len(kb.inline_keyboard[2]) == 1  # 5th preset alone
    # Nav row uses the new shared home_back_row helper:
    #   Back  → legacy dashboard:main target (preserves in-flight messages)
    #   Home  → new nav:home prefix routed by dispatcher._nav_cb
    nav = kb.inline_keyboard[3]
    assert len(nav) == 2
    callback_data = {btn.callback_data for btn in nav}
    assert callback_data == {"dashboard:main", "nav:home"}
