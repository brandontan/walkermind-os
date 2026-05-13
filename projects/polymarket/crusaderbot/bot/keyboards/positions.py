"""Inline keyboards for the live position monitor and per-position
force-close flow (R12d).

Layout:
  * positions_list_kb    — one row per open position with a
                           [🛑 Force Close] button keyed by position UUID
  * force_close_confirm_kb — two-button confirm dialog keyed by position UUID

Callback prefixes (registered in bot.dispatcher):
  position:fc_ask:<uuid>      — user tapped 🛑 Force Close on row
  position:fc_yes:<uuid>      — user confirmed
  position:fc_no:<uuid>       — user cancelled

The UUID is round-tripped through callback_data so the confirm step does not
have to re-query the DB to know which position the user is acting on.
"""
from __future__ import annotations

from typing import Iterable
from uuid import UUID

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def positions_list_kb(position_ids: Iterable[UUID | str]) -> InlineKeyboardMarkup:
    """One [🛑 Force Close] button per open position + Back/Home nav."""
    rows = [
        [
            InlineKeyboardButton(
                f"🛑 Force Close {str(pid)[:6]}",
                callback_data=f"position:fc_ask:{pid}",
            )
        ]
        for pid in position_ids
    ]
    rows.append([
        InlineKeyboardButton("⬅ Back", callback_data="portfolio:portfolio"),
        InlineKeyboardButton("🏠 Home", callback_data="dashboard:main"),
    ])
    return InlineKeyboardMarkup(rows)


def force_close_confirm_kb(position_id: UUID | str) -> InlineKeyboardMarkup:
    """Two-button confirm dialog for a single position force-close."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Confirm Close",
                    callback_data=f"position:fc_yes:{position_id}",
                ),
                InlineKeyboardButton(
                    "❌ Cancel",
                    callback_data=f"position:fc_no:{position_id}",
                ),
            ]
        ]
    )
