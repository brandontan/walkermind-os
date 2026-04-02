"""MenuHandler — Telegram inline keyboard menu builders.

Builds all inline keyboard markup dicts for the bot UI.
No backend logic here — pure presentation layer.

Menus:
    main      — top-level navigation
    status    — live system status actions
    wallet    — wallet info actions
    settings  — risk / mode / strategy / notifications
    strategy  — per-strategy toggle list
    control   — pause / resume / stop

Usage::

    kb = build_main_menu()
    # kb is a list[list[dict]] (Telegram InlineKeyboardMarkup rows)
"""
from __future__ import annotations

from typing import Any

# ── Type alias ─────────────────────────────────────────────────────────────────
InlineKeyboard = list[list[dict[str, Any]]]


def _btn(text: str, data: str) -> dict[str, str]:
    """Shorthand for an inline keyboard button dict."""
    return {"text": text, "callback_data": data}


# ── Menu builders ──────────────────────────────────────────────────────────────


def build_main_menu() -> InlineKeyboard:
    """Main navigation menu.

    Layout::

        [📊 Status]   [💰 Wallet]
        [⚙️ Settings] [▶ Control]
    """
    return [
        [_btn("📊 Status", "status"),    _btn("💰 Wallet", "wallet")],
        [_btn("⚙️ Settings", "settings"), _btn("▶ Control", "control")],
    ]


def build_status_menu() -> InlineKeyboard:
    """Status detail actions."""
    return [
        [_btn("🔄 Refresh", "status"),       _btn("📈 Performance", "performance")],
        [_btn("🏥 Health", "health"),         _btn("📋 Strategies", "strategies")],
        [_btn("🏠 Main Menu", "main_menu")],
    ]


def build_wallet_menu() -> InlineKeyboard:
    """Wallet info actions (no withdraw — custodial only)."""
    return [
        [_btn("💵 Balance", "wallet_balance"),  _btn("📉 Exposure", "wallet_exposure")],
        [_btn("🔄 Refresh", "wallet"),          _btn("🏠 Main Menu", "main_menu")],
    ]


def build_settings_menu() -> InlineKeyboard:
    """Settings sub-menu."""
    return [
        [_btn("⚠️ Risk Level", "settings_risk"),    _btn("🔀 Mode", "settings_mode")],
        [_btn("📐 Strategy", "settings_strategy"),  _btn("🔔 Notifications", "settings_notify")],
        [_btn("🤖 Auto Trade", "settings_auto"),    _btn("🏠 Main Menu", "main_menu")],
    ]


def build_strategy_menu(
    strategies: list[str],
    active: str | None = None,
) -> InlineKeyboard:
    """Strategy selection menu.

    Shows one row per strategy.  Active strategy is marked with ✅.
    Only one strategy can be active at a time.

    Args:
        strategies: List of strategy identifiers.
        active: Currently active strategy id (None = none active).

    Returns:
        InlineKeyboard rows.
    """
    rows: InlineKeyboard = []
    for name in strategies:
        marker = "✅" if name == active else "⬜"
        rows.append([_btn(f"{marker} {name}", f"strategy_toggle_{name}")])
    rows.append([_btn("🏠 Main Menu", "main_menu")])
    return rows


def build_control_menu(system_state: str = "RUNNING") -> InlineKeyboard:
    """Control menu with state-aware buttons.

    Args:
        system_state: Current state string ("RUNNING", "PAUSED", "HALTED").

    Returns:
        InlineKeyboard rows.
    """
    rows: InlineKeyboard = []

    if system_state == "RUNNING":
        rows.append([_btn("⏸ Pause", "control_pause")])
    elif system_state == "PAUSED":
        rows.append([_btn("▶️ Resume", "control_resume")])
    else:
        # HALTED — no pause/resume available
        rows.append([_btn("🔴 HALTED (restart required)", "noop")])

    # Stop always available (except already halted)
    if system_state != "HALTED":
        rows.append([_btn("🛑 Stop (confirm)", "control_stop_confirm")])

    rows.append([_btn("🏠 Main Menu", "main_menu")])
    return rows


def build_stop_confirm_menu() -> InlineKeyboard:
    """Confirmation dialog for stop/kill action."""
    return [
        [_btn("⚠️ YES — Stop Trading", "control_stop_execute"),
         _btn("❌ Cancel", "control")],
    ]


def build_mode_confirm_menu(new_mode: str) -> InlineKeyboard:
    """Confirmation dialog for mode switch."""
    return [
        [_btn(f"✅ Confirm → {new_mode}", f"mode_confirm_{new_mode.lower()}"),
         _btn("❌ Cancel", "settings")],
    ]
