"""Hermetic tests for UX Overhaul (telegram-ux-overhaul).

Parts tested:
  Part 1 — Main Menu: 3 buttons, correct layout
  Part 2 — TP/SL keyboards: preset buttons, custom, back
  Part 3 — Capital keyboards: preset buttons with $ amounts, max guard
  Part 4 — Strategy card keyboard: 4 cards + back, no internal names
  Part 6 — Insights: empty-state threshold (< 3 closed), format
  Part 7 — Settings hub keyboard: 6 items + back
  Part 8 — Auto-Trade: set_strategy_card backend mapping
  Part 9 — My Trades: formatting with TP/SL, no Dashboard button
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cb_data(kb) -> list[str]:
    """Extract all callback_data values from an InlineKeyboardMarkup."""
    data = []
    for row in kb.inline_keyboard:
        for btn in row:
            if hasattr(btn, "callback_data") and btn.callback_data:
                data.append(btn.callback_data)
    return data


def _btn_labels(kb) -> list[str]:
    """Extract all button text values from an InlineKeyboardMarkup."""
    labels = []
    for row in kb.inline_keyboard:
        for btn in row:
            labels.append(btn.text)
    return labels


# ---------------------------------------------------------------------------
# Part 1 — Main Menu layout
# ---------------------------------------------------------------------------

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
    # MVP v1: second row is Auto Trade + Copy Wallet
    row2 = [btn.text for btn in kb.keyboard[1]]
    assert "🤖 Auto Trade" in row2
    assert "👥 Copy Wallet" in row2


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


def test_tpsl_confirm_kb_has_back():
    kb = tpsl_confirm_kb()
    data = _cb_data(kb)
    assert "settings:hub" in data


# ---------------------------------------------------------------------------
# Part 3 — Capital preset keyboard
# ---------------------------------------------------------------------------


def test_capital_preset_kb_has_four_presets_and_custom():
    kb = capital_preset_kb(1000.0, "paper")
    data = _cb_data(kb)
    assert "cap_set:10" in data
    assert "cap_set:25" in data
    assert "cap_set:50" in data
    assert "cap_set:75" in data
    assert "cap_set:custom" in data


def test_capital_preset_kb_dollar_amounts():
    kb = capital_preset_kb(1000.0, "paper")
    labels = _btn_labels(kb)
    # 10% of $1000 = $100
    assert any("$100" in lbl for lbl in labels)
    # 25% of $1000 = $250
    assert any("$250" in lbl for lbl in labels)


def test_capital_preset_kb_has_back():
    kb = capital_preset_kb(500.0, "paper")
    data = _cb_data(kb)
    assert "settings:hub" in data


def test_capital_preset_kb_no_100_pct():
    """100% allocation is forbidden — no cap_set:100."""
    kb = capital_preset_kb(1000.0, "paper")
    data = _cb_data(kb)
    assert "cap_set:100" not in data
    assert "cap_set:95" not in data  # max preset is 75


# ---------------------------------------------------------------------------
# Part 4 — Strategy card keyboard
# ---------------------------------------------------------------------------

from projects.polymarket.crusaderbot.bot.keyboards import strategy_card_kb


def test_strategy_card_kb_has_four_cards():
    kb = strategy_card_kb()
    data = _cb_data(kb)
    assert "strategy:signal" in data
    assert "strategy:edge_finder" in data
    assert "strategy:momentum_reversal" in data
    assert "strategy:all" in data


def test_strategy_card_kb_has_back():
    kb = strategy_card_kb()
    data = _cb_data(kb)
    assert "strategy:back" in data


def test_strategy_card_kb_no_internal_names_exposed():
    """User-facing labels must not show 'value', 'R6b+', or 'momentum_reversal'."""
    kb = strategy_card_kb()
    labels = _btn_labels(kb)
    exposed = [lbl for lbl in labels if any(
        bad in lbl for bad in ["R6b+", " value", "momentum_reversal"]
    )]
    assert not exposed, f"Internal names exposed: {exposed}"


def test_strategy_card_kb_labels_user_friendly():
    kb = strategy_card_kb()
    labels = _btn_labels(kb)
    assert any("Edge Finder" in lbl for lbl in labels)
    assert any("Momentum" in lbl for lbl in labels)
    assert any("Signal" in lbl for lbl in labels)


# ---------------------------------------------------------------------------
# Part 4 — set_strategy_card backend mapping
# ---------------------------------------------------------------------------

from projects.polymarket.crusaderbot.bot.handlers.setup import _CARD_TO_BACKEND


def test_edge_finder_maps_to_value():
    assert _CARD_TO_BACKEND["edge_finder"] == ["value"]


def test_momentum_reversal_maps_correctly():
    assert _CARD_TO_BACKEND["momentum_reversal"] == ["momentum_reversal"]


def test_all_strategy_maps_all_three():
    result = _CARD_TO_BACKEND["all"]
    assert "signal" in result
    assert "value" in result
    assert "momentum_reversal" in result
    assert len(result) == 3


# ---------------------------------------------------------------------------
# Part 6 — Insights threshold
# ---------------------------------------------------------------------------

from projects.polymarket.crusaderbot.bot.handlers.pnl_insights import format_insights


def _base_data(**overrides) -> dict:
    defaults = {
        "total_closed": 10,
        "wins": 6,
        "losses": 4,
        "gross_wins": Decimal("30.00"),
        "gross_losses": Decimal("12.00"),
        "best_pnl": Decimal("8.50"),
        "worst_pnl": Decimal("-4.20"),
        "best_title": "Will Bitcoin hit 120K?",
        "worst_title": "US election 2028?",
        "avg_win": Decimal("5.00"),
        "avg_loss": Decimal("3.00"),
        "trades_7d": 3,
        "pnl_7d": Decimal("6.30"),
        "streak_dir": "win",
        "streak_len": 3,
    }
    defaults.update(overrides)
    return defaults


def test_insights_empty_state_below_threshold():
    text = format_insights(_base_data(total_closed=0))
    assert "Not enough data" in text or "3 closed" in text.lower() or "0 closed" in text


def test_insights_threshold_2_shows_not_enough():
    text = format_insights(_base_data(total_closed=2))
    assert "Not enough data" in text


def test_insights_threshold_3_shows_content():
    text = format_insights(_base_data(total_closed=3, wins=2, losses=1))
    assert "Insights" in text
    assert "Not enough data" not in text


def test_insights_threshold_shows_current_count():
    text = format_insights(_base_data(total_closed=2))
    assert "2" in text


# ---------------------------------------------------------------------------
# Part 6 — insights_kb has no Dashboard button
# ---------------------------------------------------------------------------

from projects.polymarket.crusaderbot.bot.keyboards import insights_kb


def test_insights_kb_no_dashboard_button():
    kb = insights_kb()
    labels = _btn_labels(kb)
    assert not any("Dashboard" in lbl for lbl in labels)


def test_insights_kb_has_refresh():
    kb = insights_kb()
    data = _cb_data(kb)
    assert "insights:refresh" in data
