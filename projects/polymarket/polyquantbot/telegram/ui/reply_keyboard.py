"""Reply keyboard builder — persistent bottom menu for Telegram hybrid UI.

The reply keyboard stays permanently visible at the bottom of the chat
(``resize_keyboard=True``) and serves as a navigation trigger only.

Each button press sends a plain text message that is intercepted by
``on_text_message()`` in the polling loop, mapped to an ``action:<name>``
string, and dispatched through ``CallbackRouter`` which edits the single
active inline message in-place (``editMessageText``).

Architecture:
    Reply keyboard  →  text message  →  on_text_message()
                                            ↓
                                     CallbackRouter.dispatch(action)
                                            ↓
                                     editMessageText  (single active message)

This separation ensures:
    - Bottom menu is always visible (reply keyboard).
    - All dynamic content lives in a single inline message (no stacking).
    - Zero logic duplication — reply buttons reuse the inline callback system.
"""
from __future__ import annotations

from typing import Any

# ── Type alias ─────────────────────────────────────────────────────────────────
ReplyKeyboardMarkup = dict[str, Any]

# ── Button labels ──────────────────────────────────────────────────────────────
_TRADE_BTN = "📊 Trade"
_WALLET_BTN = "💰 Wallet"
_SETTINGS_BTN = "⚙️ Settings"
_CONTROL_BTN = "▶ Control"

# ── Mapping: reply keyboard button text → callback action name ─────────────────
REPLY_MENU_MAP: dict[str, str] = {
    _TRADE_BTN:    "status",
    _WALLET_BTN:   "wallet",
    _SETTINGS_BTN: "settings",
    _CONTROL_BTN:  "control",
}


def get_main_reply_keyboard() -> ReplyKeyboardMarkup:
    """Build the persistent bottom reply keyboard.

    Layout::

        [📊 Trade]    [💰 Wallet  ]
        [⚙️ Settings] [▶ Control  ]

    Returns:
        Telegram ``ReplyKeyboardMarkup`` dict ready for the ``reply_markup``
        field in ``sendMessage``.
    """
    return {
        "keyboard": [
            [_TRADE_BTN,    _WALLET_BTN],
            [_SETTINGS_BTN, _CONTROL_BTN],
        ],
        "resize_keyboard": True,
    }

_REPLY_KB_READY_MSG = "🤖 Menu ready. Use the buttons below to navigate."


def get_reply_keyboard_remove() -> dict[str, bool]:
    """Build a ``ReplyKeyboardRemove`` object to hide the bottom menu.

    Returns:
        Telegram ``ReplyKeyboardRemove`` dict.
    """
    return {"remove_keyboard": True}
