"""Reply keyboard builder — persistent bottom menu for Telegram hybrid UI."""
from __future__ import annotations

from typing import Any

# ── Type alias ─────────────────────────────────────────────────────────────────
ReplyKeyboardMarkup = dict[str, Any]

# ── Button labels ──────────────────────────────────────────────────────────────
_TRADE_BTN = "📊 Trade"
_WALLET_BTN = "💼 Wallet"
_PERFORMANCE_BTN = "📈 Performance"
_EXPOSURE_BTN = "📉 Exposure"
_SETTINGS_BTN = "⚙️ Settings"
_STRATEGY_BTN = "🧠 Strategy"
_REFRESH_BTN = "🔄 Refresh"
_HOME_BTN = "🏠 Home"

# ── Mapping: reply keyboard button text → callback action name ─────────────────
REPLY_MENU_MAP: dict[str, str] = {
    _TRADE_BTN: "status",
    _WALLET_BTN: "wallet",
    _PERFORMANCE_BTN: "performance",
    _EXPOSURE_BTN: "exposure",
    _SETTINGS_BTN: "settings",
    _STRATEGY_BTN: "strategy",
    _REFRESH_BTN: "refresh",
    _HOME_BTN: "back_main",
}


def get_main_reply_keyboard() -> ReplyKeyboardMarkup:
    """Build the persistent bottom reply keyboard with premium global layout."""
    return {
        "keyboard": [
            [_TRADE_BTN, _WALLET_BTN],
            [_PERFORMANCE_BTN, _EXPOSURE_BTN],
            [_SETTINGS_BTN, _STRATEGY_BTN],
            [_REFRESH_BTN, _HOME_BTN],
        ],
        "resize_keyboard": True,
    }


_REPLY_KB_READY_MSG = "✨ Premium dashboard ready. Tap a section to navigate."


def get_reply_keyboard_remove() -> dict[str, bool]:
    """Build a ``ReplyKeyboardRemove`` object to hide the bottom menu."""
    return {"remove_keyboard": True}
