"""Inline keyboards for the live position monitor (R12d).

MVP UX hides manual force-close controls from standard user surfaces.
The force-close confirmation keyboard remains available for internal/admin
callback paths, but positions_list_kb renders navigation-only controls.
"""
from __future__ import annotations

from typing import Iterable
from uuid import UUID

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def positions_list_kb(position_ids: Iterable[UUID | str]) -> InlineKeyboardMarkup:
    """Navigation-only keyboard for portfolio surfaces (no manual close CTA)."""
    _ = list(position_ids)  # keep signature stable for existing call sites
    rows: list[list[InlineKeyboardButton]] = []
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
