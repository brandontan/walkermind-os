"""Auto Trade keyboards (blueprint section 9)."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ._common import BACK, CANCEL, HOME


def home_kb(*, running: bool = False, paused: bool = False) -> InlineKeyboardMarkup:
    if running:
        action_btn = InlineKeyboardButton("⏸ Pause", callback_data="auto:pause")
    elif paused:
        action_btn = InlineKeyboardButton("▶ Resume", callback_data="auto:resume")
    else:
        action_btn = InlineKeyboardButton("▶ Start", callback_data="auto:start")
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🚀 Quick Start", callback_data="auto:quick_start"),
            InlineKeyboardButton("🛠 Configure", callback_data="auto:configure"),
        ],
        [
            InlineKeyboardButton("📊 Status", callback_data="auto:status"),
            action_btn,
        ],
        [BACK, HOME],
    ])


def quick_start_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Start Recommended", callback_data="auto:start")],
        [InlineKeyboardButton("🛠 Customize", callback_data="auto:configure")],
        [BACK],
    ])


def configure_strategy_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ Momentum", callback_data="auto:configure:strategy:momentum")],
        [InlineKeyboardButton("📊 Mean Reversion", callback_data="auto:configure:strategy:mean_reversion")],
        [InlineKeyboardButton("🧪 Smart Hybrid", callback_data="auto:configure:strategy:smart_hybrid")],
        [BACK],
    ])


def configure_capital_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("$25", callback_data="auto:configure:capital:25"),
            InlineKeyboardButton("$50", callback_data="auto:configure:capital:50"),
        ],
        [
            InlineKeyboardButton("$100", callback_data="auto:configure:capital:100"),
            InlineKeyboardButton("$250", callback_data="auto:configure:capital:250"),
        ],
        [InlineKeyboardButton("✏️ Custom", callback_data="auto:configure:capital:custom")],
        [BACK],
    ])


def configure_risk_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 Safe", callback_data="auto:configure:risk:safe")],
        [InlineKeyboardButton("🟡 Balanced", callback_data="auto:configure:risk:balanced")],
        [InlineKeyboardButton("🔴 Aggressive", callback_data="auto:configure:risk:aggressive")],
        [BACK],
    ])


def configure_review_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("▶ Start Auto Trade", callback_data="auto:start")],
        [InlineKeyboardButton("🛠 Edit Setup", callback_data="auto:configure")],
        [CANCEL],
    ])


def strategy_status_kb(*, running: bool = True) -> InlineKeyboardMarkup:
    pause_resume = (
        InlineKeyboardButton("⏸ Pause", callback_data="auto:pause")
        if running else
        InlineKeyboardButton("▶ Resume", callback_data="auto:resume")
    )
    return InlineKeyboardMarkup([
        [pause_resume, InlineKeyboardButton("⚙️ Edit", callback_data="auto:configure")],
        [InlineKeyboardButton("📊 Stats", callback_data="auto:status"), HOME],
    ])


def pause_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Pause Bot", callback_data="auto:pause:confirm")],
        [CANCEL],
    ])


def resume_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Resume Bot", callback_data="auto:resume:confirm")],
        [CANCEL],
    ])
