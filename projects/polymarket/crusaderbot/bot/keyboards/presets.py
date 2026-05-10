"""Inline keyboards for the strategy preset system (Phase 5C/5D)."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ...domain.preset import RECOMMENDED_PRESET, list_presets
from . import grid_rows


def preset_picker() -> InlineKeyboardMarkup:
    """Render presets in a 2-column grid; recommended preset gets a ⭐ tag."""
    buttons = []
    for p in list_presets():
        label = f"{p.emoji} {p.name}"
        if p.key == RECOMMENDED_PRESET:
            label = f"{label} ⭐"
        buttons.append(InlineKeyboardButton(
            label, callback_data=f"preset:pick:{p.key}",
        ))
    return InlineKeyboardMarkup(grid_rows(buttons))


def preset_confirm(preset_key: str) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton("✅ Activate",
                             callback_data=f"preset:activate:{preset_key}"),
        InlineKeyboardButton("✏️ Customize",
                             callback_data=f"preset:customize:{preset_key}"),
        InlineKeyboardButton("← Back", callback_data="preset:picker"),
    ]
    return InlineKeyboardMarkup(grid_rows(buttons))


def preset_status(paused: bool) -> InlineKeyboardMarkup:
    """Status card controls. Pause / Resume swap based on the user's state."""
    pause_btn = (
        InlineKeyboardButton("▶️ Resume", callback_data="preset:resume")
        if paused
        else InlineKeyboardButton("⏸ Pause", callback_data="preset:pause")
    )
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Edit",   callback_data="preset:edit"),
         InlineKeyboardButton("🔄 Switch", callback_data="preset:switch")],
        [pause_btn,
         InlineKeyboardButton("🛑 Stop",  callback_data="preset:stop")],
    ])


def preset_switch_confirm() -> InlineKeyboardMarkup:
    """Switching deactivates the current preset before showing the picker."""
    buttons = [
        InlineKeyboardButton("✅ Yes, switch", callback_data="preset:switch_yes"),
        InlineKeyboardButton("← Back",         callback_data="preset:status"),
    ]
    return InlineKeyboardMarkup(grid_rows(buttons))


def preset_stop_confirm() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton("🛑 Yes, stop", callback_data="preset:stop_yes"),
        InlineKeyboardButton("← Back",       callback_data="preset:status"),
    ]
    return InlineKeyboardMarkup(grid_rows(buttons))
