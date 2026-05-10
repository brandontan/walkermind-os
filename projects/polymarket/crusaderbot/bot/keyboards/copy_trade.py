"""Inline keyboards for the Copy Trade surface (Phase 5E).

Callback prefix: copytrade:

Patterns:
    copytrade:dashboard        — main dashboard view
    copytrade:add              — add wallet screen (two paths)
    copytrade:paste            — trigger paste-address input mode
    copytrade:discover         — smart discovery leaderboard (default filter)
    copytrade:discover:<f>     — leaderboard with filter f
    copytrade:stats:<addr>     — wallet stats card
    copytrade:copy:<addr>      — begin copy task setup (Phase 5F wizard)
    copytrade:pause:<task_id>  — toggle task pause / resume
    copytrade:edit:<task_id>   — edit task (Phase 5F wizard)
    copytrade:remove:<addr>    — legacy: remove copy_targets row
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from . import grid_rows

_DISCOVER_FILTERS: list[tuple[str, str]] = [
    ("🪙 Crypto",    "crypto"),
    ("🏅 Sports",    "sports"),
    ("🗳 Politics",  "politics"),
    ("🌍 World",     "world"),
    ("💰 Top PnL",   "top_pnl"),
    ("🎯 Top WR",    "top_wr"),
]


def copy_trade_empty_kb() -> InlineKeyboardMarkup:
    """Dashboard empty state — no tasks yet."""
    buttons = [
        InlineKeyboardButton("➕ Add Wallet", callback_data="copytrade:add"),
        InlineKeyboardButton("🔍 Discover",   callback_data="copytrade:discover"),
    ]
    return InlineKeyboardMarkup(grid_rows(buttons))


def copy_trade_task_list_kb(
    task_ids: list[str],
    statuses: list[str],
) -> InlineKeyboardMarkup:
    """Per-task [Pause/Resume] [Edit] rows plus nav buttons at the bottom."""
    rows: list[list] = []
    for task_id, status in zip(task_ids, statuses):
        pause_label = "▶️ Resume" if status == "paused" else "⏸ Pause"
        rows.append([
            InlineKeyboardButton(
                pause_label, callback_data=f"copytrade:pause:{task_id}",
            ),
            InlineKeyboardButton(
                "✏️ Edit", callback_data=f"copytrade:edit:{task_id}",
            ),
        ])
    nav = [
        InlineKeyboardButton("➕ Add Wallet", callback_data="copytrade:add"),
        InlineKeyboardButton("🔍 Discover",   callback_data="copytrade:discover"),
    ]
    rows.append(nav)
    return InlineKeyboardMarkup(rows)


def copy_trade_add_wallet_kb() -> InlineKeyboardMarkup:
    """Two-path add wallet screen."""
    top = grid_rows([
        InlineKeyboardButton("📋 Paste Address", callback_data="copytrade:paste"),
        InlineKeyboardButton("🔍 Discover",      callback_data="copytrade:discover"),
    ])
    bottom = [[InlineKeyboardButton("← Back", callback_data="copytrade:dashboard")]]
    return InlineKeyboardMarkup(top + bottom)


def wallet_stats_kb(address: str) -> InlineKeyboardMarkup:
    """Stats card actions: copy or go back."""
    buttons = [
        InlineKeyboardButton(
            "🐋 Copy This Wallet", callback_data=f"copytrade:copy:{address}",
        ),
        InlineKeyboardButton("← Back", callback_data="copytrade:add"),
    ]
    return InlineKeyboardMarkup(grid_rows(buttons))


def discover_filter_kb(active_filter: str = "top_pnl") -> InlineKeyboardMarkup:
    """Filter row (2-col grid) for the leaderboard, plus Back button."""
    buttons = [
        InlineKeyboardButton(
            f"{'✅ ' if f == active_filter else ''}{label}",
            callback_data=f"copytrade:discover:{f}",
        )
        for label, f in _DISCOVER_FILTERS
    ]
    back = InlineKeyboardButton("← Back", callback_data="copytrade:add")
    return InlineKeyboardMarkup(grid_rows(buttons) + [[back]])


def discover_wallet_kb(address: str) -> InlineKeyboardMarkup:
    """Per-wallet action in the leaderboard view."""
    buttons = [
        InlineKeyboardButton(
            "🐋 Copy This Wallet", callback_data=f"copytrade:copy:{address}",
        ),
        InlineKeyboardButton("← Back", callback_data="copytrade:discover"),
    ]
    return InlineKeyboardMarkup(grid_rows(buttons))


def _truncate_wallet(address: str) -> str:
    """0x12345678…abcd-style display label for a 0x + 40-hex address."""
    if len(address) < 12:
        return address
    return f"{address[:8]}…{address[-4:]}"


def copy_targets_list_kb(wallet_addresses) -> InlineKeyboardMarkup:
    """Legacy: one [🗑 Stop] button per active copy target (copy_targets table)."""
    rows = [
        [
            InlineKeyboardButton(
                f"🗑 Stop {_truncate_wallet(addr)}",
                callback_data=f"copytrade:remove:{addr}",
            )
        ]
        for addr in wallet_addresses
    ]
    return InlineKeyboardMarkup(rows)


# ---------------------------------------------------------------------------
# Phase 5F — Wizard step keyboards
# ---------------------------------------------------------------------------


def wizard_amount_mode_kb() -> InlineKeyboardMarkup:
    """Step 1/3: choose Fixed Amount vs Percentage Mirror mode."""
    buttons = [
        InlineKeyboardButton("💵 Fixed Amount", callback_data="wizard:mode:fixed"),
        InlineKeyboardButton("📊 % Mirror",      callback_data="wizard:mode:pct"),
    ]
    cancel = InlineKeyboardButton("✕ Cancel", callback_data="wizard:cancel")
    return InlineKeyboardMarkup(grid_rows(buttons) + [[cancel]])


def wizard_step1_fixed_kb() -> InlineKeyboardMarkup:
    """Step 1/3 — Fixed mode: preset amount buttons + Custom."""
    buttons = [
        InlineKeyboardButton("$1",  callback_data="wizard:fixed:1"),
        InlineKeyboardButton("$5",  callback_data="wizard:fixed:5"),
        InlineKeyboardButton("$10", callback_data="wizard:fixed:10"),
        InlineKeyboardButton("$25", callback_data="wizard:fixed:25"),
        InlineKeyboardButton("✏️ Custom", callback_data="wizard:custom:amount"),
        InlineKeyboardButton("← Mode",   callback_data="wizard:back:mode"),
    ]
    return InlineKeyboardMarkup(grid_rows(buttons))


def wizard_step1_pct_kb() -> InlineKeyboardMarkup:
    """Step 1/3 — % Mirror mode: preset pct buttons + Custom."""
    buttons = [
        InlineKeyboardButton("5%",  callback_data="wizard:pct:5"),
        InlineKeyboardButton("10%", callback_data="wizard:pct:10"),
        InlineKeyboardButton("25%", callback_data="wizard:pct:25"),
        InlineKeyboardButton("50%", callback_data="wizard:pct:50"),
        InlineKeyboardButton("✏️ Custom", callback_data="wizard:custom:pct"),
        InlineKeyboardButton("← Mode",   callback_data="wizard:back:mode"),
    ]
    return InlineKeyboardMarkup(grid_rows(buttons))


def wizard_step2_kb() -> InlineKeyboardMarkup:
    """Step 2/3: Keep Defaults or Edit risk controls."""
    buttons = [
        InlineKeyboardButton("✅ Keep Defaults", callback_data="wizard:keep"),
        InlineKeyboardButton("✏️ Edit",           callback_data="wizard:risk:edit"),
    ]
    back = InlineKeyboardButton("← Back", callback_data="wizard:back:step1")
    return InlineKeyboardMarkup(grid_rows(buttons) + [[back]])


def wizard_step2_edit_kb(
    tp: str, sl: str, max_daily: str, slippage: str, min_trade: str,
) -> InlineKeyboardMarkup:
    """Step 2/3 edit mode: each risk setting as a tappable button."""
    buttons = [
        InlineKeyboardButton(f"TP: {tp}",         callback_data="wizard:custom:tp"),
        InlineKeyboardButton(f"SL: {sl}",         callback_data="wizard:custom:sl"),
        InlineKeyboardButton(f"Max/Day: {max_daily}", callback_data="wizard:custom:maxd"),
        InlineKeyboardButton(f"Slip: {slippage}", callback_data="wizard:custom:slip"),
        InlineKeyboardButton(f"Min: {min_trade}", callback_data="wizard:custom:min"),
        InlineKeyboardButton("✅ Done",            callback_data="wizard:keep"),
    ]
    return InlineKeyboardMarkup(grid_rows(buttons))


def wizard_step3_kb() -> InlineKeyboardMarkup:
    """Step 3/3: Start Copying or go Back."""
    buttons = [
        InlineKeyboardButton("🚀 Start Copying", callback_data="wizard:confirm"),
        InlineKeyboardButton("← Back",           callback_data="wizard:back:step2"),
    ]
    return InlineKeyboardMarkup(grid_rows(buttons))


def wizard_success_kb() -> InlineKeyboardMarkup:
    """Post-creation success nav: Copy Trade dashboard or main Dashboard."""
    buttons = [
        InlineKeyboardButton("🐋 Copy Trade", callback_data="copytrade:dashboard"),
        InlineKeyboardButton("📊 Dashboard",  callback_data="dashboard:main"),
    ]
    return InlineKeyboardMarkup(grid_rows(buttons))


def wizard_custom_cancel_kb(back_data: str) -> InlineKeyboardMarkup:
    """Cancel button for custom text input prompts."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✕ Cancel", callback_data=back_data),
    ]])


