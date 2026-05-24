"""Portfolio, positions, and trade keyboards.

Screens:
  1. portfolio_home  — Positions / Trades / Refresh / Home
  2. positions_list  — Paginated position list (3/page)
  3. position_detail — Force close button per position
  4. close_confirm   — Confirm/Cancel close dialog
  5. trades_list     — Trade history with pagination
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ._common import back_home_row, build_kb, confirm_cancel_row, pagination_row


def portfolio_home_kb() -> InlineKeyboardMarkup:
    """Portfolio hub — 2 actions + refresh/home. 2 rows."""
    return build_kb(
        [[
            InlineKeyboardButton("📋 Positions", callback_data="portfolio:positions"),
            InlineKeyboardButton("📋 Trades",    callback_data="portfolio:trades"),
        ]],
        nav=[
            InlineKeyboardButton("🔄 Refresh",  callback_data="portfolio:refresh"),
            InlineKeyboardButton("🏠 Home",     callback_data="menu:home"),
        ],
    )


def positions_list_kb(
    page: int,
    total_pages: int,
) -> InlineKeyboardMarkup:
    """Paginated positions list. Nav row always present."""
    rows: list[list[InlineKeyboardButton]] = []
    if total_pages > 1:
        rows.append(pagination_row(
            prev_cb=f"portfolio:positions:page:{page - 1}",
            next_cb=f"portfolio:positions:page:{page + 1}",
            page=page,
            total=total_pages,
        ))
    rows.append(back_home_row("menu:portfolio"))
    return InlineKeyboardMarkup(rows)


def position_close_kb(position_id: str) -> InlineKeyboardMarkup:
    """Single position — close button."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🛑 Close Position",
                             callback_data=f"positions:close:{position_id}"),
    ]])


def close_confirm_kb(position_id: str) -> InlineKeyboardMarkup:
    """Confirm close — destructive action requires explicit confirm."""
    return InlineKeyboardMarkup([
        confirm_cancel_row(
            confirm_cb=f"positions:close:confirm:{position_id}",
            cancel_cb="portfolio:positions",
            confirm_label="✅ Confirm Close",
            cancel_label="❌ Cancel",
        ),
    ])


def trades_home_kb() -> InlineKeyboardMarkup:
    """Trade history screen — history + dashboard."""
    return build_kb(
        [[
            InlineKeyboardButton("📋 Full History", callback_data="trades:history"),
            InlineKeyboardButton("📊 Dashboard",    callback_data="menu:home"),
        ]],
    )


def trades_empty_kb() -> InlineKeyboardMarkup:
    """No trades yet — funnel to auto-trade setup."""
    return build_kb(
        [
            [InlineKeyboardButton("🤖 Set Up Auto-Trade", callback_data="menu:autotrade")],
        ],
        nav=[InlineKeyboardButton("📊 Dashboard", callback_data="menu:home")],
    )


def trades_history_kb(
    page: int,
    total_pages: int,
) -> InlineKeyboardMarkup:
    """Paginated trade history."""
    rows: list[list[InlineKeyboardButton]] = []
    if total_pages > 1:
        rows.append(pagination_row(
            prev_cb=f"trades:history:page:{page - 1}",
            next_cb=f"trades:history:page:{page + 1}",
            page=page,
            total=total_pages,
        ))
    rows.append(back_home_row("menu:portfolio"))
    return InlineKeyboardMarkup(rows)
