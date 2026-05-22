"""Shared keyboard helpers — back / home / refresh / cancel / confirm rows."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup


BACK = InlineKeyboardButton("⬅ Back", callback_data="nav:back")
HOME = InlineKeyboardButton("🏠 Home", callback_data="nav:home")
REFRESH = InlineKeyboardButton("🔄 Refresh", callback_data="nav:refresh")
CANCEL = InlineKeyboardButton("❌ Cancel", callback_data="nav:cancel")
NOOP = InlineKeyboardButton("·", callback_data="nav:noop")


def back_row() -> list[InlineKeyboardButton]:
    return [BACK]


def home_row() -> list[InlineKeyboardButton]:
    return [HOME]


def back_home_row() -> list[InlineKeyboardButton]:
    return [BACK, HOME]


def refresh_home_row() -> list[InlineKeyboardButton]:
    return [REFRESH, HOME]


def confirm_cancel_row(
    confirm_label: str = "✅ Confirm",
    confirm_data: str = "nav:confirm",
    cancel_label: str = "❌ Cancel",
    cancel_data: str = "nav:cancel",
) -> list[InlineKeyboardButton]:
    return [
        InlineKeyboardButton(confirm_label, callback_data=confirm_data),
        InlineKeyboardButton(cancel_label, callback_data=cancel_data),
    ]


def main_menu_kb(
    auto_on: bool = False,
    paused: bool = False,
    open_count: int = 0,
    configured: bool = False,
) -> ReplyKeyboardMarkup:
    """Persistent bottom navigation keyboard (blueprint v7 Section 3)."""
    if paused:
        auto_label = "▶️ Resume"
    elif auto_on or configured:
        auto_label = "🤖 Auto Mode"
    else:
        auto_label = "🤖 Setup Auto"
    portfolio_label = f"💼 Trades ({open_count})" if open_count > 0 else "💼 Portfolio"
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("📊 Dashboard"), KeyboardButton(portfolio_label)],
            [KeyboardButton(auto_label),     KeyboardButton("⚙️ Settings")],
            [KeyboardButton("❓ Help")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )

