"""Phase 5D — 2-column grid + Copy/Auto Trade menu split.

Hermetic tests. No DB, no Telegram API calls.

Coverage:
  * grid_rows helper: even, odd, single, empty
  * main_menu: 6 buttons in 3 rows of 2 (ReplyKeyboard)
  * Copy Trade / Auto-Trade separation in MAIN_MENU_ROUTES
  * menu_copytrade_handler: renders placeholder, correct inline buttons
  * dashboard_nav: 3 buttons in 2-col layout
  * wallet_menu: 3 buttons in 2-col layout
  * emergency_menu: 3 buttons in 2-col layout
  * preset_picker: 2-col grid, 3 presets
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


# ---------- main_menu (ReplyKeyboard) ----------------------------------------

def test_main_menu_has_six_buttons():
    kb = main_menu()
    all_buttons = [btn for row in kb.keyboard for btn in row]
    assert len(all_buttons) == 6


def test_main_menu_layout_three_rows_of_two():
    kb = main_menu()
    assert len(kb.keyboard) == 3
    for row in kb.keyboard:
        assert len(row) == 2


def test_main_menu_contains_copy_trade_button():
    kb = main_menu()
    labels = [btn.text for row in kb.keyboard for btn in row]
    assert "🐋 Copy Trade" in labels


def test_main_menu_contains_auto_trade_button():
    kb = main_menu()
    labels = [btn.text for row in kb.keyboard for btn in row]
    assert "🤖 Auto-Trade" in labels


def test_main_menu_expected_buttons():
    kb = main_menu()
    labels = [btn.text for row in kb.keyboard for btn in row]
    assert set(labels) == {
        "📊 Dashboard",
        "🐋 Copy Trade",
        "🤖 Auto-Trade",
        "📈 My Trades",
        "💰 Wallet",
        "🚨 Emergency",
    }


# ---------- MAIN_MENU_ROUTES ------------------------------------------------

def test_copy_trade_route_registered():
    assert "🐋 Copy Trade" in MAIN_MENU_ROUTES


def test_auto_trade_route_registered():
    assert "🤖 Auto-Trade" in MAIN_MENU_ROUTES


def test_copy_trade_and_auto_trade_are_different_handlers():
    copy_handler = MAIN_MENU_ROUTES["🐋 Copy Trade"]
    auto_handler = MAIN_MENU_ROUTES["🤖 Auto-Trade"]
    assert copy_handler is not auto_handler


def test_all_six_main_menu_routes_present():
    expected = {
        "📊 Dashboard", "🐋 Copy Trade", "🤖 Auto-Trade",
        "📈 My Trades", "💰 Wallet", "🚨 Emergency",
    }
    assert expected <= set(MAIN_MENU_ROUTES.keys())


# ---------- menu_copytrade_handler ------------------------------------------

def test_menu_copytrade_handler_sends_placeholder(monkeypatch):
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
    asyncio.run(menu_copytrade_handler(update, ctx=SimpleNamespace()))
    assert len(replies) == 1
    assert "Copy Trade" in replies[0]
    assert "Coming soon" in replies[0] or "Phase 5E" in replies[0]


def test_menu_copytrade_handler_inline_buttons(monkeypatch):
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
    asyncio.run(menu_copytrade_handler(update, ctx=SimpleNamespace()))
    kb = sent_kw[0]["reply_markup"]
    cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "dashboard:main" in cbs
    assert "preset:picker" in cbs


# ---------- Other keyboard 2-col layouts ------------------------------------

def test_dashboard_nav_with_trades_is_two_col():
    kb = dashboard_nav(has_trades=True)
    # 3 buttons → row 0 has 2, row 1 has 1
    assert len(kb.inline_keyboard[0]) == 2
    assert len(kb.inline_keyboard[1]) == 1


def test_wallet_menu_is_two_col():
    kb = wallet_menu()
    # 3 buttons → row 0 has 2, row 1 has 1
    assert len(kb.inline_keyboard[0]) == 2
    assert len(kb.inline_keyboard[1]) == 1


def test_emergency_menu_is_two_col():
    kb = emergency_menu()
    # 4 buttons → 2 rows of 2
    assert len(kb.inline_keyboard) == 2
    assert len(kb.inline_keyboard[0]) == 2
    assert len(kb.inline_keyboard[1]) == 2


def test_preset_picker_is_two_col():
    kb = preset_picker()
    # 3 presets → row 0 has 2, row 1 has 1
    assert len(kb.inline_keyboard) == 2
    assert len(kb.inline_keyboard[0]) == 2
    assert len(kb.inline_keyboard[1]) == 1
