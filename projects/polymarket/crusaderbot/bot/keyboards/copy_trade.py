"""Inline keyboards for the /copytrade Telegram surface.

Single keyboard:
    copy_targets_list_kb — one row per active copy target with a
                           [🗑 Stop] button keyed by the wallet address.

Callback prefix:
    copytrade:remove:<wallet_address>

The wallet address is round-tripped through callback_data so the remove
handler does not need to re-query the DB to know which target to deactivate.
"""
from __future__ import annotations

from typing import Iterable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def _truncate_wallet(address: str) -> str:
    """0x12345678…abcd-style display label for a 0x + 40-hex address."""
    if len(address) < 12:
        return address
    return f"{address[:8]}…{address[-4:]}"


def copy_targets_list_kb(wallet_addresses: Iterable[str]) -> InlineKeyboardMarkup:
    """One [🗑 Stop] button per active copy target."""
    rows = [
        [
            InlineKeyboardButton(
                f"🗑 Stop {_truncate_wallet(addr)}",
                callback_data=f"copytrade:remove:{addr}",
            )
        ]
        for addr in wallet_addresses
    ]
    return InlineKeyboardMarkup(rows)
