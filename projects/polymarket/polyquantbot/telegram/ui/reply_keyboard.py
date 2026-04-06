"""Reply keyboard builder — persistent bottom menu for Telegram hybrid UI."""
from __future__ import annotations

from typing import Any

ReplyKeyboardMarkup = dict[str, Any]

_DASHBOARD_BTN = "📊 Dashboard"
_PORTFOLIO_BTN = "💼 Portfolio"
_MARKETS_BTN = "🎯 Markets"
_SETTINGS_BTN = "⚙️ Settings"
_HELP_BTN = "❓ Help"

ROUTE_ACTIONS: tuple[str, ...] = (
    "dashboard",
    "portfolio",
    "markets",
    "settings",
    "help",
)

REPLY_MENU_MAP: dict[str, str] = {
    _DASHBOARD_BTN: "dashboard",
    _PORTFOLIO_BTN: "portfolio",
    _MARKETS_BTN: "markets",
    _SETTINGS_BTN: "settings",
    _HELP_BTN: "help",
}

_MISSING_ACTIONS = tuple(action for action in ROUTE_ACTIONS if action not in REPLY_MENU_MAP.values())
if _MISSING_ACTIONS:
    raise RuntimeError(f"Reply keyboard action map missing required actions: {_MISSING_ACTIONS}")


def get_main_reply_keyboard() -> ReplyKeyboardMarkup:
    """Build the persistent bottom reply keyboard with premium layout."""
    return {
        "keyboard": [
            [_DASHBOARD_BTN, _PORTFOLIO_BTN],
            [_MARKETS_BTN, _SETTINGS_BTN],
            [_HELP_BTN],
        ],
        "resize_keyboard": True,
    }



_REPLY_KB_READY_MSG = "✨ Premium dashboard ready. Tap a section to navigate."


def get_reply_keyboard_remove() -> dict[str, bool]:
    """Build a ``ReplyKeyboardRemove`` object to hide the bottom menu."""
    return {"remove_keyboard": True}
