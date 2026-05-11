"""Settings hub keyboards — UX Overhaul."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from . import grid_rows


def settings_hub_kb() -> InlineKeyboardMarkup:
    """Root Settings hub — replaces old auto-redeem-only surface."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Wallet",              callback_data="settings:wallet")],
        [InlineKeyboardButton("🎯 TP / SL",             callback_data="settings:tpsl")],
        [InlineKeyboardButton("💵 Capital Allocation",  callback_data="settings:capital")],
        [InlineKeyboardButton("⚖️ Risk Profile",        callback_data="settings:risk")],
        [InlineKeyboardButton("🔔 Notifications",       callback_data="settings:notifications")],
        [InlineKeyboardButton("📄 Mode (Paper/Live)",   callback_data="settings:mode")],
        [InlineKeyboardButton("↩️ Back to Main Menu",   callback_data="settings:back")],
    ])


def tp_preset_kb(current_tp: float | None) -> InlineKeyboardMarkup:
    """Step 1 of 2: Take Profit preset selection."""
    current_str = f"+{current_tp:.0f}%" if current_tp is not None else "not set"
    _ = current_str  # shown in message text, not in keyboard
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("+5%",  callback_data="tp_set:5"),
            InlineKeyboardButton("+10%", callback_data="tp_set:10"),
            InlineKeyboardButton("+15%", callback_data="tp_set:15"),
        ],
        [
            InlineKeyboardButton("+25%",   callback_data="tp_set:25"),
            InlineKeyboardButton("Custom", callback_data="tp_set:custom"),
        ],
        [InlineKeyboardButton("↩️ Back to Settings", callback_data="settings:hub")],
    ])


def sl_preset_kb(current_sl: float | None) -> InlineKeyboardMarkup:
    """Step 2 of 2: Stop Loss preset selection."""
    _ = current_sl  # shown in message text, not in keyboard
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("-5%",  callback_data="sl_set:5"),
            InlineKeyboardButton("-8%",  callback_data="sl_set:8"),
            InlineKeyboardButton("-10%", callback_data="sl_set:10"),
        ],
        [
            InlineKeyboardButton("-15%",   callback_data="sl_set:15"),
            InlineKeyboardButton("Custom", callback_data="sl_set:custom"),
        ],
        [InlineKeyboardButton("↩️ Back to Settings", callback_data="settings:hub")],
    ])


def tpsl_confirm_kb() -> InlineKeyboardMarkup:
    """Confirmation keyboard after TP+SL set."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("↩️ Back to Settings", callback_data="settings:hub"),
    ]])


def capital_preset_kb(balance: float, mode: str) -> InlineKeyboardMarkup:
    """Capital allocation preset buttons showing real dollar amounts."""
    def _btn(pct: int) -> InlineKeyboardButton:
        amount = balance * pct / 100.0
        return InlineKeyboardButton(
            f"{pct}% — ${amount:.0f}",
            callback_data=f"cap_set:{pct}",
        )

    return InlineKeyboardMarkup([
        [_btn(10)],
        [_btn(25)],
        [_btn(50)],
        [_btn(75)],
        [InlineKeyboardButton("Custom", callback_data="cap_set:custom")],
        [InlineKeyboardButton("↩️ Back to Settings", callback_data="settings:hub")],
    ])


def settings_menu(auto_redeem_mode: str) -> InlineKeyboardMarkup:
    """Legacy auto-redeem settings keyboard — kept for /settings command compat."""
    label = f"🏆 Auto-Redeem Mode: {auto_redeem_mode.title()}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(label, callback_data="settings:redeem")],
    ])


def autoredeem_settings_picker(current: str) -> InlineKeyboardMarkup:
    """2-column picker for instant / hourly / back."""
    def mark(m: str) -> str:
        return f"{'✅' if m == current else '◻️'} {m.title()}"
    buttons = [
        InlineKeyboardButton(mark("instant"),
                             callback_data="settings:redeem_set:instant"),
        InlineKeyboardButton(mark("hourly"),
                             callback_data="settings:redeem_set:hourly"),
        InlineKeyboardButton("⬅️ Back", callback_data="settings:hub"),
    ]
    return InlineKeyboardMarkup(grid_rows(buttons))


def settings_mode_picker(current: str) -> InlineKeyboardMarkup:
    """Mode picker scoped to Settings hub — Back routes to settings:hub."""
    def mark(m: str) -> str:
        return f"{'✅' if m == current else '◻️'} {m.title()}"
    buttons = [
        InlineKeyboardButton(mark("paper"), callback_data="set_mode:paper"),
        InlineKeyboardButton(mark("live") + " (Tier 4)", callback_data="set_mode:live"),
        InlineKeyboardButton("⬅️ Back", callback_data="settings:hub"),
    ]
    return InlineKeyboardMarkup(grid_rows(buttons))
