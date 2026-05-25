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
    dashboard,
    positions,
    presets,
    wallet,
)

HandlerFn = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


async def _group0_noop(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Sentinel for buttons whose response is already sent by a group=-1
    MessageHandler in dispatcher.py.

    Registered in MAIN_MENU_ROUTES so that _text_router still:
      (a) clears ctx.user_data['awaiting'] before returning, and
      (b) short-circuits before reaching wizard text-input handlers
          (copy_trade / settings / setup).

    Without this sentinel a Dashboard tap during an active wizard would fall
    through to e.g. copy_trade.text_input and trigger a stale-state error
    message even though the dashboard response was already sent by group=-1.
    """


MAIN_MENU_ROUTES: dict[str, HandlerFn] = {
    # V5 AUTOBOT fixed menu
    # "📊 Dashboard" and "💼 Portfolio" map to _group0_noop — the visible
    # response is sent by the group=-1 MessageHandler in dispatcher.py (fires
    # first).  The noop entry here lets _text_router clear ctx.user_data
    # ['awaiting'] and return early, preventing wizard text handlers from
    # misprocessing the tap (which would surface as a duplicate message).
    "📊 Dashboard":          _group0_noop,
    "💼 Portfolio":          _group0_noop,
    # Auto-mode taps are answered by the group=-1 MessageHandler in
    # dispatcher.py (routes to the MVP autotrade surface). Noop here so the
    # text router clears pending wizard state without sending a duplicate.
    "🤖 Auto Mode":          _group0_noop,
    "🤖 Setup Auto":         _group0_noop,
    "▶️ Resume":             _group0_noop,
    # Settings + Help responses are sent by the group=-1 MessageHandler in
    # dispatcher.py (MVP surface). Noop here so the text router clears pending
    # wizard state without the legacy handler firing a second message.
    "⚙️ Settings":           _group0_noop,
    "❓ Help":               _group0_noop,
    "💳 Wallet":             wallet.wallet_root_cb,
    # Backward-compat aliases (old state-driven labels)
    "📊 Active Monitor":     dashboard.dashboard,
    "🚀 Start Autobot":      presets.show_preset_picker,
    "⚙️ Configure Strategy": presets.show_preset_picker,
}


def get_menu_route(text: str) -> HandlerFn | None:
    """Resolve a tapped reply-keyboard label to its handler, or ``None``
    if the text is not a registered top-level menu button."""
    return MAIN_MENU_ROUTES.get(text)
