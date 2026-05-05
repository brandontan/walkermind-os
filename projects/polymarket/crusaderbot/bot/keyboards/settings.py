"""R12e Settings menu keyboards.

The blueprint §5 promises a top-level ``⚙️ Settings`` surface separate
from the strategy/risk ``🤖 Setup`` flow. Phase 1 ships only the
auto-redeem mode toggle — the other rows (Notifications, 2FA, Language,
Privacy, Advanced) are deferred to later lanes per blueprint §13 Phase 9
and are explicitly not in scope for this lane.

Callback prefixes consumed by ``bot.handlers.settings``:

  settings:menu                — repaint the root menu
  settings:redeem              — open the auto-redeem picker
  settings:redeem_set:<mode>   — apply a redeem-mode choice (instant|hourly)
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


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
    """Two-button picker for instant vs hourly auto-redeem mode."""
    def mark(m: str) -> str:
        return f"{'✅' if m == current else '◻️'} {m.title()}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(mark("instant"),
                              callback_data="settings:redeem_set:instant")],
        [InlineKeyboardButton(mark("hourly"),
                              callback_data="settings:redeem_set:hourly")],
        [InlineKeyboardButton("⬅️ Back",
                              callback_data="settings:menu")],
    ])
