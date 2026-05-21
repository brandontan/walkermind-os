"""Onboarding keyboards: welcome, wallet ready, deposit prompt, new-user dashboard."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ._common import BACK, HOME


def welcome_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Quick Start", callback_data="auto:quick_start")],
        [InlineKeyboardButton("🛠 Configure", callback_data="auto:configure")],
        [InlineKeyboardButton("❓ Learn More", callback_data="help:home")],
    ])


def wallet_ready_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Quick Start", callback_data="auto:quick_start")],
        [InlineKeyboardButton("🛠 Customize", callback_data="auto:configure")],
        [InlineKeyboardButton("⬅ Back", callback_data="nav:back")],
    ])


def deposit_prompt_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Continue with Paper", callback_data="auto:quick_start")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="settings:home")],
        [HOME],
    ])


def new_user_dashboard_kb() -> InlineKeyboardMarkup:
    """Compact CTA keyboard rendered on the new-user dashboard (blueprint 8.2)."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Quick Start", callback_data="auto:quick_start")],
        [InlineKeyboardButton("🛠 Configure", callback_data="auto:configure")],
        [InlineKeyboardButton("❓ Learn More", callback_data="help:home")],
    ])
