"""R12e Settings menu keyboards."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from . import grid_rows


def settings_menu(auto_redeem_mode: str) -> InlineKeyboardMarkup:
    """Root settings keyboard.

    Surfaces the current auto-redeem mode in the button label so the
    user does not have to drill down to see the active setting.
    """
    label = f"🏆 Auto-Redeem Mode: {auto_redeem_mode.title()}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(label, callback_data="settings:redeem")],
    ])


def autoredeem_settings_picker(current: str) -> InlineKeyboardMarkup:
    """2-column picker for instant / hourly / back."""
    def mark(m: str) -> str:
        return f"{'✅' if m == current else '◻️'} {m.title()}"
    buttons = [
        InlineKeyboardButton(mark("instant"),
                             callback_data="settings:redeem_set:instant"),
        InlineKeyboardButton(mark("hourly"),
                             callback_data="settings:redeem_set:hourly"),
        InlineKeyboardButton("⬅️ Back", callback_data="settings:menu"),
    ]
    return InlineKeyboardMarkup(grid_rows(buttons))
