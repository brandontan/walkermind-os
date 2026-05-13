"""Onboarding-specific inline keyboards — MVP Reset V1."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def get_started_kb() -> InlineKeyboardMarkup:
    """MVP single CTA — Get Started only. No demo dashboard, no settings."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Get Started", callback_data="onboard:get_started")],
    ])


# MVP RESET V1 — deprecated UI flow
def _legacy_get_started_kb() -> InlineKeyboardMarkup:
    """Legacy 3-button onboarding keyboard — archived, not shown to users."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Get Started",          callback_data="onboard:get_started")],
        [InlineKeyboardButton("📊 View Demo Dashboard",  callback_data="onboard:view_dashboard")],
        [InlineKeyboardButton("⚙️ Settings",             callback_data="onboard:settings")],
    ])


# MVP RESET V1 — deprecated UI flow
def mode_select_kb() -> InlineKeyboardMarkup:
    """Legacy mode selection keyboard — archived, not part of MVP flow."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 Start Paper Trading", callback_data="onboard:mode_paper")],
        [InlineKeyboardButton("💰 Setup Live Trading",  callback_data="onboard:mode_live")],
    ])


# MVP RESET V1 — deprecated UI flow
def paper_complete_kb() -> InlineKeyboardMarkup:
    """Legacy paper complete keyboard — archived, not part of MVP flow."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("📊 View Dashboard", callback_data="onboard:view_dashboard"),
    ]])
