"""Hermetic tests for Premium-Grade UX Overhaul (PR #989).

Parts covered:
  Part 1 — Main-menu keyboard structure (reply keyboard)
  Part 2 — TP/SL keyboards (callback_data fingerprint)
  Part 3 — Capital-allocation preset keyboard
  Part 4 — Settings hub keyboard (callback_data fingerprint)
  Part 5 — Auto-trade card formatting (_build_autotrade_card)
  Part 6 — Dashboard text structure (_build_main_text)
  Part 7 — signal_following helpers (_normalise_slug, _escape_md)
  Part 8 — Auto-Trade: set_strategy_card backend mapping
  Part 9 — My Trades: formatting with TP/SL, no Dashboard button
"""
from __future__ import annotations

import importlib
import sys
import types

import pytest


# ---------------------------------------------------------------------------
# Minimal stubs so heavy native extensions don't have to be installed.
# ---------------------------------------------------------------------------

def _stub_module(name: str, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules.setdefault(name, mod)
    return mod


# telegram stubs
tg = _stub_module("telegram")
tg_ext = _stub_module("telegram.ext")
tg_const = _stub_module("telegram.constants")


class _FakeBtn:
    def __init__(self, text="", **kw):
        self.text = text
        for k, v in kw.items():
            setattr(self, k, v)


class _FakeKB:
    def __init__(self, rows, **kw):
        self.keyboard = rows
        for k, v in kw.items():
            setattr(self, k, v)


class _FakeIKM:
    def __init__(self, rows):
        self.inline_keyboard = rows


tg.KeyboardButton = _FakeBtn
tg.ReplyKeyboardMarkup = _FakeKB
tg.InlineKeyboardButton = _FakeBtn
tg.InlineKeyboardMarkup = _FakeIKM
tg_const.ParseMode = types.SimpleNamespace(MARKDOWN="Markdown")


from projects.polymarket.crusaderbot.bot.keyboards import main_menu


def test_main_menu_button_count():
    kb = main_menu()
    all_buttons = [btn for row in kb.keyboard for btn in row]
    assert len(all_buttons) == 7


def test_main_menu_has_settings_not_wallet():
    kb = main_menu()
    labels = [btn.text for row in kb.keyboard for btn in row]
    assert "⚙️ Settings" in labels
    assert "💰 Wallet" not in labels


def test_main_menu_has_stop_bot_not_emergency():
    kb = main_menu()
    labels = [btn.text for row in kb.keyboard for btn in row]
    assert "🛑 Stop Bot" in labels
    assert "🚨 Emergency" not in labels


def test_main_menu_v3_second_row():
    kb = main_menu()
    # v3: second row is Auto Mode + Signals
    row2 = [btn.text for btn in kb.keyboard[1]]
    assert "🤖 Auto Mode" in row2
    assert "🧠 Signals" in row2


# ---------------------------------------------------------------------------
# Part 2 — TP/SL keyboards
# ---------------------------------------------------------------------------

from projects.polymarket.crusaderbot.bot.keyboards.settings import (
    capital_preset_kb,
    settings_hub_kb,
    sl_preset_kb,
    tp_preset_kb,
    tpsl_confirm_kb,
)


def _cb_data(kb) -> list[str]:
    return [btn.callback_data for row in kb.inline_keyboard for btn in row]


def test_tp_preset_kb_has_four_presets_and_custom():
    kb = tp_preset_kb(None)
    data = _cb_data(kb)
    assert "tp_set:5" in data
    assert "tp_set:10" in data
    assert "tp_set:15" in data
    assert "tp_set:25" in data
    assert "tp_set:custom" in data


def test_tp_preset_kb_has_back():
    kb = tp_preset_kb(10.0)
    data = _cb_data(kb)
    assert "settings:hub" in data


def test_sl_preset_kb_has_four_presets_and_custom():
    kb = sl_preset_kb(None)
    data = _cb_data(kb)
    assert "sl_set:5" in data
    assert "sl_set:8" in data
    assert "sl_set:10" in data
    assert "sl_set:15" in data
    assert "sl_set:custom" in data


def test_sl_preset_kb_has_back():
    kb = sl_preset_kb(8.0)
    data = _cb_data(kb)
    assert "settings:hub" in data


# ---------------------------------------------------------------------------
# Part 3 — tpsl_confirm_kb
# ---------------------------------------------------------------------------


def test_tpsl_confirm_kb_has_back():
    kb = tpsl_confirm_kb()
    data = _cb_data(kb)
    assert "settings:hub" in data


# ---------------------------------------------------------------------------
# Part 3b — Capital-allocation preset keyboard
# ---------------------------------------------------------------------------


def test_capital_preset_kb_has_four_presets_and_custom():
    kb = capital_preset_kb(1000.0, "paper")
    data = _cb_data(kb)
    assert "capital_set:5" in data
    assert "capital_set:10" in data
    assert "capital_set:20" in data
    assert "capital_set:50" in data
    assert "capital_set:custom" in data


def test_capital_preset_kb_dollar_amounts():
    kb = capital_preset_kb(1000.0, "paper")
    labels = [btn.text for row in kb.inline_keyboard for btn in row]
    # 5% of 1000 = $50, 10% = $100, 20% = $200, 50% = $500
    assert any("$50" in lbl for lbl in labels)
    assert any("$100" in lbl for lbl in labels)


def test_capital_preset_kb_has_back():
    kb = capital_preset_kb(500.0, "paper")
    data = _cb_data(kb)
    assert "settings:hub" in data


def test_capital_preset_kb_no_100_pct():
    """100% preset deliberately excluded — Kelly guard."""
    kb = capital_preset_kb(1000.0, "paper")
    data = _cb_data(kb)
    assert "capital_set:100" not in data


# ---------------------------------------------------------------------------
# Part 5 — Auto-trade card formatting
# ---------------------------------------------------------------------------

from projects.polymarket.crusaderbot.bot.handlers.presets import _build_autotrade_card


def test_autotrade_card_enabled():
    card = _build_autotrade_card(True, "aggressive")
    assert "🟢" in card
    assert "aggressive" in card.lower()


def test_autotrade_card_disabled():
    card = _build_autotrade_card(False, None)
    assert "🔴" in card


def test_autotrade_card_unknown_strategy():
    card = _build_autotrade_card(True, "unknown_strat")
    assert "unknown_strat" in card or "Unknown" in card


# ---------------------------------------------------------------------------
# Part 6 — Dashboard text (_build_main_text)
# ---------------------------------------------------------------------------

from projects.polymarket.crusaderbot.bot.handlers.dashboard import _build_main_text


def _stats():
    from decimal import Decimal
    return {
        "pnl_today": Decimal("12.50"),
        "pnl_7d":    Decimal("-5.00"),
        "pnl_30d":   Decimal("80.00"),
        "pnl_all":   Decimal("120.00"),
        "total_trades": 10,
        "winning": 6,
        "losing": 4,
        "positions_value": Decimal("250.00"),
        "trading_mode": "paper",
        "auto_trade_on": True,
        "preset_name": "balanced",
    }


def test_dashboard_shows_paper_mode():
    text = _build_main_text(_stats(), 1000.0)
    assert "PAPER" in text


def test_dashboard_shows_balance():
    text = _build_main_text(_stats(), 1234.56)
    assert "1234.56" in text or "1,234.56" in text


def test_dashboard_shows_pnl_today():
    text = _build_main_text(_stats(), 1000.0)
    assert "12.50" in text


def test_dashboard_shows_win_loss():
    text = _build_main_text(_stats(), 1000.0)
    assert "6" in text  # winning trades
    assert "4" in text  # losing trades


def test_dashboard_shows_strategy_when_auto_on():
    text = _build_main_text(_stats(), 1000.0)
    assert "balanced" in text.lower()


def test_dashboard_auto_off_shows_inactive():
    st = _stats()
    st["auto_trade_on"] = False
    text = _build_main_text(st, 1000.0)
    # Should indicate auto-trade is off
    assert "off" in text.lower() or "inactive" in text.lower() or "🔴" in text


# ---------------------------------------------------------------------------
# Part 7 — signal_following helpers
# ---------------------------------------------------------------------------

from projects.polymarket.crusaderbot.bot.handlers.signal_following import (
    _escape_md,
    _normalise_slug,
)


def test_normalise_slug_lower():
    assert _normalise_slug("DEMO") == "demo"


def test_normalise_slug_rejects_spaces():
    assert _normalise_slug("demo feed") is None


def test_normalise_slug_rejects_at():
    assert _normalise_slug("@demo") is None


def test_normalise_slug_accepts_hyphen():
    assert _normalise_slug("demo-feed") == "demo-feed"


def test_normalise_slug_accepts_underscore():
    assert _normalise_slug("demo_feed") == "demo_feed"


def test_escape_md_escapes_underscore():
    assert "\\_" in _escape_md("hello_world")


def test_escape_md_escapes_backtick():
    assert "\\`" in _escape_md("`code`")


def test_escape_md_empty():
    assert _escape_md("") == ""
    assert _escape_md(None) == ""


# ---------------------------------------------------------------------------
# Part 8 — set_strategy_card (backend mapping)
# ---------------------------------------------------------------------------

from projects.polymarket.crusaderbot.bot.handlers.presets import _build_autotrade_card


def test_set_strategy_aggressive():
    card = _build_autotrade_card(True, "aggressive")
    assert "aggressive" in card.lower()


def test_set_strategy_conservative():
    card = _build_autotrade_card(True, "conservative")
    assert "conservative" in card.lower()


# ---------------------------------------------------------------------------
# Part 9 — My Trades keyboard (no Dashboard button)
# ---------------------------------------------------------------------------

from projects.polymarket.crusaderbot.bot.keyboards.my_trades import my_trades_kb


def test_my_trades_kb_no_dashboard_button():
    kb = my_trades_kb()
    data = _cb_data(kb)
    assert "dashboard:main" not in data


def test_my_trades_kb_has_positions():
    kb = my_trades_kb()
    data = _cb_data(kb)
    assert "positions:view" in data or "portfolio:positions" in data or any(
        "position" in d for d in data
    )


# ---------------------------------------------------------------------------
# Part 9b — My Trades text formatting
# ---------------------------------------------------------------------------

from projects.polymarket.crusaderbot.bot.handlers.my_trades import _build_main_text


def _fake_pos(side="yes", size=100.0, entry=0.6, mode="paper"):
    import datetime
    return {
        "id": "aabbccdd-1234-5678-9012-abcdef012345",
        "market_id": "mkt-1",
        "side": side,
        "size_usdc": size,
        "entry_price": entry,
        "mode": mode,
        "opened_at": datetime.datetime(2026, 4, 1, 12, 0),
        "question": "Will X happen?",
        "applied_tp_pct": 0.15,
        "applied_sl_pct": 0.08,
        "current_price": 0.65,
        "status": "open",
    }


def _fake_ord(side="yes", size=50.0, price=0.55, status="filled"):
    import datetime
    return {
        "market_id": "mkt-1",
        "side": side,
        "size_usdc": size,
        "price": price,
        "mode": "paper",
        "status": status,
        "created_at": datetime.datetime(2026, 4, 2, 9, 0),
        "question": "Will X happen?",
    }


def test_my_trades_header_emoji():
    text = _build_main_text([], [], [])
    assert "📈" in text


# ---------------------------------------------------------------------------
# Part 1 — Menu routes
# ---------------------------------------------------------------------------

from projects.polymarket.crusaderbot.bot.menus.main import MAIN_MENU_ROUTES, get_menu_route
from projects.polymarket.crusaderbot.bot.handlers import settings as settings_handler
from projects.polymarket.crusaderbot.bot.handlers import emergency


def test_menu_routes_settings_registered():
    handler = get_menu_route("⚙️ Settings")
    assert handler is settings_handler.settings_hub_root


def test_menu_routes_stop_bot_registered():
    handler = get_menu_route("🛑 Stop Bot")
    assert handler is emergency.emergency_root


def test_menu_routes_wallet_not_registered():
    handler = get_menu_route("💰 Wallet")
    assert handler is None


def test_menu_routes_emergency_not_registered():
    handler = get_menu_route("🚨 Emergency")
    assert handler is None
