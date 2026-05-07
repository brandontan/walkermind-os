"""Inline keyboards for the /signals Telegram surface.

Single keyboard:
    signal_subs_list_kb — one row per active subscription with a
                          [\U0001F6D1 Off] button keyed by the feed slug.

Callback prefix:
    signals:off:<feed_slug>

The feed slug is round-tripped through callback_data so the off handler
does not need a second DB lookup to know which subscription to retire.
"""
from __future__ import annotations

from typing import Iterable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def _truncate_label(text: str, limit: int = 28) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def signal_subs_list_kb(
    entries: Iterable[tuple[str, str]],
) -> InlineKeyboardMarkup:
    """One [\U0001F6D1 Off] button per active subscription.

    Args:
        entries: iterable of ``(feed_slug, feed_name)`` tuples. ``feed_slug``
            is the value round-tripped through callback_data; ``feed_name``
            is the display label.
    """
    rows = [
        [
            InlineKeyboardButton(
                f"\U0001F6D1 Off {_truncate_label(name)}",
                callback_data=f"signals:off:{slug}",
            )
        ]
        for slug, name in entries
    ]
    return InlineKeyboardMarkup(rows)
