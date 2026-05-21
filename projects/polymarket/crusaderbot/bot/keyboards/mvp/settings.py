"""Settings keyboards (blueprint section 13)."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ._common import BACK, HOME


def home_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Trading Mode", callback_data="settings:mode"),
            InlineKeyboardButton("🛡 Risk", callback_data="settings:risk"),
        ],
        [
            InlineKeyboardButton("🔔 Notifications", callback_data="settings:notifications"),
            InlineKeyboardButton("👥 Copy Wallet", callback_data="settings:copy_wallet"),
        ],
        [
            InlineKeyboardButton("👤 Account", callback_data="settings:account"),
            InlineKeyboardButton("🧪 Advanced", callback_data="settings:advanced"),
        ],
        [BACK, HOME],
    ])


def trading_mode_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Paper Mode", callback_data="settings:mode:paper")],
        [InlineKeyboardButton("💸 Live Mode", callback_data="settings:mode:live")],
        [BACK],
    ])


def live_gate_kb() -> InlineKeyboardMarkup:
    """Live mode is locked — only request-access + back. No bypass (blueprint 23.2)."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔐 Request Access", callback_data="settings:mode:live:request")],
        [BACK],
    ])


def risk_controls_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💸 Loss Limit", callback_data="settings:risk:loss_limit")],
        [InlineKeyboardButton("📊 Position Size", callback_data="settings:risk:position_size")],
        [InlineKeyboardButton("🔢 Trade Limits", callback_data="settings:risk:concurrent")],
        [InlineKeyboardButton("⏸ Auto Pause", callback_data="settings:risk:auto_pause")],
        [BACK],
    ])


def notifications_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 Trades", callback_data="settings:notifications:trades")],
        [InlineKeyboardButton("⚠ Risk Alerts", callback_data="settings:notifications:risk")],
        [InlineKeyboardButton("📅 Daily Summary", callback_data="settings:notifications:summary")],
        [InlineKeyboardButton("🔕 Quiet Mode", callback_data="settings:notifications:quiet")],
        [BACK],
    ])


def account_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Wallet", callback_data="settings:account:wallet")],
        [InlineKeyboardButton("📄 Export Data", callback_data="settings:account:export")],
        [InlineKeyboardButton("🔒 Security", callback_data="settings:account:security")],
        [BACK],
    ])


def advanced_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📜 Logs", callback_data="settings:advanced:logs")],
        [InlineKeyboardButton("🛠 Debug", callback_data="settings:advanced:debug")],
        [InlineKeyboardButton("💓 Health", callback_data="settings:advanced:health")],
        [BACK],
    ])
