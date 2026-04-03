"""Inline keyboard builders — standardized action:<name> callback format.

All callback_data values follow the format: ``action:<name>``

This ensures every button press is routed through CallbackRouter which
uses editMessageText (inline UI, no duplicate messages).

Usage::

    from .telegram.ui.keyboard import build_main_menu

    payload = {"_keyboard": build_main_menu()}
"""
from __future__ import annotations

from typing import Any

# ── Type alias ─────────────────────────────────────────────────────────────────
InlineKeyboard = list[list[dict[str, Any]]]

# ── Prefix ─────────────────────────────────────────────────────────────────────
_PREFIX = "action:"


def _btn(text: str, action: str) -> dict[str, str]:
    """Shorthand for an inline keyboard button with action:<name> data."""
    return {"text": text, "callback_data": f"{_PREFIX}{action}"}


# ── Main navigation ────────────────────────────────────────────────────────────


def build_main_menu() -> InlineKeyboard:
    """Top-level navigation menu.

    Layout::

        [📊 Status]    [💰 Wallet  ]
        [⚙️ Settings]  [▶  Control ]
    """
    return [
        [_btn("📊 Status",    "status"),   _btn("💰 Wallet",  "wallet")],
        [_btn("⚙️ Settings", "settings"),  _btn("▶ Control", "control")],
    ]


# ── Status sub-menu ────────────────────────────────────────────────────────────


def build_status_menu() -> InlineKeyboard:
    """Status detail actions."""
    return [
        [_btn("🔄 Refresh", "refresh"), _btn("🏠 Main Menu", "back_main")],
    ]


# ── Wallet sub-menu ────────────────────────────────────────────────────────────


def build_wallet_menu() -> InlineKeyboard:
    """Wallet info actions — includes Withdraw button."""
    return [
        [_btn("💵 Balance",    "wallet_balance"),  _btn("📉 Exposure",   "wallet_exposure")],
        [_btn("💸 Withdraw",   "wallet_withdraw"),  _btn("🔄 Refresh",    "wallet")],
        [_btn("🏠 Main Menu",  "back_main")],
    ]


# ── Settings sub-menu ──────────────────────────────────────────────────────────


def build_settings_menu() -> InlineKeyboard:
    """Settings sub-menu."""
    return [
        [_btn("⚠️ Risk Level",    "settings_risk"),    _btn("🔀 Mode",           "settings_mode")],
        [_btn("📐 Strategy",       "settings_strategy"), _btn("🔔 Notifications",  "settings_notify")],
        [_btn("🤖 Auto Trade",     "settings_auto"),     _btn("🏠 Main Menu",      "back_main")],
    ]


def build_strategy_menu(
    strategies: list[str],
    active: str | None = None,
) -> InlineKeyboard:
    """Per-strategy toggle list.  Active strategy marked with ✅."""
    rows: InlineKeyboard = []
    for name in strategies:
        marker = "✅" if name == active else "⬜"
        rows.append([_btn(f"{marker} {name}", f"strategy_toggle_{name}")])
    rows.append([_btn("🏠 Main Menu", "back_main")])
    return rows


def build_mode_confirm_menu(new_mode: str) -> InlineKeyboard:
    """Confirmation dialog for mode switch."""
    return [
        [
            _btn(f"✅ Confirm → {new_mode}", f"mode_confirm_{new_mode.lower()}"),
            _btn("❌ Cancel", "settings"),
        ],
    ]


# ── Control sub-menu ───────────────────────────────────────────────────────────


def build_control_menu(system_state: str = "RUNNING") -> InlineKeyboard:
    """State-aware control menu.

    Args:
        system_state: ``"RUNNING"`` | ``"PAUSED"`` | ``"HALTED"``.
    """
    rows: InlineKeyboard = []

    if system_state == "RUNNING":
        rows.append([_btn("⏸ Pause", "control_pause")])
    elif system_state == "PAUSED":
        rows.append([_btn("▶️ Resume", "control_resume")])
    else:
        rows.append([_btn("🔴 HALTED (restart required)", "noop")])

    if system_state != "HALTED":
        rows.append([_btn("🛑 Stop (confirm)", "control_stop_confirm")])

    rows.append([_btn("🏠 Main Menu", "back_main")])
    return rows


def build_stop_confirm_menu() -> InlineKeyboard:
    """Confirmation dialog for stop/halt action."""
    return [
        [
            _btn("⚠️ YES — Stop Trading", "control_stop_execute"),
            _btn("❌ Cancel", "control"),
        ],
    ]
