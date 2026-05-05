"""Single source of truth for the main reply-keyboard menu routing.

The reply-keyboard layout itself lives in ``bot.keyboards.main_menu`` —
this module owns the *button-text → handler* mapping that the dispatcher
text router consumes. Centralising the mapping keeps button registration
and handler wiring in one place: adding a new top-level menu surface is a
one-line change here.

R12d adds the 📈 Positions slot which routes to the rich live position
monitor (``bot.handlers.positions.show_positions``) instead of the legacy
``dashboard.positions`` view (no P&L, no force-close confirmation).
"""
from __future__ import annotations

from typing import Awaitable, Callable

from telegram import Update
from telegram.ext import ContextTypes

from ..handlers import (
    dashboard, emergency, onboarding, positions,
    settings as settings_handler, setup, wallet,
)

HandlerFn = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


# Order is irrelevant for routing but mirrors keyboards.main_menu() rows
# so the two stay easy to diff at review time.
MAIN_MENU_ROUTES: dict[str, HandlerFn] = {
    "💰 Wallet": wallet.wallet_root,
    "🤖 Setup": setup.setup_root,
    "📊 Dashboard": dashboard.dashboard,
    "📈 Positions": positions.show_positions,
    "📋 Activity": dashboard.activity,
    "🛑 Emergency": emergency.emergency_root,
    "ℹ️ Help": onboarding.help_handler,
    "⚙️ Settings": settings_handler.settings_root,
}


def get_menu_route(text: str) -> HandlerFn | None:
    """Resolve a tapped reply-keyboard label to its handler, or ``None``
    if the text is not a registered top-level menu button."""
    return MAIN_MENU_ROUTES.get(text)
