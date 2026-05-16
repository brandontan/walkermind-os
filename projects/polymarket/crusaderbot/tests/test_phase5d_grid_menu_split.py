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


# ---------- main_menu MVP (ReplyKeyboard) ------------------------------------

# MVP state-driven main_menu — "running bot" state labels
MVP_RUNNING_BUTTONS = {
    "📊 Active Monitor",
    "💼 Portfolio",
    "⚙️ Settings",
    "🚨 Emergency",
}


def test_main_menu_has_four_buttons():
    # Running state: 4 buttons in 1+2+1 layout
    kb = main_menu(strategy_key="signal_sniper", auto_on=True)
    all_buttons = [btn for row in kb.keyboard for btn in row]
    assert len(all_buttons) == 4


def test_main_menu_layout_three_rows():
    # All states: 3 rows
    kb = main_menu()
    assert len(kb.keyboard) == 3


def test_main_menu_running_row0_is_single_active_monitor():
    # Running state: row0=[Active Monitor] (single CTA)
    kb = main_menu(strategy_key="signal_sniper", auto_on=True)
    assert len(kb.keyboard[0]) == 1
    assert kb.keyboard[0][0].text == "📊 Active Monitor"
    # row1=[Portfolio, Settings] (pair)
    assert len(kb.keyboard[1]) == 2


def test_main_menu_last_row_has_emergency():
    # All states: last row is [🚨 Emergency]
    kb = main_menu()
    assert len(kb.keyboard[-1]) == 1
    assert kb.keyboard[-1][0].text == "🚨 Emergency"


def test_main_menu_expected_running_buttons():
    kb = main_menu(strategy_key="signal_sniper", auto_on=True)
    labels = {btn.text for row in kb.keyboard for btn in row}
    assert labels == MVP_RUNNING_BUTTONS


def test_main_menu_signals_removed():
    kb = main_menu()
    labels = [btn.text for row in kb.keyboard for btn in row]
    assert "📡 Signal Feeds" not in labels


def test_main_menu_contains_portfolio_button():
    kb = main_menu()
    labels = [btn.text for row in kb.keyboard for btn in row]
    assert "💼 Portfolio" in labels


def test_main_menu_running_has_settings_not_my_trades():
    # Running state: Settings is present; My Trades and Auto-Trade are NOT on main menu
    kb = main_menu(strategy_key="signal_sniper", auto_on=True)
    labels = [btn.text for row in kb.keyboard for btn in row]
    assert "⚙️ Settings" in labels
    assert "📈 My Trades" not in labels
    assert "🤖 Auto-Trade" not in labels


def test_main_menu_contains_emergency():
    # All states: Emergency is always present in last row
    kb = main_menu()
    labels = [btn.text for row in kb.keyboard for btn in row]
    assert "🚨 Emergency" in labels


# ---------- MAIN_MENU_ROUTES V5 -------------------------------------------

def test_signals_route_removed():
    assert "📡 Signal Feeds" not in MAIN_MENU_ROUTES


def test_portfolio_route_registered():
    assert "💼 Portfolio" in MAIN_MENU_ROUTES


def test_active_monitor_route_registered():
    # Bot-running state: Active Monitor routes to dashboard
    assert "📊 Active Monitor" in MAIN_MENU_ROUTES


def test_dashboard_label_not_a_route():
    # "📊 Dashboard" is no longer a reply-keyboard button in any state
    assert "📊 Dashboard" not in MAIN_MENU_ROUTES


def test_auto_trade_not_a_route():
    # Auto-Trade lives in the inline dashboard keyboard, not the reply keyboard
    assert "🤖 Auto-Trade" not in MAIN_MENU_ROUTES


def test_emergency_route_not_in_text_router():
    # Emergency moved to group=-1 dispatcher handler so it fires before
    # ConversationHandler text states; it is no longer in MAIN_MENU_ROUTES.
    assert "🚨 Emergency" not in MAIN_MENU_ROUTES


def test_all_main_menu_routes_present():
    expected = {
        "📊 Active Monitor", "💼 Portfolio", "⚙️ Settings",
        "🚀 Start Autobot", "⚙️ Configure Strategy",
    }
    assert expected <= set(MAIN_MENU_ROUTES.keys())


def test_active_monitor_and_portfolio_are_different_handlers():
    monitor_handler = MAIN_MENU_ROUTES["📊 Active Monitor"]
    portfolio_handler = MAIN_MENU_ROUTES["💼 Portfolio"]
    assert monitor_handler is not portfolio_handler


def test_active_monitor_and_settings_are_different_handlers():
    monitor_handler = MAIN_MENU_ROUTES["📊 Active Monitor"]
    settings_handler = MAIN_MENU_ROUTES["⚙️ Settings"]
    assert monitor_handler is not settings_handler


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
