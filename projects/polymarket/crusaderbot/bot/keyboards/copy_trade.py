"""Inline keyboards for the Copy Trade surface (Phase 5E).

Callback prefix: copytrade:

Patterns:
    copytrade:dashboard        — main dashboard view
    copytrade:add              — add wallet screen (two paths)
    copytrade:paste            — trigger paste-address input mode
    copytrade:discover         — smart discovery leaderboard (default filter)
    copytrade:discover:<f>     — leaderboard with filter f
    copytrade:stats:<addr>     — wallet stats card
    copytrade:copy:<addr>      — begin copy task setup (Phase 5F wizard)
    copytrade:pause:<task_id>  — toggle task pause / resume
    copytrade:edit:<task_id>   — edit task (Phase 5F wizard)
    copytrade:remove:<addr>    — legacy: remove copy_targets row
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from . import grid_rows

_DISCOVER_FILTERS: list[tuple[str, str]] = [
    ("🪙 Crypto",    "crypto"),
    ("🏅 Sports",    "sports"),
    ("🗳 Politics",  "politics"),
    ("🌍 World",     "world"),
    ("💰 Top PnL",   "top_pnl"),
    ("🎯 Top WR",    "top_wr"),
]


def copy_trade_empty_kb() -> InlineKeyboardMarkup:
    """Dashboard empty state — no tasks yet."""
    buttons = [
        InlineKeyboardButton("➕ Add Wallet", callback_data="copytrade:add"),
        InlineKeyboardButton("🔍 Discover",   callback_data="copytrade:discover"),
    ]
    return InlineKeyboardMarkup(grid_rows(buttons))


def copy_trade_task_list_kb(
    task_ids: list[str],
    statuses: list[str],
) -> InlineKeyboardMarkup:
    """Per-task [Pause/Resume] [Edit] rows plus nav buttons at the bottom."""
    rows: list[list] = []
    for task_id, status in zip(task_ids, statuses):
        pause_label = "▶️ Resume" if status == "paused" else "⏸ Pause"
        rows.append([
            InlineKeyboardButton(
                pause_label, callback_data=f"copytrade:pause:{task_id}",
            ),
            InlineKeyboardButton(
                "✏️ Edit", callback_data=f"copytrade:edit:{task_id}",
            ),
        ])
    nav = [
        InlineKeyboardButton("➕ Add Wallet", callback_data="copytrade:add"),
        InlineKeyboardButton("🔍 Discover",   callback_data="copytrade:discover"),
    ]
    rows.append(nav)
    return InlineKeyboardMarkup(rows)


def copy_trade_add_wallet_kb() -> InlineKeyboardMarkup:
    """Two-path add wallet screen."""
    top = grid_rows([
        InlineKeyboardButton("📋 Paste Address", callback_data="copytrade:paste"),
        InlineKeyboardButton("🔍 Discover",      callback_data="copytrade:discover"),
    ])
    bottom = [[InlineKeyboardButton("← Back", callback_data="copytrade:dashboard")]]
    return InlineKeyboardMarkup(top + bottom)


def wallet_stats_kb(address: str) -> InlineKeyboardMarkup:
    """Stats card actions: copy or go back."""
    buttons = [
        InlineKeyboardButton(
            "🐋 Copy This Wallet", callback_data=f"copytrade:copy:{address}",
        ),
        InlineKeyboardButton("← Back", callback_data="copytrade:add"),
    ]
    return InlineKeyboardMarkup(grid_rows(buttons))


def discover_filter_kb(active_filter: str = "top_pnl") -> InlineKeyboardMarkup:
    """Filter row (2-col grid) for the leaderboard, plus Back button."""
    buttons = [
        InlineKeyboardButton(
            f"{'✅ ' if f == active_filter else ''}{label}",
            callback_data=f"copytrade:discover:{f}",
        )
        for label, f in _DISCOVER_FILTERS
    ]
    back = InlineKeyboardButton("← Back", callback_data="copytrade:add")
    return InlineKeyboardMarkup(grid_rows(buttons) + [[back]])


def discover_wallet_kb(address: str) -> InlineKeyboardMarkup:
    """Per-wallet action in the leaderboard view."""
    buttons = [
        InlineKeyboardButton(
            "🐋 Copy This Wallet", callback_data=f"copytrade:copy:{address}",
        ),
        InlineKeyboardButton("← Back", callback_data="copytrade:discover"),
    ]
    return InlineKeyboardMarkup(grid_rows(buttons))


def _truncate_wallet(address: str) -> str:
    """0x12345678…abcd-style display label for a 0x + 40-hex address."""
    if len(address) < 12:
        return address
    return f"{address[:8]}…{address[-4:]}"


def copy_targets_list_kb(wallet_addresses) -> InlineKeyboardMarkup:
    """Legacy: one [🗑 Stop] button per active copy target (copy_targets table)."""
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
