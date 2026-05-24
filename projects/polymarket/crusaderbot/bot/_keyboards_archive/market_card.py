"""Inline keyboard for the rich market card (/market {slug})."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ._common import home_row

_MAX_SLUG = 50  # keeps callback_data under 64 bytes (prefix is ≤14 chars)


def market_card_kb(slug: str) -> InlineKeyboardMarkup:
    """2×2 keyboard for a market card. Slug is truncated if unusually long."""
    s = slug[:_MAX_SLUG]
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Buy YES", callback_data=f"market:y:{s}"),
            InlineKeyboardButton("Buy NO",  callback_data=f"market:n:{s}"),
        ],
        [
            InlineKeyboardButton("Set Alert", callback_data=f"market:a:{s}"),
            InlineKeyboardButton("Details",   callback_data=f"market:d:{s}"),
        ],
        home_row(),
    ])
