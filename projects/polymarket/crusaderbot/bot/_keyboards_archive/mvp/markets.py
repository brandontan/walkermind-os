"""Markets (intelligence-only) keyboards — no manual trade buttons (blueprint 11)."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ._common import BACK, HOME, REFRESH


def home_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔥 Trending", callback_data="markets:trending"),
            InlineKeyboardButton("🆕 New", callback_data="markets:new"),
        ],
        [
            InlineKeyboardButton("🧠 AI Insights", callback_data="markets:insights"),
            InlineKeyboardButton("⭐ Watchlist", callback_data="markets:watchlist"),
        ],
        [InlineKeyboardButton("🔎 Search", callback_data="markets:search"), HOME],
    ])


def trending_list_kb(items: list[dict]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for it in items[:8]:
        label = f"{it.get('rank', '')} {it.get('title', '')}"[:32]
        rows.append([
            InlineKeyboardButton(label, callback_data=f"markets:detail:{it.get('id')}"),
        ])
    rows.append([REFRESH, HOME])
    return InlineKeyboardMarkup(rows)


def detail_kb(market_id: str) -> InlineKeyboardMarkup:
    """No manual trade buttons — only auto-strategy / watchlist / similar markets."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 Auto Strategy", callback_data="auto:home")],
        [InlineKeyboardButton("⭐ Add Watchlist", callback_data=f"markets:watchlist:add:{market_id}")],
        [InlineKeyboardButton("📊 Similar Markets", callback_data=f"markets:similar:{market_id}")],
        [BACK],
    ])


def ai_insight_kb(market_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 View Market", callback_data=f"markets:detail:{market_id}")],
        [InlineKeyboardButton("⭐ Watchlist", callback_data=f"markets:watchlist:add:{market_id}")],
        [BACK],
    ])


def search_prompt_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[BACK, HOME]])


def watchlist_empty_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧠 AI Insights", callback_data="markets:insights")],
        [InlineKeyboardButton("🔥 Trending", callback_data="markets:trending")],
        [HOME],
    ])
