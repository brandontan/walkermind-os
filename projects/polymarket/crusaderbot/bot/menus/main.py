"""Single source of truth for the main reply-keyboard menu routing.

The reply-keyboard layout itself lives in ``bot.keyboards.main_menu`` —
this module owns the *button-text → handler* mapping that the dispatcher
text router consumes.

V5 AUTOBOT layout (6 buttons, 2-column):

  🏠 Dashboard   💼 Portfolio
  🤖 Auto Mode   👥 Referrals
  ⚙️ Settings    ❓ Help
"""
from __future__ import annotations

from typing import Awaitable, Callable

from telegram import Update
from telegram.ext import ContextTypes

from ..handlers import (
    dashboard, onboarding, positions,
    presets, referral, settings as settings_handler,
)

HandlerFn = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


# Order mirrors keyboards.main_menu() rows for easy diffing.
MAIN_MENU_ROUTES: dict[str, HandlerFn] = {
    "🏠 Dashboard":  dashboard.dashboard,
    "💼 Portfolio":  positions.show_portfolio,
    "🤖 Auto Mode":  presets.show_preset_picker,
    "👥 Referrals":  referral.referral_command,
    "⚙️ Settings":   settings_handler.settings_hub_root,
    "❓ Help":        onboarding.help_handler,
}


def get_menu_route(text: str) -> HandlerFn | None:
    """Resolve a tapped reply-keyboard label to its handler, or ``None``
    if the text is not a registered top-level menu button."""
    return MAIN_MENU_ROUTES.get(text)
