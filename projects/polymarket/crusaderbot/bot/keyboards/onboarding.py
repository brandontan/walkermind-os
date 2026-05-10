"""Onboarding-specific inline keyboards."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from . import grid_rows


def welcome_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🚀 Let's Go",    callback_data="onboard:lets_go"),
        InlineKeyboardButton("ℹ️ Learn More",  callback_data="onboard:learn_more"),
    ]])


def faq_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Got it, let's go!", callback_data="onboard:got_it"),
    ]])


def wallet_kb() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton("📋 Copy Address", callback_data="onboard:copy_addr"),
        InlineKeyboardButton("➡️ Next",         callback_data="onboard:next"),
    ]
    return InlineKeyboardMarkup(grid_rows(buttons))


def style_picker_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🐋 Copy Trade", callback_data="onboard:style:copy_trade")],
        [InlineKeyboardButton("🤖 Auto Trade", callback_data="onboard:style:auto_trade")],
        [InlineKeyboardButton("⚡ Both",        callback_data="onboard:style:both")],
    ])


def deposit_kb() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton("📷 Show QR",      callback_data="onboard:qr"),
        InlineKeyboardButton("📋 Copy Address", callback_data="onboard:deposit_copy"),
        InlineKeyboardButton("⏭️ Skip for now", callback_data="onboard:skip"),
    ]
    return InlineKeyboardMarkup(grid_rows(buttons))
