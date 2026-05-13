"""Single source of truth for the main reply-keyboard menu routing.

The reply-keyboard layout itself lives in ``bot.keyboards.main_menu`` —
this module owns the *button-text → handler* mapping that the dispatcher
text router consumes.

MVP Reset V1 layout (5 buttons):

  🏠 Dashboard   💼 Portfolio
  🤖 Auto Trade  ⚙️ Settings
  🛑 Stop Bot

Signal Feeds and Insights removed from main navigation.
"""
from __future__ import annotations

from typing import Awaitable, Callable

from telegram import Update
from telegram.ext import ContextTypes

from ..handlers import (
    dashboard, emergency, positions,
    presets, settings as settings_handler,
)

HandlerFn = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


# Order mirrors keyboards.main_menu() rows for easy diffing.
MAIN_MENU_ROUTES: dict[str, HandlerFn] = {
    "🏠 Dashboard":   dashboard.dashboard,
    "💼 Portfolio":   positions.show_portfolio,
    "🤖 Auto Trade":  presets.show_preset_picker,
    "⚙️ Settings":    settings_handler.settings_hub_root,
    "🛑 Stop Bot":    emergency.emergency_root,
}

# MVP RESET V1 — deprecated UI flow
# "📡 Signal Feeds" and "📊 Insights" removed from main navigation.
# Handlers remain reachable via direct callbacks but not via reply keyboard.


def get_menu_route(text: str) -> HandlerFn | None:
    """Resolve a tapped reply-keyboard label to its handler, or ``None``
    if the text is not a registered top-level menu button."""
    return MAIN_MENU_ROUTES.get(text)
