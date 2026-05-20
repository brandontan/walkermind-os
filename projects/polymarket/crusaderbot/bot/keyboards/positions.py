"""Inline keyboards for the live position monitor (R12d).

MVP UX hides manual force-close controls from standard user surfaces.
The force-close confirmation keyboard remains available for internal/admin
callback paths, but positions_list_kb renders navigation-only controls.
"""
from __future__ import annotations

from typing import Iterable
from uuid import UUID

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ._common import confirm_cancel_row, home_back_row


def positions_list_kb(positions: Iterable[dict]) -> InlineKeyboardMarkup:
    """Per-position [🔴 Close — id SIDE · question] rows + back/home nav row."""
    rows: list[list[InlineKeyboardButton]] = []
    for pos in positions:
        pid   = str(pos["id"])[:8]
        side  = pos["side"].upper()
        q     = pos.get("question") or pos.get("market_id", "")
        title = (q[:28] + "…") if len(q) > 28 else q
        label = f"🔴 Close — {pid} {side} · {title}"
        rows.append([InlineKeyboardButton(label, callback_data=f"close_position:{pos['id']}")])
    rows.append(home_back_row("portfolio:portfolio"))
    return InlineKeyboardMarkup(rows)


def force_close_confirm_kb(position_id: UUID | str) -> InlineKeyboardMarkup:
    """Two-button confirm dialog for a single position force-close."""
    return InlineKeyboardMarkup([
        confirm_cancel_row(
            f"position:fc_yes:{position_id}",
            f"position:fc_no:{position_id}",
            "✅ Confirm Close",
            "❌ Cancel",
        ),
    ])
