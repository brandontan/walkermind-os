"""Admin and operator keyboards — restricted surfaces.

These keyboards are ONLY shown to users with admin/operator role.
Never exposed in public help or discovery paths.

Screens:
  1. admin_menu       — Kill switch, system status, tools
  2. ops_dashboard    — Operator panel with runtime controls
  3. confirm dialogs  — All destructive admin actions
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ._common import back_home_row, build_kb, confirm_cancel_row, grid_rows


def admin_menu_kb(*, kill_active: bool = False) -> InlineKeyboardMarkup:
    """Admin menu — kill switch, status, tools. Max 5 rows."""
    kill_label = "🟢 Disable Kill Switch" if kill_active else "🔴 Activate Kill Switch"
    return build_kb(
        grid_rows([
            InlineKeyboardButton(kill_label,               callback_data="admin:kill"),
            InlineKeyboardButton("📊 System Status",       callback_data="admin:status"),
            InlineKeyboardButton("🔁 Force Redeem",        callback_data="admin:force_redeem"),
            InlineKeyboardButton("🔄 Reset Onboarding",    callback_data="admin:resetonboard_prompt"),
        ]),
        nav=back_home_row("menu:home"),
    )


def ops_dashboard_kb() -> InlineKeyboardMarkup:
    """Operator panel — monitoring + runtime controls. Max 5 rows."""
    return build_kb(
        [
            [
                InlineKeyboardButton("📊 Metrics",  callback_data="ops:metrics"),
                InlineKeyboardButton("🏥 Health",   callback_data="ops:health"),
            ],
            [
                InlineKeyboardButton("📋 Jobs",     callback_data="ops:jobs"),
                InlineKeyboardButton("📝 Audit",    callback_data="ops:audit"),
            ],
            [
                InlineKeyboardButton("👥 Users",    callback_data="ops:users"),
                InlineKeyboardButton("🛡️ Alerts",   callback_data="ops:alerts"),
            ],
        ],
        nav=back_home_row("menu:home"),
    )


def admin_confirm_kb(action: str) -> InlineKeyboardMarkup:
    """Confirm destructive admin action."""
    return InlineKeyboardMarkup([
        confirm_cancel_row(
            confirm_cb=f"admin:confirm:{action}",
            cancel_cb="admin:menu",
        ),
    ])
