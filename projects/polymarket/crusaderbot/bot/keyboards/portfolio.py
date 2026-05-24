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

from typing import Iterable
from uuid import UUID

from ._common import (
    back_home_row, build_kb, confirm_cancel_row, grid_rows,
    home_back_row, pagination_row,
)


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


# ── Legacy P5 portfolio / positions / trades surfaces ────────────────
# Callback data preserved exactly for the positions/trades/my_trades
# handlers and their dispatcher patterns (portfolio:, close_position:,
# position:fc_*, p5:trades:*, mytrades:*).

def portfolio_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 Positions", callback_data="portfolio:positions"),
            InlineKeyboardButton("📋 Trades",    callback_data="portfolio:trades"),
        ],
        [
            InlineKeyboardButton("🔄 Refresh",   callback_data="dashboard:portfolio"),
            InlineKeyboardButton("🏠 Home",      callback_data="dashboard:main"),
        ],
    ])


def positions_close_list_kb(positions: Iterable[dict]) -> InlineKeyboardMarkup:
    """Per-position close rows + back/home nav (legacy positions monitor)."""
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


def trades_p5_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 Full History", callback_data="p5:trades:history"),
            InlineKeyboardButton("📊 Dashboard",    callback_data="menu:dashboard"),
        ],
    ])


def close_position_p5_kb(position_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🛑 Close", callback_data=f"close_position:{position_id}"),
    ]])


def close_confirm_p5_kb(position_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirm Close",
                                 callback_data=f"close_position:confirm:{position_id}"),
            InlineKeyboardButton("⬅ Cancel", callback_data="p5:trades:cancel_close"),
        ],
    ])


def my_trades_main_kb(position_ids: list[UUID | str]) -> InlineKeyboardMarkup:
    """Combined My Trades message — numbered close buttons + history/insights."""
    rows: list[list[InlineKeyboardButton]] = []
    close_btns = [
        InlineKeyboardButton(f"🔴 Close {i + 1}",
                             callback_data=f"mytrades:close_ask:{pid}")
        for i, pid in enumerate(position_ids)
    ]
    rows.extend(grid_rows(close_btns))
    rows.append([
        InlineKeyboardButton("📋 Full History", callback_data="mytrades:hist:0"),
        InlineKeyboardButton("📊 Insights",     callback_data="insights:refresh"),
    ])
    return InlineKeyboardMarkup(rows)


def mytrades_close_confirm_kb(position_id: UUID | str) -> InlineKeyboardMarkup:
    """Confirm / cancel dialog for a per-position My Trades close."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirm Close",
                             callback_data=f"mytrades:close_yes:{position_id}"),
        InlineKeyboardButton("❌ Cancel",
                             callback_data=f"mytrades:close_no:{position_id}"),
    ]])


def close_success_kb() -> InlineKeyboardMarkup:
    """Navigation shown after a successful My Trades close."""
    return InlineKeyboardMarkup([home_back_row("mytrades:back")])


def history_nav_kb(page: int, has_prev: bool, has_next: bool) -> InlineKeyboardMarkup:
    """Prev / Next navigation for the My Trades Full History view."""
    nav: list[InlineKeyboardButton] = []
    if has_prev:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"mytrades:hist:{page - 1}"))
    if has_next:
        nav.append(InlineKeyboardButton("➡️ Next", callback_data=f"mytrades:hist:{page + 1}"))
    rows: list[list[InlineKeyboardButton]] = []
    if nav:
        rows.append(nav)
    rows.append(home_back_row("mytrades:back"))
    return InlineKeyboardMarkup(rows)
