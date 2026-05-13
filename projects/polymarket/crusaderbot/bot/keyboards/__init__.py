"""All inline + reply keyboards in one place."""
from __future__ import annotations

from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, ReplyKeyboardMarkup,
)


def grid_rows(buttons: list, cols: int = 2) -> list[list]:
    """Pair a flat list of buttons into rows of `cols` (default 2).

    Odd-count lists produce a partial last row — the final button is not
    centred by this helper; Telegram renders it left-aligned.
    """
    return [buttons[i:i + cols] for i in range(0, len(buttons), cols)]


def nav_row(back_data: str = "dashboard:main") -> list[InlineKeyboardButton]:
    """Standard persistent bottom nav row — append to any inline keyboard."""
    return [
        InlineKeyboardButton("⬅️ Back",    callback_data=back_data),
        InlineKeyboardButton("🏠 Home",    callback_data="dashboard:main"),
        InlineKeyboardButton("🔄 Refresh", callback_data="noop:refresh"),
    ]


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🏠 Dashboard"),   KeyboardButton("💼 Portfolio")],
            [KeyboardButton("🤖 Auto Trade"),  KeyboardButton("👥 Copy Wallet")],
            [KeyboardButton("📊 Insights"),    KeyboardButton("⚙️ Settings")],
            [KeyboardButton("🛑 Stop Bot")],
        ],
        resize_keyboard=True,
    )


def dashboard_kb(cta_btn: InlineKeyboardButton) -> InlineKeyboardMarkup:
    """Dashboard inline keyboard — hierarchy tree style, 2-col grid."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🤖 Auto Trade",  callback_data="dashboard:auto"),
            InlineKeyboardButton("👥 Copy Wallet", callback_data="dashboard:signals"),
        ],
        [
            InlineKeyboardButton("💼 Portfolio",   callback_data="dashboard:portfolio"),
            InlineKeyboardButton("📊 Insights",    callback_data="dashboard:insights"),
        ],
        [
            InlineKeyboardButton("⚙️ Settings",    callback_data="dashboard:settings"),
            InlineKeyboardButton("🛑 Stop Bot",    callback_data="dashboard:stop"),
        ],
        [
            InlineKeyboardButton("🔄 Refresh",     callback_data="dashboard:main"),
        ],
        [cta_btn],
    ])


def portfolio_kb() -> InlineKeyboardMarkup:
    """Portfolio screen keyboard with Back/Home nav."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 Open Positions", callback_data="portfolio:positions"),
            InlineKeyboardButton("📈 Chart",           callback_data="portfolio:chart"),
        ],
        [
            InlineKeyboardButton("📊 Insights",        callback_data="portfolio:insights"),
            InlineKeyboardButton("📋 My Trades",       callback_data="portfolio:trades"),
        ],
        nav_row("dashboard:main"),
    ])


def wallet_menu() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton("📥 Deposit",  callback_data="wallet:deposit"),
        InlineKeyboardButton("💵 Balance",  callback_data="wallet:balance"),
        InlineKeyboardButton("📤 Withdraw", callback_data="wallet:withdraw"),
    ]
    return InlineKeyboardMarkup(grid_rows(buttons))


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
        InlineKeyboardButton("⬅️ Back", callback_data="setup:menu"),
    ]
    return InlineKeyboardMarkup(grid_rows(buttons))


