"""Inline keyboards for the strategy preset system (Phase 5C)."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ...domain.preset import RECOMMENDED_PRESET, list_presets


def preset_picker() -> InlineKeyboardMarkup:
    """Render one row per preset; recommended preset gets a ⭐ tag."""
    rows = []
    for p in list_presets():
        label = f"{p.emoji} {p.name}"
        if p.key == RECOMMENDED_PRESET:
            label = f"{label} ⭐"
        rows.append([InlineKeyboardButton(
            label, callback_data=f"preset:pick:{p.key}",
        )])
    return InlineKeyboardMarkup(rows)


def preset_confirm(preset_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Activate",
                              callback_data=f"preset:activate:{preset_key}")],
        [InlineKeyboardButton("✏️ Customize",
                              callback_data=f"preset:customize:{preset_key}")],
        [InlineKeyboardButton("← Back", callback_data="preset:picker")],
    ])


def preset_status(paused: bool) -> InlineKeyboardMarkup:
    """Status card controls. Pause / Resume swap based on the user's state."""
    pause_btn = (
        InlineKeyboardButton("▶️ Resume", callback_data="preset:resume")
        if paused
        else InlineKeyboardButton("⏸ Pause", callback_data="preset:pause")
    )
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Edit", callback_data="preset:edit"),
         InlineKeyboardButton("🔄 Switch", callback_data="preset:switch")],
        [pause_btn,
         InlineKeyboardButton("🛑 Stop", callback_data="preset:stop")],
    ])


def preset_switch_confirm() -> InlineKeyboardMarkup:
    """Switching deactivates the current preset before showing the picker."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes, switch",
                              callback_data="preset:switch_yes")],
        [InlineKeyboardButton("← Back", callback_data="preset:status")],
    ])


def preset_stop_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛑 Yes, stop",
                              callback_data="preset:stop_yes")],
        [InlineKeyboardButton("← Back", callback_data="preset:status")],
    ])
