"""Advanced setup-wizard keyboards (/setup_advanced).

Behavior-preserving port of the legacy advanced setup flow. Callback
data (``setup:*``, ``set_strategy:*``, ``set_risk:*``, ``set_cat:*``,
``set_mode:*``, ``set_redeem:*``, ``strategy:*``) is preserved exactly so
the existing setup handler/parser keeps routing unchanged.
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ._common import grid_rows


def setup_menu() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton("🎯 Strategy",          callback_data="setup:strategy"),
        InlineKeyboardButton("⚖️ Risk Profile",      callback_data="setup:risk"),
        InlineKeyboardButton("🏷️ Categories",        callback_data="setup:categories"),
        InlineKeyboardButton("💰 Capital %",          callback_data="setup:capital"),
        InlineKeyboardButton("🎚️ TP / SL",           callback_data="setup:tpsl"),
        InlineKeyboardButton("👥 Copy Targets",       callback_data="setup:copy"),
        InlineKeyboardButton("🔁 Mode (Paper/Live)",  callback_data="setup:mode"),
        InlineKeyboardButton("🏆 Auto-redeem",        callback_data="setup:redeem"),
    ]
    return InlineKeyboardMarkup(grid_rows(buttons))


def strategy_picker(current: list[str]) -> InlineKeyboardMarkup:
    """Legacy checkbox picker — kept for presets and backward compat."""
    def mark(s: str) -> str:
        return f"{'✅' if s in current else '◻️'} {s.title().replace('_', ' ')}"
    buttons = [
        InlineKeyboardButton(mark("copy_trade"),
                             callback_data="set_strategy:copy_trade"),
        InlineKeyboardButton(mark("signal"), callback_data="set_strategy:signal"),
        InlineKeyboardButton(mark("value"),  callback_data="set_strategy:value"),
        InlineKeyboardButton("⬅ Back", callback_data="setup:menu"),
    ]
    return InlineKeyboardMarkup(grid_rows(buttons))


def strategy_card_kb() -> InlineKeyboardMarkup:
    """Descriptive strategy card keyboard — shown in the Auto-Trade menu."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Select Signal",        callback_data="strategy:signal")],
        [InlineKeyboardButton("Select Edge Finder",   callback_data="strategy:edge_finder")],
        [InlineKeyboardButton("Select Momentum",      callback_data="strategy:momentum_reversal")],
        [InlineKeyboardButton("⚡ Select All",         callback_data="strategy:all")],
        [InlineKeyboardButton("⬅ Back to Main Menu",  callback_data="strategy:back")],
    ])


def risk_picker(current: str) -> InlineKeyboardMarkup:
    def mark(r: str) -> str:
        return f"{'✅' if r == current else '◻️'} {r.title()}"
    buttons = [
        InlineKeyboardButton(mark("conservative"),
                             callback_data="set_risk:conservative"),
        InlineKeyboardButton(mark("balanced"),  callback_data="set_risk:balanced"),
        InlineKeyboardButton(mark("aggressive"), callback_data="set_risk:aggressive"),
        InlineKeyboardButton(
            f"{'✅' if current == 'custom' else '◻️'} ⚙️ Custom Risk",
            callback_data="set_risk:custom",
        ),
        InlineKeyboardButton("⬅ Back", callback_data="setup:menu"),
    ]
    return InlineKeyboardMarkup(grid_rows(buttons))


def category_picker(current: list[str] | None) -> InlineKeyboardMarkup:
    cur = set(current or [])
    def mark(c: str) -> str:
        return f"{'✅' if c in cur or not cur and c == 'all' else '◻️'} {c.title()}"
    cats = ["all", "politics", "sports", "crypto", "tech", "culture"]
    buttons = [InlineKeyboardButton(mark(c), callback_data=f"set_cat:{c}")
               for c in cats]
    buttons.append(InlineKeyboardButton("⬅ Back", callback_data="setup:menu"))
    return InlineKeyboardMarkup(grid_rows(buttons))


def mode_picker(current: str) -> InlineKeyboardMarkup:
    def mark(m: str) -> str:
        return f"{'✅' if m == current else '◻️'} {m.title()}"
    buttons = [
        InlineKeyboardButton(mark("paper"),  callback_data="set_mode:paper"),
        InlineKeyboardButton(mark("live"),   callback_data="set_mode:live"),
        InlineKeyboardButton("⬅ Back", callback_data="setup:menu"),
    ]
    return InlineKeyboardMarkup(grid_rows(buttons))


def autoredeem_picker(current: str) -> InlineKeyboardMarkup:
    def mark(m: str) -> str:
        return f"{'✅' if m == current else '◻️'} {m.title()}"
    buttons = [
        InlineKeyboardButton(mark("instant"), callback_data="set_redeem:instant"),
        InlineKeyboardButton(mark("hourly"),  callback_data="set_redeem:hourly"),
    ]
    return InlineKeyboardMarkup(grid_rows(buttons))