def strategy_card_kb() -> InlineKeyboardMarkup:
    """Descriptive strategy card keyboard — shown in the Auto-Trade menu."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Select Signal",        callback_data="strategy:signal")],
        [InlineKeyboardButton("Select Edge Finder",   callback_data="strategy:edge_finder")],
        [InlineKeyboardButton("Select Momentum",      callback_data="strategy:momentum_reversal")],
        [InlineKeyboardButton("⚡ Select All",         callback_data="strategy:all")],
        [InlineKeyboardButton("↩️ Back to Main Menu", callback_data="strategy:back")],
    ])


def risk_picker(current: str) -> InlineKeyboardMarkup:
    def mark(r: str) -> str:
        return f"{'✅' if r == current else '◻️'} {r.title()}"
    buttons = [
        InlineKeyboardButton(mark("conservative"),
                             callback_data="set_risk:conservative"),
        InlineKeyboardButton(mark("balanced"),  callback_data="set_risk:balanced"),
        InlineKeyboardButton(mark("aggressive"), callback_data="set_risk:aggressive"),
        InlineKeyboardButton("⬅️ Back", callback_data="setup:menu"),
    ]
    return InlineKeyboardMarkup(grid_rows(buttons))


def category_picker(current: list[str] | None) -> InlineKeyboardMarkup:
    cur = set(current or [])
    def mark(c: str) -> str:
        return f"{'✅' if c in cur or not cur and c == 'all' else '◻️'} {c.title()}"
    cats = ["all", "politics", "sports", "crypto", "tech", "culture"]
    buttons = [InlineKeyboardButton(mark(c), callback_data=f"set_cat:{c}")
               for c in cats]
    buttons.append(InlineKeyboardButton("⬅️ Back", callback_data="setup:menu"))
    return InlineKeyboardMarkup(grid_rows(buttons))


def mode_picker(current: str) -> InlineKeyboardMarkup:
    def mark(m: str) -> str:
        return f"{'✅' if m == current else '◻️'} {m.title()}"
    buttons = [
        InlineKeyboardButton(mark("paper"),  callback_data="set_mode:paper"),
        InlineKeyboardButton(mark("live") + " (Tier 4)",
                             callback_data="set_mode:live"),
        InlineKeyboardButton("⬅️ Back", callback_data="setup:menu"),
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


def autotrade_toggle(on: bool) -> InlineKeyboardMarkup:
    label = "🛑 Turn OFF auto-trade" if on else "✅ Turn ON auto-trade"
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(label, callback_data="autotrade:toggle"),
    ]])


def emergency_menu() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton("⏸ Pause Auto-Trade",  callback_data="emergency:pause"),
        InlineKeyboardButton("🛑 Pause + Close All", callback_data="emergency:pause_close"),
        InlineKeyboardButton("🔒 Lock Account",      callback_data="emergency:lock"),
        InlineKeyboardButton("⬅️ Back",              callback_data="emergency:back"),
    ]
    return InlineKeyboardMarkup(grid_rows(buttons))


def emergency_confirm(action: str) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton("✅ Confirm", callback_data=f"emergency:confirm:{action}"),
        InlineKeyboardButton("❌ Cancel",  callback_data="emergency:cancel"),
    ]
    return InlineKeyboardMarkup(grid_rows(buttons))


def emergency_feedback() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton("📊 Dashboard",  callback_data="dashboard:main"),
        InlineKeyboardButton("🤖 Auto-Trade", callback_data="dashboard:autotrade"),
    ]
    return InlineKeyboardMarkup(grid_rows(buttons))


def admin_menu(kill_active: bool) -> InlineKeyboardMarkup:
    label = "🟢 Disable kill switch" if kill_active else "🔴 Activate kill switch"
    buttons = [
        InlineKeyboardButton(label,             callback_data="admin:kill"),
        InlineKeyboardButton("📊 System status", callback_data="admin:status"),
        InlineKeyboardButton("🔁 Force redeem pending",
                             callback_data="admin:force_redeem"),
    ]
    return InlineKeyboardMarkup(grid_rows(buttons))


def dashboard_nav(has_trades: bool) -> InlineKeyboardMarkup:
    if not has_trades:
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("🤖 Get Started", callback_data="dashboard:autotrade"),
        ]])
    buttons = [
        InlineKeyboardButton("🤖 Auto-Trade",  callback_data="dashboard:autotrade"),
        InlineKeyboardButton("📈 Trades",      callback_data="dashboard:trades"),
        InlineKeyboardButton("💰 Wallet",      callback_data="dashboard:wallet"),
        InlineKeyboardButton("📊 Insights",    callback_data="dashboard:insights"),
    ]
    return InlineKeyboardMarkup(grid_rows(buttons))


def insights_kb() -> InlineKeyboardMarkup:
    """Keyboard attached to the PNL Insights message."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 Refresh",       callback_data="insights:refresh"),
        InlineKeyboardButton("📋 Full Report",   callback_data="insights:full_report"),
    ]])


def chart_kb(current_days: int | str) -> InlineKeyboardMarkup:
    """Inline keyboard for the portfolio chart — period selector."""
    def mark(key: str, label: str) -> InlineKeyboardButton:
        tick = "✅ " if str(current_days) == key else ""
        return InlineKeyboardButton(f"{tick}{label}", callback_data=f"chart:{key}")

    return InlineKeyboardMarkup([[
        mark("7",   "7 Days"),
        mark("30",  "30 Days"),
        mark("all", "All Time"),
    ]])


def confirm(action_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes", callback_data=f"confirm:{action_key}:yes"),
        InlineKeyboardButton("❌ No",  callback_data=f"confirm:{action_key}:no"),
    ]])
