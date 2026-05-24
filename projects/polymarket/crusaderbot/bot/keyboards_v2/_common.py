"""Shared keyboard helpers — buttons, rows, and layout utilities.

Every inline keyboard in this package MUST use these helpers for
navigation rows, confirmation dialogs, and pagination. This ensures
consistent UX across all screens.

Design rules enforced:
- Back + Home on every nested screen (escape hatch)
- Confirm/Cancel on every destructive action
- Pagination with page counter
- Grid helper respects MAX_COLS
- All labels use standardized emoji from _constants
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ._constants import (
    E_BACK, E_CANCEL, E_CONFIRM, E_HOME, E_REFRESH,
    MAX_COLS, NAV_BACK, NAV_CANCEL, NAV_HOME, NAV_NOOP, NAV_REFRESH,
)

# ── Singleton buttons (import these, don't recreate) ─────────────
BACK    = InlineKeyboardButton(f"{E_BACK} Back",    callback_data=NAV_BACK)
HOME    = InlineKeyboardButton(f"{E_HOME} Home",    callback_data=NAV_HOME)
REFRESH = InlineKeyboardButton(f"{E_REFRESH} Refresh", callback_data=NAV_REFRESH)
CANCEL  = InlineKeyboardButton(f"{E_CANCEL} Cancel",  callback_data=NAV_CANCEL)
NOOP    = InlineKeyboardButton("·",                   callback_data=NAV_NOOP)


# ── Row builders ─────────────────────────────────────────────────

def back_row(target: str = NAV_BACK) -> list[InlineKeyboardButton]:
    """Single back button. Use custom target for specific back destinations."""
    if target == NAV_BACK:
        return [BACK]
    return [InlineKeyboardButton(f"{E_BACK} Back", callback_data=target)]


def home_row() -> list[InlineKeyboardButton]:
    return [HOME]


def back_home_row(back_target: str = NAV_BACK) -> list[InlineKeyboardButton]:
    """Standard nav row: back + home. Append to every nested screen."""
    back_btn = BACK if back_target == NAV_BACK else InlineKeyboardButton(
        f"{E_BACK} Back", callback_data=back_target,
    )
    return [back_btn, HOME]


def refresh_home_row() -> list[InlineKeyboardButton]:
    return [REFRESH, HOME]


def confirm_cancel_row(
    confirm_cb: str,
    cancel_cb: str = NAV_CANCEL,
    confirm_label: str = f"{E_CONFIRM} Confirm",
    cancel_label: str = f"{E_CANCEL} Cancel",
) -> list[InlineKeyboardButton]:
    """Symmetric confirm/cancel for any destructive action."""
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
    """Three-column: ← Prev | 2/5 | Next →. Indicator is a noop tap."""
    return [
        InlineKeyboardButton("← Prev", callback_data=prev_cb),
        InlineKeyboardButton(f"{page}/{total}", callback_data=NAV_NOOP),
        InlineKeyboardButton("Next →", callback_data=next_cb),
    ]


# ── Layout helpers ───────────────────────────────────────────────

def grid_rows(
    buttons: list[InlineKeyboardButton],
    cols: int = MAX_COLS,
) -> list[list[InlineKeyboardButton]]:
    """Chunk a flat button list into rows of `cols` (default 2)."""
    return [buttons[i:i + cols] for i in range(0, len(buttons), cols)]


def build_kb(
    rows: list[list[InlineKeyboardButton]],
    *,
    nav: list[InlineKeyboardButton] | None = None,
) -> InlineKeyboardMarkup:
    """Build InlineKeyboardMarkup with optional nav row appended.

    Usage:
        build_kb(
            [[btn1, btn2], [btn3]],
            nav=back_home_row("dashboard:main"),
        )
    """
    all_rows = list(rows)
    if nav is not None:
        all_rows.append(nav)
    return InlineKeyboardMarkup(all_rows)


def mark_selected(label: str, is_selected: bool) -> str:
    """Prefix label with ✅ if selected, ◻️ otherwise."""
    return f"{'✅' if is_selected else '◻️'} {label}"
