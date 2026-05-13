"""Single source of truth for the main reply-keyboard menu routing.

The reply-keyboard layout itself lives in ``bot.keyboards.main_menu`` —
this module owns the *button-text → handler* mapping that the dispatcher
text router consumes. Centralising the mapping keeps button registration
and handler wiring in one place: adding a new top-level menu surface is a
one-line change here.

MVP UX v1 layout (hierarchy tree style):

  🏠 Dashboard   💼 Portfolio
  🤖 Auto Trade  👥 Copy Wallet
  📊 Insights    ⚙️ Settings
  🛑 Stop Bot
"""
from __future__ import annotations

from typing import Awaitable, Callable

from telegram import Update
from telegram.ext import ContextTypes

from ..handlers import (
    dashboard, emergency, positions,
    pnl_insights as pnl_insights_h,
    presets, settings as settings_handler,
    signal_following,
)

HandlerFn = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


# Order mirrors keyboards.main_menu() rows for easy diffing.
MAIN_MENU_ROUTES: dict[str, HandlerFn] = {
    "🏠 Dashboard":   dashboard.dashboard,
    "💼 Portfolio":   positions.show_portfolio,
    "🤖 Auto Trade":  presets.show_preset_picker,
    "👥 Copy Wallet": signal_following.signals_command,
    "📊 Insights":    pnl_insights_h.pnl_insights_command,
    "⚙️ Settings":    settings_handler.settings_hub_root,
    "🛑 Stop Bot":    emergency.emergency_root,
}


def get_menu_route(text: str) -> HandlerFn | None:
    """Resolve a tapped reply-keyboard label to its handler, or ``None``
    if the text is not a registered top-level menu button."""
    return MAIN_MENU_ROUTES.get(text)
