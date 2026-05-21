"""Shared keyboard helpers — back / home / refresh / cancel / confirm rows."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

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


def main_menu_kb() -> InlineKeyboardMarkup:
    """Dashboard 6-button main navigation (blueprint 7.2)."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🤖 Auto Trade", callback_data="auto:home"),
            InlineKeyboardButton("👥 Copy Wallet", callback_data="copy:home"),
        ],
        [
            InlineKeyboardButton("💼 Portfolio", callback_data="portfolio:home"),
            InlineKeyboardButton("📈 Markets", callback_data="markets:home"),
        ],
        [
            InlineKeyboardButton("⚙️ Settings", callback_data="settings:home"),
            InlineKeyboardButton("❓ Help", callback_data="help:home"),
        ],
        [REFRESH, HOME],
    ])
