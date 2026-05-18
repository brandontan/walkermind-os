"""Inline keyboards for the My Trades combined view (Phase 5I).

Callback prefixes (all registered in bot.dispatcher):
  mytrades:close_ask:<uuid>   — per-position Close button
  mytrades:close_yes:<uuid>   — confirm close
  mytrades:close_no:<uuid>    — cancel close
  mytrades:hist:<page>        — history page (0-based)
  mytrades:back               — re-render My Trades from a callback surface
"""
from __future__ import annotations

from uuid import UUID

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from . import grid_rows
from ._common import home_back_row


def my_trades_main_kb(position_ids: list[UUID | str]) -> InlineKeyboardMarkup:
    """Main keyboard for the combined My Trades message.

    Close buttons (numbered 1…N, 2-column grid) are followed by a
    [Full History] [Dashboard] navigation row.
    """
    rows: list[list[InlineKeyboardButton]] = []
    close_btns = [
        InlineKeyboardButton(
            f"🔴 Close {i + 1}",
            callback_data=f"mytrades:close_ask:{pid}",
        )
        for i, pid in enumerate(position_ids)
    ]
    rows.extend(grid_rows(close_btns))
    rows.append(
        [
            InlineKeyboardButton(
                "📋 Full History", callback_data="mytrades:hist:0"
            ),
            InlineKeyboardButton(
                "📊 Insights", callback_data="insights:refresh"
            ),
        ]
    )
    return InlineKeyboardMarkup(rows)


def close_confirm_kb(position_id: UUID | str) -> InlineKeyboardMarkup:
    """Confirm / cancel dialog for a per-position close."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Confirm Close",
                    callback_data=f"mytrades:close_yes:{position_id}",
                ),
                InlineKeyboardButton(
                    "❌ Cancel",
                    callback_data=f"mytrades:close_no:{position_id}",
                ),
            ]
        ]
    )


def close_success_kb() -> InlineKeyboardMarkup:
    """Navigation buttons shown after a successful position close."""
    return InlineKeyboardMarkup(
        [home_back_row("mytrades:back")]
    )


def history_nav_kb(page: int, has_prev: bool, has_next: bool) -> InlineKeyboardMarkup:
    """Prev / Next navigation for the Full History paginated view."""
    nav: list[InlineKeyboardButton] = []
    if has_prev:
        nav.append(
            InlineKeyboardButton(
                "⬅️ Prev", callback_data=f"mytrades:hist:{page - 1}"
            )
        )
    if has_next:
        nav.append(
            InlineKeyboardButton(
                "➡️ Next", callback_data=f"mytrades:hist:{page + 1}"
            )
        )
    rows: list[list[InlineKeyboardButton]] = []
    if nav:
        rows.append(nav)
    rows.append(home_back_row("mytrades:back"))
    return InlineKeyboardMarkup(rows)
