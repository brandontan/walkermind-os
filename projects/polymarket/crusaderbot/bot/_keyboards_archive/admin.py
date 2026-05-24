"""Admin/Ops-plane inline keyboards (R12f operator dashboard)."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from . import grid_rows
from ._common import confirm_cancel_row


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


def operator_panel_keyboard() -> InlineKeyboardMarkup:
    """Consolidated operator control panel (/panel).

    Start = release kill switch (resume), Stop = engage kill switch (pause).
    Both stay visible regardless of state so the operator always sees the full
    control surface; the live run-state is shown in the panel body (_render_root),
    so the keyboard itself is static. Lock is kept on its own row — it is
    destructive (forces every user off auto-trade).
    """
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ Start", callback_data="panel:start"),
         InlineKeyboardButton("⏹ Stop",  callback_data="panel:stop")],
        [InlineKeyboardButton("📊 Status", callback_data="panel:status"),
         InlineKeyboardButton("📈 Stats",  callback_data="panel:stats")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="panel:settings"),
         InlineKeyboardButton("❓ Help",     callback_data="panel:help")],
        [InlineKeyboardButton("🔒 Lock (force users off)",
                              callback_data="panel:lock")],
        [InlineKeyboardButton("🔄 Refresh", callback_data="panel:refresh")],
    ])


def killswitch_confirm_keyboard(action: str) -> InlineKeyboardMarkup:
    """Yes/No confirm for destructive killswitch actions (lock)."""
    return InlineKeyboardMarkup([
        confirm_cancel_row(
            f"ops:confirm:{action}", "ops:cancel", "✅ Confirm", "❌ Cancel",
        ),
    ])
