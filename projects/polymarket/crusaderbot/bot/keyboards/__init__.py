"""All inline + reply keyboards in one place."""
from __future__ import annotations

from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, ReplyKeyboardMarkup,
)


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("📊 Dashboard"), KeyboardButton("🤖 Auto-Trade")],
            [KeyboardButton("💰 Wallet"),    KeyboardButton("📈 My Trades")],
            [KeyboardButton("🚨 Emergency")],
        ],
        resize_keyboard=True,
    )


def wallet_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Deposit", callback_data="wallet:deposit")],
        [InlineKeyboardButton("💵 Balance", callback_data="wallet:balance")],
        [InlineKeyboardButton("📤 Withdraw", callback_data="wallet:withdraw")],
    ])


def setup_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎯 Strategy", callback_data="setup:strategy")],
        [InlineKeyboardButton("⚖️ Risk Profile", callback_data="setup:risk")],
        [InlineKeyboardButton("🏷️ Categories", callback_data="setup:categories")],
        [InlineKeyboardButton("💰 Capital %", callback_data="setup:capital")],
        [InlineKeyboardButton("🎚️ TP / SL", callback_data="setup:tpsl")],
        [InlineKeyboardButton("👥 Copy Targets", callback_data="setup:copy")],
        [InlineKeyboardButton("🔁 Mode (Paper/Live)", callback_data="setup:mode")],
        [InlineKeyboardButton("🏆 Auto-redeem (Instant/Hourly)",
                              callback_data="setup:redeem")],
    ])


def strategy_picker(current: list[str]) -> InlineKeyboardMarkup:
    def mark(s):
        return f"{'✅' if s in current else '◻️'} {s.title().replace('_', ' ')}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(mark("copy_trade"),
                              callback_data="set_strategy:copy_trade")],
        [InlineKeyboardButton(mark("signal"), callback_data="set_strategy:signal")],
        [InlineKeyboardButton(mark("value") + " (R6b+)",
                              callback_data="set_strategy:value")],
        [InlineKeyboardButton("⬅️ Back", callback_data="setup:menu")],
    ])


def risk_picker(current: str) -> InlineKeyboardMarkup:
    def mark(r):
        return f"{'✅' if r == current else '◻️'} {r.title()}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(mark("conservative"),
                              callback_data="set_risk:conservative")],
        [InlineKeyboardButton(mark("balanced"), callback_data="set_risk:balanced")],
        [InlineKeyboardButton(mark("aggressive"),
                              callback_data="set_risk:aggressive")],
        [InlineKeyboardButton("⬅️ Back", callback_data="setup:menu")],
    ])


def category_picker(current: list[str] | None) -> InlineKeyboardMarkup:
    cur = set(current or [])
    def mark(c):
        return f"{'✅' if c in cur or not cur and c == 'all' else '◻️'} {c.title()}"
    cats = ["all", "politics", "sports", "crypto", "tech", "culture"]
    rows = [[InlineKeyboardButton(mark(c), callback_data=f"set_cat:{c}")]
            for c in cats]
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="setup:menu")])
    return InlineKeyboardMarkup(rows)


def mode_picker(current: str) -> InlineKeyboardMarkup:
    def mark(m):
        return f"{'✅' if m == current else '◻️'} {m.title()}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(mark("paper"), callback_data="set_mode:paper")],
        [InlineKeyboardButton(mark("live") + " (Tier 4)",
                              callback_data="set_mode:live")],
        [InlineKeyboardButton("⬅️ Back", callback_data="setup:menu")],
    ])


def autoredeem_picker(current: str) -> InlineKeyboardMarkup:
    def mark(m):
        return f"{'✅' if m == current else '◻️'} {m.title()}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(mark("instant"),
                              callback_data="set_redeem:instant")],
        [InlineKeyboardButton(mark("hourly"), callback_data="set_redeem:hourly")],
    ])


def autotrade_toggle(on: bool) -> InlineKeyboardMarkup:
    label = "🛑 Turn OFF auto-trade" if on else "✅ Turn ON auto-trade"
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(label, callback_data="autotrade:toggle"),
    ]])


def emergency_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏸ Pause new trades",
                              callback_data="emergency:pause")],
        [InlineKeyboardButton("▶️ Resume", callback_data="emergency:resume")],
        [InlineKeyboardButton("🛑 Pause + Close All",
                              callback_data="emergency:pause_close")],
    ])


def admin_menu(kill_active: bool) -> InlineKeyboardMarkup:
    label = "🟢 Disable kill switch" if kill_active else "🔴 Activate kill switch"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(label, callback_data="admin:kill")],
        [InlineKeyboardButton("📊 System status", callback_data="admin:status")],
        [InlineKeyboardButton("🔁 Force redeem pending",
                              callback_data="admin:force_redeem")],
    ])


def dashboard_nav(has_trades: bool) -> InlineKeyboardMarkup:
    if not has_trades:
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("🤖 Get Started", callback_data="dashboard:autotrade"),
        ]])
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🤖 Auto-Trade", callback_data="dashboard:autotrade"),
        InlineKeyboardButton("📈 Trades",     callback_data="dashboard:trades"),
        InlineKeyboardButton("💰 Wallet",     callback_data="dashboard:wallet"),
    ]])


def confirm(action_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes", callback_data=f"confirm:{action_key}:yes"),
        InlineKeyboardButton("❌ No", callback_data=f"confirm:{action_key}:no"),
    ]])
