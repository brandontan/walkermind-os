"""Reply keyboard builder — persistent bottom menu for Telegram hybrid UI."""
from __future__ import annotations

from typing import Any

ReplyKeyboardMarkup = dict[str, Any]

_TRADE_BTN = "📊 Trade"
_WALLET_BTN = "💼 Wallet"
_PERFORMANCE_BTN = "📈 Performance"
_EXPOSURE_BTN = "📉 Exposure"
_STRATEGY_BTN = "🧠 Strategy"
_HOME_BTN = "🏠 Home"

ROUTE_ACTIONS: tuple[str, ...] = (
    "trade",
    "wallet",
    "performance",
    "exposure",
    "strategy",
    "home",
)

REPLY_MENU_MAP: dict[str, str] = {
    _TRADE_BTN: "trade",
    _WALLET_BTN: "wallet",
    _PERFORMANCE_BTN: "performance",
    _EXPOSURE_BTN: "exposure",
    _STRATEGY_BTN: "strategy",
    _HOME_BTN: "home",
}

_MISSING_ACTIONS = tuple(action for action in ROUTE_ACTIONS if action not in REPLY_MENU_MAP.values())
if _MISSING_ACTIONS:
    raise RuntimeError(f"Reply keyboard action map missing required actions: {_MISSING_ACTIONS}")


def get_main_reply_keyboard() -> ReplyKeyboardMarkup:
    """Build the persistent bottom reply keyboard with premium layout."""
    return {
        "keyboard": [
            [_TRADE_BTN, _WALLET_BTN],
            [_PERFORMANCE_BTN, _EXPOSURE_BTN],
            [_STRATEGY_BTN, _HOME_BTN],
        ],
        "resize_keyboard": True,
    }



_REPLY_KB_READY_MSG = "✨ Premium dashboard ready. Tap a section to navigate."


def get_reply_keyboard_remove() -> dict[str, bool]:
    """Build a ``ReplyKeyboardRemove`` object to hide the bottom menu."""
    return {"remove_keyboard": True}
