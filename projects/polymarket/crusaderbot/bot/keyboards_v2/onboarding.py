"""Onboarding keyboards — welcome, wallet setup, deposit prompt.

Flow: /start → Welcome → Get Started → Wallet Ready → Deposit → Dashboard
Each screen max 3 rows. Clean, non-intimidating for new users.
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ._common import build_kb


def welcome_kb() -> InlineKeyboardMarkup:
    """First contact — Get Started + Learn More. 2 rows."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Get Started", callback_data="onboard:get_started")],
        [InlineKeyboardButton("ℹ️ Learn More",  callback_data="onboard:learn_more")],
    ])


def wallet_ready_kb() -> InlineKeyboardMarkup:
    """Wallet generated — copy address + continue. 2 rows."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Copy Address", callback_data="onboard:copy_address")],
        [InlineKeyboardButton("Next →",          callback_data="onboard:wallet_next")],
    ])


def deposit_prompt_kb() -> InlineKeyboardMarkup:
    """Deposit prompt — copy address or skip. 2 rows."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Copy Address", callback_data="onboard:copy_address")],
        [InlineKeyboardButton("Skip for now",    callback_data="onboard:skip_deposit")],
    ])


def onboard_complete_kb() -> InlineKeyboardMarkup:
    """Onboarding complete — go to dashboard or setup. 2 rows."""
    return build_kb(
        [[
            InlineKeyboardButton("📊 Dashboard",      callback_data="menu:home"),
            InlineKeyboardButton("🤖 Setup Auto",     callback_data="menu:autotrade"),
        ]],
    )
