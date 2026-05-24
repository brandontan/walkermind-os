"""Wallet keyboards — deposit, balance, withdraw.

Simple 2-col grid. Max 3 rows.
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ._common import back_home_row, build_kb, grid_rows


def wallet_home_kb() -> InlineKeyboardMarkup:
    """Wallet hub — deposit / balance / withdraw + nav. 3 rows."""
    return build_kb(
        grid_rows([
            InlineKeyboardButton("📥 Deposit",  callback_data="wallet:deposit"),
            InlineKeyboardButton("💵 Balance",  callback_data="wallet:balance"),
            InlineKeyboardButton("📤 Withdraw", callback_data="wallet:withdraw"),
        ]),
        nav=back_home_row("menu:home"),
    )


def wallet_copy_kb() -> InlineKeyboardMarkup:
    """Wallet address — copy + home. 2 rows."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Copy Address", callback_data="wallet:copy")],
        [InlineKeyboardButton("🏠 Home",          callback_data="menu:home")],
    ])
