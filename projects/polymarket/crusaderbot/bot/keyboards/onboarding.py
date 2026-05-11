"""Onboarding-specific inline keyboards."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def get_started_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🚀 Get Started", callback_data="onboard:get_started"),
    ]])


def mode_select_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 Start Paper Trading", callback_data="onboard:mode_paper")],
        [InlineKeyboardButton("💰 Setup Live Trading",  callback_data="onboard:mode_live")],
    ])


def paper_complete_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("📊 View Dashboard", callback_data="onboard:view_dashboard"),
    ]])
