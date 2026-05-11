"""Single source of truth for the main reply-keyboard menu routing.

The reply-keyboard layout itself lives in ``bot.keyboards.main_menu`` —
this module owns the *button-text → handler* mapping that the dispatcher
text router consumes. Centralising the mapping keeps button registration
and handler wiring in one place: adding a new top-level menu surface is a
one-line change here.

UX Overhaul layout:

  📊 Dashboard   📈 My Trades
  🤖 Auto-Trade  🐋 Copy Trade
  ⚙️ Settings    🛑 Stop Bot

Settings = hub for Wallet + TP/SL + Capital + Risk + Notifications + Mode.
Copy Trade promoted to top-level (was nested inside Auto-Trade in earlier phases).
Emergency renamed to "🛑 Stop Bot".
"""
from __future__ import annotations

from typing import Awaitable, Callable

from telegram import Update
from telegram.ext import ContextTypes

from ..handlers import (
    copy_trade, dashboard, emergency, my_trades as my_trades_h,
    settings as settings_handler, setup,
)

HandlerFn = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


# Order mirrors keyboards.main_menu() rows for easy diffing.
MAIN_MENU_ROUTES: dict[str, HandlerFn] = {
    "📊 Dashboard":  dashboard.dashboard,
    "📈 My Trades":  my_trades_h.my_trades,
    "🤖 Auto-Trade": setup.setup_root,
    "🐋 Copy Trade": copy_trade.menu_copytrade_handler,
    "⚙️ Settings":   settings_handler.settings_hub_root,
    "🛑 Stop Bot":   emergency.emergency_root,
}


def get_menu_route(text: str) -> HandlerFn | None:
    """Resolve a tapped reply-keyboard label to its handler, or ``None``
    if the text is not a registered top-level menu button."""
    return MAIN_MENU_ROUTES.get(text)
