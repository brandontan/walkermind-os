"""Persistent bottom-bar ReplyKeyboardMarkup — state-aware nav.

This is the ONLY file that produces ReplyKeyboardMarkup. All other
keyboards in this package produce InlineKeyboardMarkup.

Layout (5 buttons, 3 rows, max 2 cols):
    [ 📊 Dashboard    ] [ 💼 Portfolio     ]
    [ 🤖 {auto_label} ] [ ⚙️ Settings      ]
    [           ❓ Help              ]

State-aware labels:
- auto_label adapts to user state (Setup/Active/Resume)
- portfolio_label shows open position count when > 0
"""
from __future__ import annotations

from telegram import KeyboardButton, ReplyKeyboardMarkup


def main_menu(
    *,
    auto_on: bool = False,
    paused: bool = False,
    open_count: int = 0,
) -> ReplyKeyboardMarkup:
    """State-aware persistent bottom-bar keyboard.

    Args:
        auto_on: True if auto-trade is running or configured.
        paused: True if auto-trade is paused (overrides auto_on label).
        open_count: Number of open positions (shown in portfolio label).
    """
    # Auto-trade button — 3 states
    if paused:
        auto_label = "▶️ Resume"
    elif auto_on:
        auto_label = "🤖 Auto Mode"
    else:
        auto_label = "🤖 Setup Auto"

    # Portfolio button — show count badge
    portfolio_label = (
        f"💼 Trades ({open_count})" if open_count > 0
        else "💼 Portfolio"
    )

    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("📊 Dashboard"), KeyboardButton(portfolio_label)],
            [KeyboardButton(auto_label),     KeyboardButton("⚙️ Settings")],
            [KeyboardButton("❓ Help")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        is_persistent=True,
    )
