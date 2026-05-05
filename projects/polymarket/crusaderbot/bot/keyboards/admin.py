"""Admin/Ops-plane inline keyboards (R12f operator dashboard).

Kept in its own module to keep the legacy ``admin_menu`` (in
``keyboards/__init__.py``) stable while the new dashboard surface gets
its own callback prefix (``ops:``) and renderer-specific buttons.
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def ops_dashboard_keyboard(kill_active: bool) -> InlineKeyboardMarkup:
    """Refresh + quick-action keyboard rendered under /ops_dashboard.

    Buttons:
        - Refresh (re-fetches the snapshot)
        - Pause / Resume (single button — label flips with current state)
        - Lock (always present; destructive — separate row to avoid
          accidental taps).
    """
    flip_label = "▶️ Resume" if kill_active else "⏸ Pause"
    flip_action = "ops:resume" if kill_active else "ops:pause"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="ops:refresh")],
        [InlineKeyboardButton(flip_label, callback_data=flip_action)],
        [InlineKeyboardButton("🔒 Lock (force users off)",
                              callback_data="ops:lock")],
    ])


def killswitch_confirm_keyboard(action: str) -> InlineKeyboardMarkup:
    """Yes/No confirm for destructive killswitch actions (lock).

    ``action`` is the ops verb being confirmed (``pause`` / ``resume`` /
    ``lock``); the callback payload encodes it so the handler does not
    need a context-stash.
    """
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirm", callback_data=f"ops:confirm:{action}"),
        InlineKeyboardButton("❌ Cancel", callback_data="ops:cancel"),
    ]])
