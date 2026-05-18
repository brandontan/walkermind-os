"""Inline keyboards for the strategy preset system (Phase 5C/5D)."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ...domain.preset import RECOMMENDED_PRESET, list_presets
from . import grid_rows
from ._common import home_back_row


def preset_picker() -> InlineKeyboardMarkup:
    """Render presets in a 2-column grid; recommended preset gets a ⭐ tag."""
    buttons = []
    for p in list_presets():
        label = f"{p.emoji} {p.name} · {int(p.capital_pct * 100)}%"
        if p.key == RECOMMENDED_PRESET:
            label = f"{label} ⭐"
        buttons.append(InlineKeyboardButton(
            label, callback_data=f"preset:pick:{p.key}",
        ))
    return InlineKeyboardMarkup(grid_rows(buttons) + [home_back_row("dashboard:main")])


def preset_confirm(preset_key: str) -> InlineKeyboardMarkup:
    """Confirm screen: Activate + Customize (2-col) + Cancel below."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("▶ Start Auto Trade",
                                 callback_data=f"preset:activate:{preset_key}"),
            InlineKeyboardButton("🛠 Customize",
                                 callback_data=f"preset:customize:{preset_key}"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="preset:picker")],
    ])


def preset_status(paused: bool) -> InlineKeyboardMarkup:
    """Status card controls. Pause / Resume swap based on the user's state."""
    pause_btn = (
        InlineKeyboardButton("▶ Resume", callback_data="preset:resume")
        if paused
        else InlineKeyboardButton("⏸ Pause", callback_data="preset:pause")
    )
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛠 Edit",   callback_data="preset:edit"),
         InlineKeyboardButton("🔄 Switch", callback_data="preset:switch")],
        [pause_btn,
         InlineKeyboardButton("🛑 Stop",  callback_data="preset:stop")],
        home_back_row("dashboard:main"),
    ])


def preset_switch_confirm() -> InlineKeyboardMarkup:
    """Switching deactivates the current preset before showing the picker."""
    buttons = [
        InlineKeyboardButton("✅ Confirm Switch", callback_data="preset:switch_yes"),
        InlineKeyboardButton("❌ Cancel",          callback_data="preset:status"),
    ]
    return InlineKeyboardMarkup(grid_rows(buttons))


def preset_stop_confirm() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton("🛑 Yes, stop", callback_data="preset:stop_yes"),
        InlineKeyboardButton("❌ Cancel",    callback_data="preset:status"),
    ]
    return InlineKeyboardMarkup(grid_rows(buttons))


# ---------------------------------------------------------------------------
# Phase 5G — Customize wizard keyboards
# ---------------------------------------------------------------------------

def wizard_capital_kb() -> InlineKeyboardMarkup:
    """Step 1/5: Capital allocation — 2-col grid + Cancel."""
    pct_buttons = [
        InlineKeyboardButton("25%",  callback_data="customize:capital:25"),
        InlineKeyboardButton("50%",  callback_data="customize:capital:50"),
        InlineKeyboardButton("75%",  callback_data="customize:capital:75"),
        InlineKeyboardButton("100%", callback_data="customize:capital:100"),
    ]
    return InlineKeyboardMarkup(
        grid_rows(pct_buttons) + [[
            InlineKeyboardButton("❌ Cancel", callback_data="customize:cancel"),
        ]]
    )


def wizard_tp_kb() -> InlineKeyboardMarkup:
    """Step 2/5: Take Profit — 2-col grid + Custom + Back."""
    pct_buttons = [
        InlineKeyboardButton("+10%", callback_data="customize:tp:10"),
        InlineKeyboardButton("+15%", callback_data="customize:tp:15"),
        InlineKeyboardButton("+20%", callback_data="customize:tp:20"),
        InlineKeyboardButton("+30%", callback_data="customize:tp:30"),
    ]
    return InlineKeyboardMarkup(
        grid_rows(pct_buttons) + [[
            InlineKeyboardButton("✏️ Custom", callback_data="customize:tp:custom"),
            InlineKeyboardButton("⬅ Back",   callback_data="customize:back:capital"),
        ]]
    )


def wizard_sl_kb() -> InlineKeyboardMarkup:
    """Step 3/5: Stop Loss — 2-col grid + Custom + Back."""
    pct_buttons = [
        InlineKeyboardButton("-5%",  callback_data="customize:sl:5"),
        InlineKeyboardButton("-8%",  callback_data="customize:sl:8"),
        InlineKeyboardButton("-10%", callback_data="customize:sl:10"),
        InlineKeyboardButton("-15%", callback_data="customize:sl:15"),
    ]
    return InlineKeyboardMarkup(
        grid_rows(pct_buttons) + [[
            InlineKeyboardButton("✏️ Custom", callback_data="customize:sl:custom"),
            InlineKeyboardButton("⬅ Back",   callback_data="customize:back:tp"),
        ]]
    )


def wizard_review_kb() -> InlineKeyboardMarkup:
    """Step 5/5: Review — Save + Back."""
    buttons = [
        InlineKeyboardButton("▶ Start Auto Trade", callback_data="customize:save"),
        InlineKeyboardButton("⬅ Back",             callback_data="customize:back:sl"),
    ]
    return InlineKeyboardMarkup(grid_rows(buttons))


def wizard_custom_input_kb(back_target: str) -> InlineKeyboardMarkup:
    """Shown while user is typing a custom TP/SL value."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅ Back", callback_data=f"customize:back:{back_target}"),
    ]])


def wizard_done_kb() -> InlineKeyboardMarkup:
    """Success screen navigation."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("📊 Auto Trade Status", callback_data="preset:status"),
        InlineKeyboardButton("🏠 Home",              callback_data="dashboard:main"),
    ]])
