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

  Bot running:     📊 Dashboard   🤖 Auto-Trade
                   💼 Portfolio   📈 My Trades
                   🚨 Emergency
"""
from __future__ import annotations

from typing import Awaitable, Callable

from telegram import Update
from telegram.ext import ContextTypes

from ..handlers import (
    dashboard, emergency,
    my_trades as my_trades_h,
    positions,
    presets, settings as settings_handler,
)

HandlerFn = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


MAIN_MENU_ROUTES: dict[str, HandlerFn] = {
    # Bot running state
    "📊 Dashboard":          dashboard.dashboard,
    "🤖 Auto-Trade":         presets.show_preset_picker,
    "💼 Portfolio":          positions.show_portfolio,
    "📈 My Trades":          my_trades_h.my_trades,
    "🚨 Emergency":          emergency.emergency_root,
    # Strategy set, bot OFF state
    "🚀 Start Autobot":      presets.show_preset_picker,
    # No strategy state
    "⚙️ Configure Strategy": presets.show_preset_picker,
    # Secondary nav (shared across states)
    "⚙️ Settings":           settings_handler.settings_hub_root,
}


def get_menu_route(text: str) -> HandlerFn | None:
    """Resolve a tapped reply-keyboard label to its handler, or ``None``
    if the text is not a registered top-level menu button."""
    return MAIN_MENU_ROUTES.get(text)
