"""Copy Wallet keyboards (blueprint section 10)."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ._common import BACK, CANCEL, HOME


def home_kb(*, running: bool = False) -> InlineKeyboardMarkup:
    pause_resume = (
        InlineKeyboardButton("⏸ Pause", callback_data="copy:pause")
        if running else
        InlineKeyboardButton("▶ Resume", callback_data="copy:resume")
    )
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Add Wallet", callback_data="copy:add_wallet"),
            InlineKeyboardButton("👛 Active Wallets", callback_data="copy:wallets"),
        ],
        [
            pause_resume,
            InlineKeyboardButton("🛡 Risk", callback_data="settings:risk"),
        ],
        [BACK, HOME],
    ])


def add_wallet_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[BACK, HOME]])


def wallet_review_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Continue", callback_data="copy:wallet:configure")],
        [CANCEL],
    ])


def wallet_configure_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("▶ Start Copying", callback_data="copy:wallet:start")],
        [InlineKeyboardButton("🛠 Edit", callback_data="copy:wallet:edit")],
        [CANCEL],
    ])


def active_wallets_empty_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Wallet", callback_data="copy:add_wallet")],
        [HOME],
    ])


def wallet_card_kb(wallet_id: str, *, running: bool = True) -> InlineKeyboardMarkup:
    pause_resume = (
        InlineKeyboardButton("⏸ Pause Wallet", callback_data=f"copy:wallet:pause:{wallet_id}")
        if running else
        InlineKeyboardButton("▶ Resume Wallet", callback_data=f"copy:wallet:resume:{wallet_id}")
    )
    return InlineKeyboardMarkup([
        [pause_resume, InlineKeyboardButton("⚙️ Edit Wallet", callback_data=f"copy:wallet:edit:{wallet_id}")],
        [InlineKeyboardButton("📊 Stats", callback_data=f"copy:wallet:stats:{wallet_id}"), HOME],
    ])


def pause_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Pause Copying", callback_data="copy:pause:confirm")],
        [CANCEL],
    ])
