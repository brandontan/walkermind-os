"""Emergency keyboards — redesigned for max 5 rows.

OLD PROBLEM: emergency_p5_kb had 7 rows, violating mobile UX.

REDESIGN: Two-level progressive disclosure.
  Level 1 (emergency_home): 3 primary actions + "More..." + nav = 5 rows
  Level 2 (emergency_more): 3 secondary actions + nav = 4 rows

Primary actions (most common/urgent):
  - Pause Auto-Trade
  - Stop All + Close Positions
  - System Status

Secondary actions (behind "More..."):
  - Lock Account
  - Kill All Positions (no pause)
  - Lock Bot (full lockdown)
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ._common import back_home_row, build_kb, confirm_cancel_row


def emergency_home_kb() -> InlineKeyboardMarkup:
    """Level 1: Primary emergency actions. 3 actions + More + nav = 5 rows."""
    return build_kb(
        [
            [InlineKeyboardButton("⏸ Pause Auto-Trade",
                                  callback_data="emergency:ask:pause")],
            [InlineKeyboardButton("⏸🛑 Pause + Close All",
                                  callback_data="emergency:ask:pause_close")],
            [InlineKeyboardButton("ℹ️ System Status",
                                  callback_data="emergency:status")],
            [InlineKeyboardButton("⚠️ More Actions...",
                                  callback_data="emergency:more")],
        ],
        nav=back_home_row("menu:home"),
    )


def emergency_more_kb() -> InlineKeyboardMarkup:
    """Level 2: Secondary emergency actions. 3 actions + nav = 4 rows."""
    return build_kb(
        [
            [InlineKeyboardButton("🛑 Stop All Auto Trade",
                                  callback_data="emergency:ask:stop_auto_trade")],
            [InlineKeyboardButton("💀 Kill All Positions",
                                  callback_data="emergency:ask:kill_all_positions")],
            [InlineKeyboardButton("🔒 Lock Account",
                                  callback_data="emergency:ask:lock")],
        ],
        nav=back_home_row("emergency:home"),
    )


def emergency_confirm_kb(action: str) -> InlineKeyboardMarkup:
    """Confirm destructive emergency action. Always 1 row."""
    return InlineKeyboardMarkup([
        confirm_cancel_row(
            confirm_cb=f"emergency:confirm:{action}",
            cancel_cb="emergency:home",
            confirm_label="✅ Confirm",
            cancel_label="❌ Cancel",
        ),
    ])


def emergency_done_kb() -> InlineKeyboardMarkup:
    """Post-action — return to safety. 1 row."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🏠 Home",       callback_data="menu:home"),
        InlineKeyboardButton("🤖 Auto Mode", callback_data="menu:autotrade"),
    ]])
