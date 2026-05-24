"""Customize wizard keyboards — step-by-step preset configuration.

Wizard flow (5 steps):
  1. Capital allocation (25/50/75/100%)
  2. Take Profit (+10/15/20/30% or custom)
  3. Stop Loss (-5/8/10/15% or custom)
  4. Copy targets (browse or skip) — only for copy_trade presets
  5. Review & save

Each step has Back to previous step. Step 1 has Cancel.
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ._common import back_home_row, build_kb, grid_rows


def wizard_capital_kb() -> InlineKeyboardMarkup:
    """Step 1/5: Capital allocation — 2-col grid + Cancel. 3 rows."""
    pct_buttons = [
        InlineKeyboardButton("25%",  callback_data="customize:capital:25"),
        InlineKeyboardButton("50%",  callback_data="customize:capital:50"),
        InlineKeyboardButton("75%",  callback_data="customize:capital:75"),
        InlineKeyboardButton("100%", callback_data="customize:capital:100"),
    ]
    return InlineKeyboardMarkup(
        grid_rows(pct_buttons)
        + [[InlineKeyboardButton("❌ Cancel", callback_data="customize:cancel")]],
    )


def wizard_tp_kb() -> InlineKeyboardMarkup:
    """Step 2/5: Take Profit — 2-col grid + custom + back. 4 rows."""
    pct_buttons = [
        InlineKeyboardButton("+10%", callback_data="customize:tp:10"),
        InlineKeyboardButton("+15%", callback_data="customize:tp:15"),
        InlineKeyboardButton("+20%", callback_data="customize:tp:20"),
        InlineKeyboardButton("+30%", callback_data="customize:tp:30"),
    ]
    return InlineKeyboardMarkup(
        grid_rows(pct_buttons) + [[
            InlineKeyboardButton("✏️ Custom", callback_data="customize:tp:custom"),
            InlineKeyboardButton("⬅ Back",   callback_data="customize:back:capital"),
        ]],
    )


def wizard_sl_kb() -> InlineKeyboardMarkup:
    """Step 3/5: Stop Loss — 2-col grid + custom + back. 4 rows."""
    pct_buttons = [
        InlineKeyboardButton("-5%",  callback_data="customize:sl:5"),
        InlineKeyboardButton("-8%",  callback_data="customize:sl:8"),
        InlineKeyboardButton("-10%", callback_data="customize:sl:10"),
        InlineKeyboardButton("-15%", callback_data="customize:sl:15"),
    ]
    return InlineKeyboardMarkup(
        grid_rows(pct_buttons) + [[
            InlineKeyboardButton("✏️ Custom", callback_data="customize:sl:custom"),
            InlineKeyboardButton("⬅ Back",   callback_data="customize:back:tp"),
        ]],
    )


def wizard_targets_kb() -> InlineKeyboardMarkup:
    """Step 4/5: Copy targets (conditional). 3 rows."""
    return build_kb(
        [
            [InlineKeyboardButton("🐋 Browse Top Wallets",
                                  callback_data="customize:targets:browse")],
            [InlineKeyboardButton("Skip",
                                  callback_data="customize:targets:skip")],
        ],
        nav=[InlineKeyboardButton("⬅ Back", callback_data="customize:back:sl")],
    )


def wizard_review_kb() -> InlineKeyboardMarkup:
    """Step 5/5: Review — Start + Back. 1 row."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("▶ Start Auto Trade", callback_data="customize:save"),
        InlineKeyboardButton("⬅ Back",             callback_data="customize:back:sl"),
    ]])


def wizard_custom_input_kb(back_step: str) -> InlineKeyboardMarkup:
    """Shown while user types a custom TP/SL value. 1 row."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅ Back", callback_data=f"customize:back:{back_step}"),
    ]])


def wizard_done_kb() -> InlineKeyboardMarkup:
    """Success screen — status or home. 1 row."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("📊 Auto Trade Status", callback_data="preset:status"),
        InlineKeyboardButton("🏠 Home",              callback_data="menu:home"),
    ]])


# ── Legacy p5:customize:* wizard (handlers/customize.py surface) ─────
# Callback data preserved exactly for the existing ConversationHandler parser.

def customize_capital_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("25%",  callback_data="p5:customize:cap:25"),
            InlineKeyboardButton("50%",  callback_data="p5:customize:cap:50"),
            InlineKeyboardButton("75%",  callback_data="p5:customize:cap:75"),
            InlineKeyboardButton("100%", callback_data="p5:customize:cap:100"),
        ],
    ])


def customize_tp_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("+10%", callback_data="p5:customize:tp:10"),
            InlineKeyboardButton("+15%", callback_data="p5:customize:tp:15"),
            InlineKeyboardButton("+20%", callback_data="p5:customize:tp:20"),
            InlineKeyboardButton("+30%", callback_data="p5:customize:tp:30"),
        ],
        [InlineKeyboardButton("Custom", callback_data="p5:customize:tp:custom")],
    ])


def customize_sl_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("-5%",  callback_data="p5:customize:sl:5"),
            InlineKeyboardButton("-8%",  callback_data="p5:customize:sl:8"),
            InlineKeyboardButton("-10%", callback_data="p5:customize:sl:10"),
            InlineKeyboardButton("-15%", callback_data="p5:customize:sl:15"),
        ],
        [InlineKeyboardButton("Custom", callback_data="p5:customize:sl:custom")],
    ])


def customize_targets_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🐋 Browse Top Wallets", callback_data="p5:customize:targets:browse")],
        [InlineKeyboardButton("Skip",                   callback_data="p5:customize:targets:skip")],
    ])


def customize_review_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Save", callback_data="p5:customize:save"),
            InlineKeyboardButton("⬅ Back", callback_data="p5:customize:back"),
        ],
    ])
