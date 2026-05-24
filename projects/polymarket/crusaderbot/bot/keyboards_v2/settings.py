"""Settings hub keyboards — grouped by domain.

Layout: 3 groups (Trading, Account, System) + admin conditional + nav.
Max 5 rows enforced. Uses mark_selected for toggle states.

Screens:
  1. settings_hub  — Grouped setting categories
  2. risk_picker   — Conservative / Balanced / Aggressive / Custom
  3. tp_picker     — Take Profit preset values
  4. sl_picker     — Stop Loss preset values
  5. mode_picker   — Paper / Live
  6. redeem_picker — Instant / Hourly
  7. capital_picker — Capital allocation %
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ._common import back_home_row, build_kb, mark_selected


def settings_hub_kb(*, is_admin: bool = False) -> InlineKeyboardMarkup:
    """Settings hub — grouped into Trading / Account sections. Max 5 rows."""
    rows: list[list[InlineKeyboardButton]] = [
        # Trading group
        [
            InlineKeyboardButton("⚖️ Risk",  callback_data="settings:risk"),
            InlineKeyboardButton("📑 Mode",   callback_data="settings:mode"),
        ],
        [
            InlineKeyboardButton("🎚️ TP/SL", callback_data="settings:tpsl"),
            InlineKeyboardButton("💰 Wallet", callback_data="settings:wallet"),
        ],
        # Account / System group
        [
            InlineKeyboardButton("🔔 Notifications", callback_data="settings:notifications"),
            InlineKeyboardButton("🏥 Health",         callback_data="settings:health"),
        ],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton("🧭 Admin", callback_data="settings:admin")])
    rows.append(back_home_row("menu:home"))
    return InlineKeyboardMarkup(rows)


def risk_picker_kb(current: str = "") -> InlineKeyboardMarkup:
    """Risk profile picker — 4 options + nav. 5 rows."""
    def _btn(key: str, emoji: str, label: str) -> InlineKeyboardButton:
        text = f"{emoji} {mark_selected(label, key == current)}"
        return InlineKeyboardButton(text, callback_data=f"set_risk:{key}")

    return build_kb(
        [
            [_btn("conservative", "🟢", "Conservative")],
            [_btn("balanced",     "🟡", "Balanced")],
            [_btn("aggressive",   "🔴", "Aggressive")],
            [_btn("custom",       "⚙️",  "Custom Risk")],
        ],
        nav=back_home_row("settings:hub"),
    )


def tp_picker_kb() -> InlineKeyboardMarkup:
    """Take Profit presets — 2-col grid + custom + nav. 4 rows."""
    return build_kb(
        [
            [
                InlineKeyboardButton("+5%",  callback_data="tp_set:5"),
                InlineKeyboardButton("+10%", callback_data="tp_set:10"),
            ],
            [
                InlineKeyboardButton("+15%", callback_data="tp_set:15"),
                InlineKeyboardButton("+25%", callback_data="tp_set:25"),
            ],
            [InlineKeyboardButton("✏️ Custom", callback_data="tp_set:custom")],
        ],
        nav=back_home_row("settings:hub"),
    )


def sl_picker_kb() -> InlineKeyboardMarkup:
    """Stop Loss presets — 2-col grid + custom + nav. 4 rows."""
    return build_kb(
        [
            [
                InlineKeyboardButton("-5%",  callback_data="sl_set:5"),
                InlineKeyboardButton("-8%",  callback_data="sl_set:8"),
            ],
            [
                InlineKeyboardButton("-10%", callback_data="sl_set:10"),
                InlineKeyboardButton("-15%", callback_data="sl_set:15"),
            ],
            [InlineKeyboardButton("✏️ Custom", callback_data="sl_set:custom")],
        ],
        nav=back_home_row("settings:hub"),
    )


def mode_picker_kb(current: str = "paper") -> InlineKeyboardMarkup:
    """Paper / Live mode picker. 2 rows."""
    return build_kb(
        [[
            InlineKeyboardButton(
                mark_selected("Paper", current == "paper"),
                callback_data="set_mode:paper",
            ),
            InlineKeyboardButton(
                mark_selected("Live", current == "live"),
                callback_data="set_mode:live",
            ),
        ]],
        nav=back_home_row("settings:hub"),
    )


def redeem_picker_kb(current: str = "hourly") -> InlineKeyboardMarkup:
    """Auto-redeem mode: Instant / Hourly. 2 rows."""
    return build_kb(
        [[
            InlineKeyboardButton(
                mark_selected("Instant", current == "instant"),
                callback_data="settings:redeem_set:instant",
            ),
            InlineKeyboardButton(
                mark_selected("Hourly", current == "hourly"),
                callback_data="settings:redeem_set:hourly",
            ),
        ]],
        nav=back_home_row("settings:hub"),
    )


def capital_picker_kb(balance: float) -> InlineKeyboardMarkup:
    """Capital allocation — shows real $ amounts. Max 5 rows."""
    def _btn(pct: int) -> InlineKeyboardButton:
        amount = balance * pct / 100.0
        return InlineKeyboardButton(
            f"{pct}% — ${amount:.0f}",
            callback_data=f"cap_set:{pct}",
        )

    return build_kb(
        [
            [_btn(10), _btn(25)],
            [_btn(50), _btn(75)],
            [InlineKeyboardButton("✏️ Custom", callback_data="cap_set:custom")],
        ],
        nav=back_home_row("settings:hub"),
    )


def tpsl_done_kb() -> InlineKeyboardMarkup:
    """Confirmation after TP+SL saved."""
    return InlineKeyboardMarkup([back_home_row("settings:hub")])
