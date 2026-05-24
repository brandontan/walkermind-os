"""Dashboard inline keyboards — glanceable home screen actions.

Screens: main dashboard, dashboard with trades, insights, chart period.
Max 2 cols, max 5 rows per skill guidelines.
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ._common import back_home_row, build_kb, refresh_home_row


def dashboard_kb(*, has_trades: bool = False) -> InlineKeyboardMarkup:
    """Main dashboard action bar — adapts to whether user has trades."""
    rows = [
        [
            InlineKeyboardButton("🤖 Auto Trade", callback_data="menu:autotrade"),
            InlineKeyboardButton("💼 Portfolio",  callback_data="menu:portfolio"),
        ],
    ]
    if has_trades:
        rows.append([
            InlineKeyboardButton("📊 Insights", callback_data="dashboard:insights"),
            InlineKeyboardButton("⚙️ Settings", callback_data="menu:settings"),
        ])
    return build_kb(rows)


def insights_kb() -> InlineKeyboardMarkup:
    """PnL Insights screen — refresh + full report + nav."""
    return build_kb(
        [[
            InlineKeyboardButton("🔄 Refresh",     callback_data="insights:refresh"),
            InlineKeyboardButton("📋 Full Report", callback_data="insights:full_report"),
        ]],
        nav=back_home_row("dashboard:main"),
    )


def chart_kb(current_days: int | str) -> InlineKeyboardMarkup:
    """Portfolio chart — period selector (7d / 30d / All)."""
    def _btn(key: str, label: str) -> InlineKeyboardButton:
        tick = "✅ " if str(current_days) == key else ""
        return InlineKeyboardButton(f"{tick}{label}", callback_data=f"chart:{key}")

    return InlineKeyboardMarkup([[
        _btn("7", "7 Days"),
        _btn("30", "30 Days"),
        _btn("all", "All Time"),
    ]])


def activity_kb() -> InlineKeyboardMarkup:
    """Activity / recent-trades screen nav."""
    return build_kb(
        [[
            InlineKeyboardButton("💼 Portfolio", callback_data="menu:portfolio"),
        ]],
        nav=[InlineKeyboardButton("🏠 Home", callback_data="menu:home")],
    )