# ---------------------------------------------------------------------------
# Phase 5F — Per-task edit screen keyboards
# ---------------------------------------------------------------------------


def edit_task_main_kb(task: object) -> InlineKeyboardMarkup:
    """Full edit grid showing current field values for the task."""
    tid = str(task.id)
    status = task.status
    pause_label = "▶️ Resume" if status == "paused" else "⏸ Pause"
    rev_label = f"🔄 Rev: {'ON' if task.reverse_copy else 'OFF'}"
    rows = [
        [
            InlineKeyboardButton(
                f"💵 ${float(task.copy_amount):.2f}",
                callback_data=f"wizard:efc:{tid}:amount",
            ),
            InlineKeyboardButton(
                f"📈 TP +{float(task.tp_pct) * 100:.0f}%",
                callback_data=f"wizard:efc:{tid}:tp",
            ),
        ],
        [
            InlineKeyboardButton(
                f"📉 SL -{float(task.sl_pct) * 100:.0f}%",
                callback_data=f"wizard:efc:{tid}:sl",
            ),
            InlineKeyboardButton(
                f"💳 ${float(task.max_daily_spend):.0f}/d",
                callback_data=f"wizard:efc:{tid}:maxd",
            ),
        ],
        [
            InlineKeyboardButton(
                f"🔀 Slip {float(task.slippage_pct) * 100:.0f}%",
                callback_data=f"wizard:efc:{tid}:slip",
            ),
            InlineKeyboardButton(
                f"📏 Min ${float(task.min_trade_size):.2f}",
                callback_data=f"wizard:efc:{tid}:min",
            ),
        ],
        [
            InlineKeyboardButton(rev_label,       callback_data=f"wizard:ef:{tid}:rev"),
            InlineKeyboardButton("✏️ Rename",     callback_data=f"wizard:erename:{tid}"),
        ],
        [
            InlineKeyboardButton(pause_label,     callback_data=f"wizard:epause:{tid}"),
            InlineKeyboardButton("🗑 Delete",     callback_data=f"wizard:edel:ask:{tid}"),
        ],
        [
            InlineKeyboardButton("📊 PnL",        callback_data=f"wizard:epnl:{tid}"),
            InlineKeyboardButton("← Back",        callback_data="wizard:eback"),
        ],
    ]
    return InlineKeyboardMarkup(rows)


def edit_delete_confirm_kb(task_id: str) -> InlineKeyboardMarkup:
    """Delete confirmation: Yes / Cancel."""
    buttons = [
        InlineKeyboardButton("✅ Yes, Delete", callback_data=f"wizard:edel:yes:{task_id}"),
        InlineKeyboardButton("❌ Cancel",      callback_data=f"wizard:edel:no:{task_id}"),
    ]
    return InlineKeyboardMarkup(grid_rows(buttons))
