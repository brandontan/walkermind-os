"""Settings hub keyboards — MVP Reset V1."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from . import grid_rows


def settings_hub_kb(is_admin: bool = False) -> InlineKeyboardMarkup:
    """Hybrid Luxury settings hub — premium stub surfaces included."""
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton("👤 Profile",       callback_data="settings:profile"),
            InlineKeyboardButton("👑 Premium",       callback_data="settings:premium"),
        ],
        [
            InlineKeyboardButton("🎁 Referrals",     callback_data="settings:referrals"),
            InlineKeyboardButton("🏥 Health",        callback_data="settings:health"),
        ],
        [
            InlineKeyboardButton("🔐 Live Gate",     callback_data="settings:live_gate"),
            InlineKeyboardButton("⚖️ Risk",          callback_data="settings:risk"),
        ],
        [InlineKeyboardButton("🔔 Notifications", callback_data="settings:notifications")],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton("🧭 Admin", callback_data="settings:admin")])
    rows.append([
        InlineKeyboardButton("⬅ Back", callback_data="settings:back"),
        InlineKeyboardButton("🏠 Home", callback_data="dashboard:main"),
    ])
    return InlineKeyboardMarkup(rows)


# MVP RESET V1 — deprecated UI flow
def _legacy_settings_hub_kb(is_admin: bool = False) -> InlineKeyboardMarkup:
    """Legacy 8-item settings hub — archived, not reachable from main flow."""
    rows = [
        [
            InlineKeyboardButton("👤 Profile",        callback_data="settings:profile"),
            InlineKeyboardButton("🔔 Notifications",  callback_data="settings:notifications"),
        ],
        [
            InlineKeyboardButton("🛡️ Risk",           callback_data="settings:risk"),
            InlineKeyboardButton("👛 Wallet",          callback_data="settings:wallet"),
        ],
        [
            InlineKeyboardButton("👑 Premium",         callback_data="settings:premium"),
            InlineKeyboardButton("🎁 Referrals",       callback_data="settings:referrals"),
        ],
        [
            InlineKeyboardButton("🏥 Health",          callback_data="settings:health"),
            InlineKeyboardButton("🔐 Live Gate",       callback_data="settings:live_gate"),
        ],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton("🧭 Admin", callback_data="settings:admin")])
    rows.append([
        InlineKeyboardButton("⬅️ Back", callback_data="settings:back"),
        InlineKeyboardButton("🏠 Home", callback_data="dashboard:main"),
    ])
    return InlineKeyboardMarkup(rows)


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
            InlineKeyboardButton("+25%",      callback_data="tp_set:25"),
            InlineKeyboardButton("✏️ Custom", callback_data="tp_set:custom"),
        ],
        [InlineKeyboardButton("⬅ Back", callback_data="settings:hub")],
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
            InlineKeyboardButton("-15%",      callback_data="sl_set:15"),
            InlineKeyboardButton("✏️ Custom", callback_data="sl_set:custom"),
        ],
        [InlineKeyboardButton("⬅ Back", callback_data="settings:hub")],
    ])


def tpsl_confirm_kb() -> InlineKeyboardMarkup:
    """Confirmation keyboard after TP+SL set."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅ Back", callback_data="settings:hub"),
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
        [InlineKeyboardButton("✏️ Custom", callback_data="cap_set:custom")],
        [InlineKeyboardButton("⬅ Back", callback_data="settings:hub")],
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
