"""Portfolio keyboards (blueprint section 12)."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ._common import BACK, HOME, REFRESH


def home_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📌 Positions", callback_data="portfolio:positions"),
            InlineKeyboardButton("📜 History", callback_data="portfolio:history"),
        ],
        [
            InlineKeyboardButton("💹 Performance", callback_data="portfolio:performance"),
            InlineKeyboardButton("💰 Balance", callback_data="portfolio:balance"),
        ],
        [BACK, HOME],
    ])


def positions_empty_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 Auto Trade", callback_data="auto:home")],
        [InlineKeyboardButton("👥 Copy Wallet", callback_data="copy:home")],
        [HOME],
    ])


def positions_list_kb(items: list[dict]) -> InlineKeyboardMarkup:
    """items: [{rank, title, id}, ...]"""
    rows: list[list[InlineKeyboardButton]] = []
    for it in items[:8]:
        label = f"{it.get('rank', '')} {it.get('title', '')}"[:32]
        rows.append([
            InlineKeyboardButton(label, callback_data=f"portfolio:position:{it.get('id')}"),
        ])
    rows.append([REFRESH, HOME])
    return InlineKeyboardMarkup(rows)


def position_detail_kb(market_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 View Market", callback_data=f"markets:detail:{market_id}")],
        [REFRESH],
        [BACK],
    ])


def history_home_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Today", callback_data="portfolio:history:today")],
        [InlineKeyboardButton("📆 This Week", callback_data="portfolio:history:week")],
        [InlineKeyboardButton("🗂 All Time", callback_data="portfolio:history:all")],
        [BACK],
    ])


def history_empty_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Quick Start", callback_data="auto:quick_start")],
        [HOME],
    ])


def performance_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Weekly", callback_data="portfolio:performance:week")],
        [InlineKeyboardButton("📈 Monthly", callback_data="portfolio:performance:month")],
        [BACK],
    ])


def balance_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [REFRESH],
        [BACK, HOME],
    ])
