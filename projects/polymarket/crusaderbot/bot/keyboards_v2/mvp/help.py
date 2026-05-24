"""Help keyboards (blueprint section 14)."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ._common import BACK, HOME


def home_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🚀 Quick Start", callback_data="help:quick_start"),
            InlineKeyboardButton("🤖 Auto Trade", callback_data="help:auto"),
        ],
        [
            InlineKeyboardButton("👥 Copy Wallet", callback_data="help:copy_wallet"),
            InlineKeyboardButton("🛡 Safety", callback_data="help:safety"),
        ],
        [
            InlineKeyboardButton("💬 FAQ", callback_data="help:faq"),
            InlineKeyboardButton("🆘 Support", callback_data="help:support"),
        ],
        [HOME],
    ])


def quick_start_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 Setup Auto Trade", callback_data="auto:quick_start")],
        [InlineKeyboardButton("👥 Setup Copy Wallet", callback_data="copy:add_wallet")],
        [BACK, HOME],
    ])


def how_auto_trade_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛡 Safety", callback_data="help:safety")],
        [InlineKeyboardButton("🚀 Quick Start", callback_data="auto:quick_start")],
        [BACK],
    ])


def how_copy_wallet_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Wallet", callback_data="copy:add_wallet")],
        [InlineKeyboardButton("🛡 Safety", callback_data="help:safety")],
        [BACK],
    ])


def safety_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Trading Mode", callback_data="settings:mode")],
        [InlineKeyboardButton("🛡 Risk Controls", callback_data="settings:risk")],
        [BACK],
    ])


def faq_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1️⃣ Auto Trade", callback_data="help:faq:auto")],
        [InlineKeyboardButton("2️⃣ Paper Mode", callback_data="help:faq:paper")],
        [InlineKeyboardButton("3️⃣ Risk", callback_data="help:faq:risk")],
        [InlineKeyboardButton("4️⃣ Copy Wallet", callback_data="help:faq:copy")],
        [BACK],
    ])


def support_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🐞 Report Issue", callback_data="help:support:report")],
        [InlineKeyboardButton("💬 FAQ", callback_data="help:faq")],
        [HOME],
    ])
