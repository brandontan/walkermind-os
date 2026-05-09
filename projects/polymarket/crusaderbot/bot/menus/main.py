"""Single source of truth for the main reply-keyboard menu routing.

The reply-keyboard layout itself lives in ``bot.keyboards.main_menu`` —
this module owns the *button-text → handler* mapping that the dispatcher
text router consumes. Centralising the mapping keeps button registration
and handler wiring in one place: adding a new top-level menu surface is a
one-line change here.

Phase 5A reduces the main menu from 8 to 5 buttons:
  📊 Dashboard   🤖 Auto-Trade
  💰 Wallet      📈 My Trades
  🚨 Emergency

Settings and Help are now /settings and /help commands only.
Positions + Activity are merged into My Trades (📈 My Trades).
"""
from __future__ import annotations

from typing import Awaitable, Callable

from telegram import Update
from telegram.ext import ContextTypes

from ..handlers import (
    dashboard, emergency, positions, setup, wallet,
)

HandlerFn = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


# Order mirrors keyboards.main_menu() rows for easy diffing.
MAIN_MENU_ROUTES: dict[str, HandlerFn] = {
    "📊 Dashboard":  dashboard.dashboard,
    "🤖 Auto-Trade": setup.setup_root,
    "💰 Wallet":     wallet.wallet_root,
    "📈 My Trades":  positions.my_trades,
    "🚨 Emergency":  emergency.emergency_root,
}


def get_menu_route(text: str) -> HandlerFn | None:
    """Resolve a tapped reply-keyboard label to its handler, or ``None``
    if the text is not a registered top-level menu button."""
    return MAIN_MENU_ROUTES.get(text)
