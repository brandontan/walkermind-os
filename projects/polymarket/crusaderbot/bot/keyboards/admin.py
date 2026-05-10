"""Admin/Ops-plane inline keyboards (R12f operator dashboard)."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from . import grid_rows


def ops_dashboard_keyboard(kill_active: bool) -> InlineKeyboardMarkup:
    """Refresh + quick-action keyboard rendered under /ops_dashboard.

    Lock is intentionally kept alone on the last row — it is destructive and
    must never be accidentally paired with Refresh or Pause/Resume.
    """
    flip_label = "▶️ Resume" if kill_active else "⏸ Pause"
    flip_action = "ops:resume" if kill_active else "ops:pause"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="ops:refresh"),
         InlineKeyboardButton(flip_label,   callback_data=flip_action)],
        [InlineKeyboardButton("🔒 Lock (force users off)",
                              callback_data="ops:lock")],
    ])


def killswitch_confirm_keyboard(action: str) -> InlineKeyboardMarkup:
    """Yes/No confirm for destructive killswitch actions (lock)."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirm", callback_data=f"ops:confirm:{action}"),
        InlineKeyboardButton("❌ Cancel",  callback_data="ops:cancel"),
    ]])
