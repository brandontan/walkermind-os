"""Single source of truth for the main reply-keyboard menu routing.

The reply-keyboard layout itself lives in ``bot.keyboards.main_menu`` —
this module owns the *button-text → handler* mapping that the dispatcher
text router consumes.

State-driven layout (3 states):

  No strategy:     ⚙️ Configure Strategy
                   💼 Portfolio   ⚙️ Settings
                   🚨 Emergency

  Strategy set:    🚀 Start Autobot
                   💼 Portfolio   ⚙️ Settings
                   🚨 Emergency

  Bot running:     📊 Active Monitor
                   💼 Portfolio   ⚙️ Settings
                   🚨 Emergency
"""
from __future__ import annotations

from typing import Awaitable, Callable

from telegram import Update
from telegram.ext import ContextTypes

from ..handlers import (
    dashboard, emergency,
    onboarding,
    positions,
    presets, settings as settings_handler,
)

HandlerFn = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


MAIN_MENU_ROUTES: dict[str, HandlerFn] = {
    # V5 AUTOBOT fixed menu
    "📊 Dashboard":          dashboard.dashboard,
    "💼 Portfolio":          positions.show_portfolio,
    "🤖 Auto Mode":          presets.show_preset_picker,
    "⚙️ Settings":           settings_handler.settings_hub_root,
    "❓ Help":               onboarding.help_handler,
    # Backward-compat aliases (old state-driven labels)
    "📊 Active Monitor":     dashboard.dashboard,
    "🚀 Start Autobot":      presets.show_preset_picker,
    "⚙️ Configure Strategy": presets.show_preset_picker,
}


def get_menu_route(text: str) -> HandlerFn | None:
    """Resolve a tapped reply-keyboard label to its handler, or ``None``
    if the text is not a registered top-level menu button."""
    return MAIN_MENU_ROUTES.get(text)
