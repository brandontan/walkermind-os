"""Single source of truth for the main reply-keyboard menu routing.

The reply-keyboard layout itself lives in ``bot.keyboards.main_menu`` —
this module owns the *button-text → handler* mapping that the dispatcher
text router consumes.

V6 layout (5 buttons, clean Telegram-native):

  🤖 Auto Trade   💼 Portfolio
  ⚙️ Settings     📊 Insights
  🛑 Stop Bot
"""
from __future__ import annotations

from typing import Awaitable, Callable

from telegram import Update
from telegram.ext import ContextTypes

from ..handlers import (
    dashboard, onboarding, positions,
    presets, settings as settings_handler,
    pnl_insights as pnl_insights_h,
    emergency,
)

HandlerFn = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


# Order mirrors keyboards.main_menu() rows for easy diffing.
MAIN_MENU_ROUTES: dict[str, HandlerFn] = {
    "🤖 Auto Trade":  presets.show_preset_picker,
    "💼 Portfolio":   positions.show_portfolio,
    "⚙️ Settings":    settings_handler.settings_hub_root,
    "📊 Insights":    pnl_insights_h.pnl_insights_command,
    "🛑 Stop Bot":    emergency.emergency_root,
}


def get_menu_route(text: str) -> HandlerFn | None:
    """Resolve a tapped reply-keyboard label to its handler, or ``None``
    if the text is not a registered top-level menu button."""
    return MAIN_MENU_ROUTES.get(text)
