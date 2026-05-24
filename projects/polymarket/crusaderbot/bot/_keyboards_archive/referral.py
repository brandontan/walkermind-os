"""Keyboards for the referral / share card surface."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ._common import home_row


def share_trade_kb(trade_id: str) -> InlineKeyboardMarkup:
    """Inline keyboard attached to winning-trade notifications."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏆 Share", callback_data=f"referral:share:{trade_id}")],
        home_row(),
    ])
