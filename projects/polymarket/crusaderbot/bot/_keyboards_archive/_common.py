"""Shared inline-keyboard row helpers — Tactical Terminal polish.

Use the new ``nav:`` / ``act:`` / ``cfg:`` callback_data prefixes for any
keyboard rewritten as part of the bot polish pass. Legacy prefixes
(``p5:``, ``setup:``, ``dashboard:``, ``wallet:`` etc.) remain registered
in the dispatcher for backwards-compat with in-flight messages and are
phased out gradually.

All helpers return ``list[InlineKeyboardButton]`` (a single row); callers
wrap them into ``InlineKeyboardMarkup`` with their own keyboard layout.
"""
from __future__ import annotations

from telegram import InlineKeyboardButton

# ── Navigation prefixes ──────────────────────────────────────────────────────
NAV_HOME    = "nav:home"
NAV_BACK    = "nav:back"
NAV_REFRESH = "nav:refresh"


def home_row() -> list[InlineKeyboardButton]:
    """Single-button row with a Home action."""
    return [InlineKeyboardButton("🏠 Home", callback_data=NAV_HOME)]


def home_back_row(back_cb: str = NAV_BACK) -> list[InlineKeyboardButton]:
    """Two-column nav row: back arrow on the left, home on the right.

    Use this on every nested screen so the user always has an escape hatch.
    """
    return [
        InlineKeyboardButton("⬅ Back", callback_data=back_cb),
        InlineKeyboardButton("🏠 Home", callback_data=NAV_HOME),
    ]


def confirm_cancel_row(
    confirm_cb: str,
    cancel_cb: str = NAV_BACK,
    confirm_label: str = "✓ Confirm",
    cancel_label:  str = "✕ Cancel",
) -> list[InlineKeyboardButton]:
    """Symmetric confirm/cancel row used by any destructive flow."""
    return [
        InlineKeyboardButton(confirm_label, callback_data=confirm_cb),
        InlineKeyboardButton(cancel_label,  callback_data=cancel_cb),
    ]


def pagination_row(
    prev_cb: str,
    next_cb: str,
    page: int,
    total: int,
) -> list[InlineKeyboardButton]:
    """Three-column pagination row with a neutral page indicator in the middle.

    Indicator uses ``nav:noop`` so taps are silently absorbed by the
    dispatcher (handler is a no-op).
    """
    return [
        InlineKeyboardButton("← Prev", callback_data=prev_cb),
        InlineKeyboardButton(f"{page}/{total}", callback_data="nav:noop"),
        InlineKeyboardButton("Next →", callback_data=next_cb),
    ]
