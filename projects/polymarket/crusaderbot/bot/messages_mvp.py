"""MVP v1 Telegram message renderers (V5 premium terminal — HTML format).

Every screen defined in docs/ux/telegram-mvp-v1.md has one render_* function
here. Renderers are pure: they take primitives, return strings. No I/O, no
DB calls. Handlers fetch data, call these renderers, and send the result.

WARP-71: all output is Telegram HTML (parse_mode="HTML"). Numerical groups
render through ``pre_block`` (monospaced ``<pre>`` columns); grouped key/value
rows use the ``├── / └──`` tree via ``leaf`` / ``section``; ``DIV`` (━ × 32)
separates major sections.
"""
from __future__ import annotations

from typing import Sequence

from .ui.tree import (
    CARD_DIVIDER,
    DIV,
    LIVE,
    LOCKED,
    PAPER,
    STATUS_NOT_SET,
    STATUS_PAUSED,
    STATUS_RUNNING,
    STATUS_STOPPED,
    STATUS_SYNCING,
    cta,
    html_escape,
    join_blocks,
    leaf,
    nested,
    pnl,
    pre_block,
    section,
    title,
)

# ─────────────────────────────────────────────────────────────────────────────
# 8. Dashboard
# ─────────────────────────────────────────────────────────────────────────────


def render_dashboard_default(
    *,
    bot_status: str = STATUS_RUNNING,
    today_pnl: float = 0.0,
    today_trades: int = 0,
    active_strategy: str = "⚡ Full Auto",
    copy_wallets_active: int = 0,
    portfolio_value: float = 0.0,
) -> str:
    return (
        f"🏠 <b>Dashboard</b>\n"
        f"{DIV}\n\n"
        f"Bot Status: <code>{html_escape(bot_status)}</code>\n\n"
        f"<b>💹 Today</b>\n"
        + pre_block([
            ("PnL", pnl(today_pnl)),
            ("Trades", str(today_trades)),
        ]) +
        f"\n{DIV}\n"
        f"<b>📊 Overview</b>\n"
        f"  · Auto Trade: <code>{html_escape(active_strategy)}</code>\n"
        f"  · Copy Wallet: <code>{copy_wallets_active} Active</code>\n"
        f"  · Portfolio: <code>${portfolio_value:,.2f}</code>"
    )


def render_dashboard_new_user() -> str:
    return (
        f"🏠 <b>Dashboard</b>\n"
        f"{DIV}\n\n"
        f"Bot Status: <code>{STATUS_NOT_SET}</code>\n\n"
        f"<b>📊 Overview</b>\n"
        f"  · Auto Trade: <code>{STATUS_NOT_SET}</code>\n"
        f"  · Copy Wallet: <code>{STATUS_NOT_SET}</code>\n\n"
        f"{cta('Tap Setup Auto to get started')}"
    )


def render_dashboard_paused(*, reason: str = "Manual Pause", today_pnl: float = 0.0) -> str:
    return (
        f"🏠 <b>Dashboard</b>\n"
        f"{DIV}\n\n"
        f"Bot Status: <code>{STATUS_PAUSED}</code>\n"
        f"Reason: <code>{html_escape(reason)}</code>\n\n"
        f"Today PnL: <code>{pnl(today_pnl)}</code>\n\n"
        f"{cta('Resume trading to continue')}"
    )


def render_dashboard_risk_alert(*, message: str = "Daily drawdown nearing limit") -> str:
    return (
        f"🏠 <b>Dashboard</b>\n"
        f"{DIV}\n\n"
        f"⚠️ Risk Alert: <code>{html_escape(message)}</code>\n"
        f"Bot Protection: <code>Auto pause may trigger</code>\n\n"
        f"{cta('Adjust risk settings')}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 9. Auto Trade
# ─────────────────────────────────────────────────────────────────────────────


def render_autotrade_home(
    *,
    status: str = STATUS_NOT_SET,
    strategy: str = "⚡ Momentum",
    capital: float = 100.0,
    risk: str = "🟡 Balanced",
    mode: str = PAPER,
    pnl_today: float = 0.0,
    executions: int = 0,
    win_rate: int = 0,
) -> str:
    return (
        f"🤖 <b>Auto Trade</b>\n"
        f"{DIV}\n\n"
        f"Status: <code>{html_escape(status)}</code>\n"
        f"Strategy: <code>{html_escape(strategy)}</code>\n\n"
        f"<b>⚙️ Configuration</b>\n"
        + pre_block([
            ("Capital", f"${capital:,.2f}"),
            ("Risk",    risk),
            ("Mode",    mode),
        ]) +
        f"\n\n<b>📊 Performance</b>\n"
        + pre_block([
            ("PnL Today",   pnl(pnl_today)),
            ("Executions",  str(executions)),
            ("Win Rate",    f"{win_rate}%"),
        ]) +
        f"\n{DIV}\n"
        f"{cta('Choose an action:')}",
    )[0] if False else (
        f"🤖 <b>Auto Trade</b>\n"
        f"{DIV}\n\n"
        f"Status: <code>{html_escape(status)}</code>\n"
        f"Strategy: <code>{html_escape(strategy)}</code>\n\n"
        f"<b>⚙️ Configuration</b>\n"
        f"{pre_block([('Capital', f'${capital:,.2f}'), ('Risk', risk), ('Mode', mode)])}\n\n"
        f"<b>📊 Performance</b>\n"
        f"{pre_block([('PnL Today', pnl(pnl_today)), ('Executions', str(executions)), ('Win Rate', f'{win_rate}%')])}\n"
        f"{DIV}\n"
        f"{cta('Choose an action:')}"
    )


def render_autotrade_quick_start(
    *,
    strategy: str = "⚡ Momentum",
    risk: str = "🟡 Balanced",
    capital: float = 100.0,
    mode: str = PAPER,
) -> str:
    return (
        f"🚀 <b>Quick Start</b>\n"
        f"{DIV}\n\n"
        f"<b>Recommended Setup</b>\n"
        f"  · Strategy: <code>{html_escape(strategy)}</code>\n"
        f"  · Risk: <code>{html_escape(risk)}</code>\n"
        f"  · Capital: <code>${capital:,.0f}</code>\n"
        f"  · Mode: <code>{html_escape(mode)}</code>\n\n"
        f"{cta('Ready to begin?')}"
    )


def render_autotrade_configure_strategy() -> str:
    return (
        f"🤖 <b>Auto Trade</b> · Configure · Strategy\n"
        f"{DIV}\n\n"
        f"<b>Choose a Strategy</b>\n"
        f"  · ⚡ <b>Momentum</b> — Fast trend following\n"
        f"  · 📊 <b>Mean Reversion</b> — Buy pullbacks\n"
        f"  · 🧪 <b>Smart Hybrid</b> — Mixed adaptive mode\n\n"
        f"{cta('Select a strategy:')}"
    )


def render_autotrade_configure_capital(current: float = 100.0) -> str:
    return (
        f"🤖 <b>Auto Trade</b> · Configure · Capital\n"
        f"{DIV}\n\n"
        f"Current Allocation: <code>${current:,.0f}</code>\n\n"
        f"{cta('Choose allocation:')}"
    )


def render_autotrade_configure_risk() -> str:
    return (
        f"🤖 <b>Auto Trade</b> · Configure · Risk\n"
        f"{DIV}\n\n"
        f"<b>Choose a Risk Level</b>\n"
        f"  · 🟢 <b>Safe</b> — Lower risk · fewer trades\n"
        f"  · 🟡 <b>Balanced</b> — Recommended\n"
        f"  · 🔴 <b>Aggressive</b> — Higher volatility\n\n"
        f"{cta('Select a risk level:')}"
    )


def render_autotrade_configure_review(
    *,
    strategy: str,
    capital: float,
    risk: str,
    mode: str = PAPER,
) -> str:
    return (
        f"🤖 <b>Auto Trade</b> · Configure · Review\n"
        f"{DIV}\n\n"
        f"<b>Your Setup</b>\n"
        f"  · Strategy: <code>{html_escape(strategy)}</code>\n"
        f"  · Capital: <code>${capital:,.0f}</code>\n"
        f"  · Risk: <code>{html_escape(risk)}</code>\n"
        f"  · Mode: <code>{html_escape(mode)}</code>\n\n"
        f"{cta('Looks good?')}"
    )


def render_autotrade_strategy_status(
    *,
    strategy: str,
    status: str,
    capital: float,
    pnl_today: float,
    trades: int,
) -> str:
    return (
        f"📊 <b>Strategy Status</b>\n"
        f"{DIV}\n\n"
        f"  · Name: <code>{html_escape(strategy)}</code>\n"
        f"  · Status: <code>{html_escape(status)}</code>\n"
        f"  · Capital: <code>${capital:,.0f}</code>\n"
        f"  · PnL Today: <code>{pnl(pnl_today)}</code>\n"
        f"  · Trades: <code>{trades}</code>\n\n"
        f"{cta('Select an action:')}"
    )


def render_autotrade_pause_confirm() -> str:
    return (
        f"⏸ <b>Pause Auto Trade</b>\n"
        f"{DIV}\n\n"
        f"  · New trades: <code>Stopped</code>\n"
        f"  · Open positions: <code>Remain active</code>\n\n"
        f"{cta('Confirm pause?')}"
    )


def render_autotrade_resume_confirm() -> str:
    return (
        f"▶ <b>Resume Auto Trade</b>\n"
        f"{DIV}\n\n"
        f"  · Market monitoring: <code>Resumed</code>\n"
        f"  · Trade execution: <code>Enabled</code>\n\n"
        f"{cta('Continue trading?')}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 10. Copy Wallet
# ─────────────────────────────────────────────────────────────────────────────


def render_copy_home(
    *,
    status: str = STATUS_NOT_SET,
    active_wallets: int = 0,
    allocation: float = 0.0,
) -> str:
    return (
        f"👥 <b>Copy Wallet</b>\n"
        f"{DIV}\n\n"
        f"  · Status: <code>{html_escape(status)}</code>\n"
        f"  · Active Wallets: <code>{active_wallets} Following</code>\n"
        f"  · Allocation: <code>${allocation:,.0f}</code>\n\n"
        f"{cta('Choose an action:')}"
    )


def render_copy_add_wallet_prompt() -> str:
    return (
        f"➕ <b>Add Wallet</b>\n"
        f"{DIV}\n\n"
        f"{cta('Paste the wallet address to copy:')}"
    )


def render_copy_wallet_review(
    *,
    address_short: str,
    activity: str = STATUS_RUNNING,
    recent_trades: int = 0,
    risk: str = "🟡 Moderate",
) -> str:
    return (
        f"👥 <b>Wallet Review</b>\n"
        f"{DIV}\n\n"
        f"<b>Wallet Info</b>\n"
        f"  · Address: <code>{html_escape(address_short)}</code>\n"
        f"  · Activity: <code>{html_escape(activity)}</code>\n"
        f"  · Recent Trades: <code>{recent_trades}</code>\n"
        f"  · Risk: <code>{html_escape(risk)}</code>\n\n"
        f"{cta('Add this wallet?')}"
    )


def render_copy_wallet_configure(
    *,
    address_short: str,
    allocation: float,
    risk: str,
    copy_mode: str = "Mirror Trades",
) -> str:
    return (
        f"⚙️ <b>Wallet Configuration</b>\n"
        f"{DIV}\n\n"
        f"  · Wallet: <code>{html_escape(address_short)}</code>\n"
        f"  · Allocation: <code>${allocation:,.0f}</code>\n"
        f"  · Risk: <code>{html_escape(risk)}</code>\n"
        f"  · Copy Mode: <code>{html_escape(copy_mode)}</code>\n\n"
        f"{cta('Confirm settings?')}"
    )


def render_copy_active_wallets_empty() -> str:
    return (
        f"👛 <b>Active Wallets</b>\n"
        f"{DIV}\n\n"
        f"  · Status: <code>No wallets added</code>\n"
        f"  · Next Step: <code>Add a wallet address to start copying</code>"
    )


def render_copy_wallet_card(
    *,
    index: int,
    address_short: str,
    status: str,
    allocation: float,
    pnl_today: float,
    trades_copied: int,
) -> str:
    return (
        f"👛 <b>Active Wallets</b>\n"
        f"{DIV}\n\n"
        f"<b>Wallet #{html_escape(str(index))}</b>\n"
        + pre_block([
            ("Address",    address_short),
            ("Status",     status),
            ("Allocation", f"${allocation:,.2f}"),
            ("PnL Today",  pnl(pnl_today)),
            ("Trades",     str(trades_copied)),
        ]) +
        f"\n{DIV}\n"
        f"{cta('Select an action:')}"
    )


def render_copy_pause_confirm() -> str:
    return (
        f"⏸ <b>Pause Copy Wallet</b>\n"
        f"{DIV}\n\n"
        f"  · New copied trades: <code>Stopped</code>\n"
        f"  · Existing positions: <code>Stay active</code>\n\n"
        f"{cta('Confirm pause?')}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 11. Markets
# ─────────────────────────────────────────────────────────────────────────────


def render_markets_home() -> str:
    return (
        f"📈 <b>Markets</b>\n"
        f"{DIV}\n\n"
        f"<b>Browse</b>\n"
        f"  · 🔥 Trending — Most active markets\n"
        f"  · 🆕 New Markets — Fresh opportunities\n"
        f"  · 🧠 AI Insights — High-confidence setups\n"
        f"  · ⭐ Watchlist — Saved markets\n"
        f"  · 🔎 Search — Find any market\n\n"
        f"{cta('Choose a view:')}"
    )


def render_markets_trending(items) -> str:
    lines = [f"🔥 <b>Trending Markets</b>\n{DIV}\n"]
    for it in (items or []):
        rank = html_escape(str(it.get("rank", "")))
        t = html_escape(str(it.get("title", "")).replace("\n", " ").strip()[:60])
        yes = html_escape(str(it.get("yes", "—")))
        no = html_escape(str(it.get("no", "—")))
        vol = html_escape(str(it.get("volume", "—")))
        lines.append(
            f"<b>{rank}. {t}</b>\n"
            f"  · YES <code>{yes}</code> · NO <code>{no}</code> · Vol <code>{vol}</code>"
        )
    if not items:
        lines.append("<i>No trending markets right now</i>")
    return "\n\n".join(lines)


def render_market_card(
    *,
    title: str,
    yes: str,
    no: str,
    volume: str,
    closes: str,
    sentiment: str = "🟡 Neutral",
) -> str:
    return (
        f"🎯 <b>{html_escape(title)}</b>\n"
        f"{DIV}\n"
        + pre_block([
            ("YES",      yes),
            ("NO",       no),
            ("Volume",   volume),
            ("Closes",   closes),
            ("Sentiment",sentiment),
        ]) +
        f"\n{DIV}\n"
        f"{cta('Choose an action:')}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 12. Portfolio / Positions / History
# ─────────────────────────────────────────────────────────────────────────────


def render_portfolio_home(
    *,
    balance: float = 0.0,
    equity: float = 0.0,
    open_positions: int = 0,
    today_pnl: float = 0.0,
    week_pnl: float = 0.0,
) -> str:
    return (
        f"💼 <b>Portfolio</b>\n"
        f"{DIV}\n"
        + pre_block([
            ("Balance",    f"${balance:,.2f}"),
            ("Equity",     f"${equity:,.2f}"),
            ("Positions",  str(open_positions)),
        ]) +
        f"\n\n<b>💰 Performance</b>\n"
        + pre_block([
            ("Today",  pnl(today_pnl)),
            ("7 Days", pnl(week_pnl)),
        ]) +
        f"\n{DIV}\n"
        f"{cta('Select a view:')}"
    )


def render_positions_list(
    items,
    *,
    page: int = 1,
    total_pages: int = 1,
    total: int = 0,
) -> str:
    header = f"📋 <b>Open Positions</b>  ·  {total} active\n{DIV}"
    cards = []
    for it in (items or []):
        rank = str(it.get("rank", "")).strip()
        market_title = str(it.get("title", "")).replace("\n", " ").strip()
        label = f"{rank}. {market_title}".strip(". ")
        block = pre_block([
            ("Side", str(it.get("side", "—"))),
            ("PnL",  pnl(float(it.get("pnl", 0.0)))),
        ])
        cards.append(f"<b>{html_escape(label)}</b>\n{block}")
    if not cards:
        cards = ["<i>No open positions</i>"]
    footer = f"{DIV}\n<i>Page {page} of {total_pages}</i>"
    return header + "\n\n" + "\n\n".join(cards) + "\n" + footer


def render_position_detail(
    *,
    market_title: str,
    side: str,
    entry: str,
    current: str,
    pnl_value: float,
    status: str = "Open",
) -> str:
    return (
        f"📌 <b>Position Details</b>\n"
        f"{DIV}\n\n"
        f"<b>{html_escape(market_title)}</b>\n"
        + pre_block([
            ("Side",    side),
            ("Entry",   f"{entry}¢"),
            ("Current", f"{current}¢"),
            ("PnL",     pnl(pnl_value)),
            ("Status",  status),
        ]) +
        f"\n{DIV}\n"
        f"{cta('Choose an action:')}"
    )


def render_history_empty() -> str:
    return (
        f"📜 <b>Trade History</b>\n"
        f"{DIV}\n\n"
        f"Status: <code>No trades yet</code>\n\n"
        f"{cta('Start automation to build history')}"
    )


def render_history_home(*, today: int = 0, week: int = 0) -> str:
    return (
        f"📜 <b>Trade History</b>\n"
        f"{DIV}\n\n"
        f"  · Today: <code>{today} Trades</code>\n"
        f"  · This Week: <code>{week} Trades</code>\n\n"
        f"{cta('Choose range:')}"
    )


def render_performance(
    *,
    today_pnl: float = 0.0,
    week_pnl: float = 0.0,
    win_rate: int = 0,
    trades: int = 0,
) -> str:
    return (
        f"💹 <b>Performance</b>\n"
        f"{DIV}\n"
        + pre_block([
            ("Today",    pnl(today_pnl)),
            ("7 Days",   pnl(week_pnl)),
            ("Win Rate", f"{win_rate}%"),
            ("Trades",   str(trades)),
        ])
    )


def render_balance(
    *,
    available: float = 0.0,
    allocated: float = 0.0,
) -> str:
    free = max(available - allocated, 0.0)
    return (
        f"💰 <b>Balance</b>\n"
        f"{DIV}\n"
        + pre_block([
            ("Available",    f"${available:,.2f}"),
            ("Allocated",    f"${allocated:,.2f}"),
            ("Free Capital", f"${free:,.2f}"),
        ])
    )


# ─────────────────────────────────────────────────────────────────────────────
# 13. Settings
# ─────────────────────────────────────────────────────────────────────────────


def render_settings_home(*, trading_mode: str = PAPER) -> str:
    return (
        f"⚙️ <b>Settings</b>\n"
        f"{DIV}\n\n"
        f"  · 🔄 Trading Mode: <code>{html_escape(trading_mode)}</code>\n"
        f"  · 🛡 Risk: <code>Balanced</code>\n"
        f"  · 🔔 Alerts: <code>ON</code>\n"
        f"  · 👥 Copy Wallet: <code>OFF</code>\n"
        f"  · 👤 Account: <code>Profile</code>\n"
        f"  · 🧪 Advanced: <code>Power user</code>"
    )


def render_settings_trading_mode(*, current: str = PAPER) -> str:
    return (
        f"🔄 <b>Trading Mode</b>\n"
        f"{DIV}\n\n"
        f"Current Mode: <code>{html_escape(current)}</code>\n\n"
        f"<b>Options</b>\n"
        f"  · 📝 Paper Mode — Safe simulation\n"
        f"  · 💸 Live Mode — Real capital execution"
    )


def render_settings_live_gate() -> str:
    return (
        f"⚠️ <b>Live Trading</b>\n"
        f"{DIV}\n\n"
        f"Status: <code>{LOCKED} Disabled</code>\n\n"
        f"<b>Activation Requirements</b>\n"
        f"  · Manual owner confirmation\n"
        f"  · Risk controls verified\n"
        f"  · Paper mode tested first\n\n"
        f"{cta('Use Paper Mode until ready')}"
    )


def render_settings_risk_controls(
    *,
    daily_loss_limit: float = 20.0,
    max_position_pct: int = 10,
    max_concurrent: int = 3,
    auto_pause_enabled: bool = True,
) -> str:
    auto_pause = "🟢 Enabled" if auto_pause_enabled else "🔴 Disabled"
    return (
        f"🛡 <b>Risk Controls</b>\n"
        f"{DIV}\n"
        + pre_block([
            ("Daily Loss Limit",  f"${daily_loss_limit:,.0f}"),
            ("Max Position Size", f"{max_position_pct}%"),
            ("Concurrent Trades", f"{max_concurrent} Max"),
            ("Auto Pause",        auto_pause),
        ])
    )


def render_settings_notifications(
    *,
    trade_opened: bool = True,
    trade_closed: bool = True,
    risk_alerts: bool = True,
    daily_summary: bool = True,
    market_alerts: bool = False,
) -> str:
    on, off = "🟢 ON", "🔴 OFF"
    return (
        f"🔔 <b>Notifications</b>\n"
        f"{DIV}\n\n"
        f"  · Trade Opened: <code>{on if trade_opened else off}</code>\n"
        f"  · Trade Closed: <code>{on if trade_closed else off}</code>\n"
        f"  · Risk Alerts: <code>{on if risk_alerts else off}</code>\n"
        f"  · Daily Summary: <code>{on if daily_summary else off}</code>\n"
        f"  · Market Alerts: <code>{on if market_alerts else off}</code>"
    )


def render_settings_account(
    *,
    wallet_status: str = "Connected",
    mode: str = PAPER,
    api_status: str = "🟢 Healthy",
    subscription: str = "MVP",
) -> str:
    return (
        f"👤 <b>Account</b>\n"
        f"{DIV}\n\n"
        f"  · Wallet: <code>{html_escape(wallet_status)}</code>\n"
        f"  · Mode: <code>{html_escape(mode)}</code>\n"
        f"  · API Status: <code>{html_escape(api_status)}</code>\n"
        f"  · Subscription: <code>{html_escape(subscription)}</code>"
    )


def render_settings_advanced(*, debug_enabled: bool = False) -> str:
    debug = "🟢 Enabled" if debug_enabled else "🔴 Disabled"
    return (
        f"🧪 <b>Advanced</b>\n"
        f"{DIV}\n\n"
        f"  · Strategy Logs: <code>View execution logs</code>\n"
        f"  · Debug Mode: <code>{debug}</code>\n"
        f"  · Data Refresh: <code>Real-time</code>\n"
        f"  · System Health: <code>🟢 Operational</code>"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 14. Help
# ─────────────────────────────────────────────────────────────────────────────


def render_help_home() -> str:
    return (
        f"❓ <b>Help</b>\n"
        f"{DIV}\n\n"
        f"<b>Topics</b>\n"
        f"  · 🚀 Quick Start Guide\n"
        f"  · 🤖 How Auto Trade Works\n"
        f"  · 👥 How Copy Wallet Works\n"
        f"  · 🛡 Risk &amp; Safety\n"
        f"  · 💬 FAQ\n"
        f"  · 🆘 Support\n\n"
        f"{cta('Choose a topic:')}"
    )


def render_help_quick_start_guide() -> str:
    return (
        f"🚀 <b>Quick Start Guide</b>\n"
        f"{DIV}\n\n"
        f"<b>Steps</b>\n"
        f"  · Configure Auto Trade\n"
        f"  · Choose risk &amp; capital\n"
        f"  · Start in Paper Mode\n"
        f"  · Monitor performance\n\n"
        f"Recommendation: <code>Use Paper Mode first</code>"
    )


def render_help_how_auto_trade() -> str:
    return (
        f"🤖 <b>How Auto Trade Works</b>\n"
        f"{DIV}\n\n"
        f"  · Purpose: <code>Bot trades automatically</code>\n"
        f"  · Decision Engine: <code>Strategy-based execution</code>\n"
        f"  · You Control: <code>Capital · Risk · Strategy</code>\n"
        f"  · Bot Controls: <code>Market execution</code>\n"
        f"  · Safety: <code>Risk protections enabled</code>"
    )


def render_help_how_copy_wallet() -> str:
    return (
        f"👥 <b>How Copy Wallet Works</b>\n"
        f"{DIV}\n\n"
        f"  · Purpose: <code>Mirror target wallet activity</code>\n"
        f"  · What Happens: <code>Trades may be copied automatically</code>\n"
        f"  · You Control: <code>Allocation · Risk · Wallet</code>\n"
        f"  · Important: <code>Past performance ≠ future results</code>\n"
        f"  · Recommendation: <code>Start small</code>"
    )


def render_help_safety() -> str:
    return (
        f"🛡 <b>Risk &amp; Safety</b>\n"
        f"{DIV}\n\n"
        f"<b>Protections</b>\n"
        f"  · Paper Mode — Practice without real funds\n"
        f"  · Daily Loss Limit — Auto stop protection\n"
        f"  · Auto Pause — Risk circuit breaker\n\n"
        f"<b>Warnings</b>\n"
        f"  · Copy Wallet — Past performance ≠ future results\n"
        f"  · Never risk more than you can afford"
    )


def render_help_faq() -> str:
    return (
        f"💬 <b>FAQ</b>\n"
        f"{DIV}\n\n"
        f"  · Is the bot safe? <code>Yes — paper mode by default</code>\n"
        f"  · Can I lose money? <code>Paper mode uses virtual funds only</code>\n"
        f"  · How to stop? <code>Tap Pause or Stop Bot in Auto Mode</code>"
    )


def render_help_support() -> str:
    return (
        f"🆘 <b>Support</b>\n"
        f"{DIV}\n\n"
        f"  · Help Center: <code>Common troubleshooting</code>\n"
        f"  · Report Issue: <code>Found a problem?</code>\n"
        f"  · Status: <code>🟢 Systems Operational</code>"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 15. Notifications
# ─────────────────────────────────────────────────────────────────────────────


def render_notif_bot_started(
    *,
    strategy: str,
    capital: float,
    risk: str,
    status: str = STATUS_RUNNING,
) -> str:
    return (
        f"🤖 <b>Auto Trade Started</b>\n"
        f"{DIV}\n"
        + pre_block([
            ("Strategy", strategy),
            ("Capital",  f"${capital:,.2f}"),
            ("Risk",     risk),
            ("Status",   status),
        ])
    )


def render_notif_bot_waiting() -> str:
    return (
        f"⏳ <b>Waiting for Signal</b>\n"
        f"{DIV}\n\n"
        f"Status: <code>Scanning markets...</code>"
    )


def render_notif_trade_opened(
    *,
    market_title: str,
    side: str,
    size: float,
    price: float,
    mode: str = PAPER,
) -> str:
    return (
        f"⚡ <b>Position Opened</b>\n"
        f"{DIV}\n"
        + pre_block([
            ("Market", market_title[:40]),
            ("Side",   side),
            ("Size",   f"${size:,.2f}"),
            ("Price",  f"{price:.3f}"),
            ("Mode",   mode),
        ]) +
        f"\n{DIV}"
    )


def render_notif_first_trade(
    *,
    market_title: str,
    side: str,
    size: float,
) -> str:
    return (
        f"🎉 <b>First Trade!</b>\n"
        f"{DIV}\n"
        + pre_block([
            ("Market", market_title[:40]),
            ("Side",   side),
            ("Size",   f"${size:,.2f}"),
        ])
    )


def render_notif_trade_closed(
    *,
    market_title: str,
    side: str,
    size: float,
    pnl_value: float,
) -> str:
    return (
        f"✅ <b>Position Closed</b>\n"
        f"{DIV}\n"
        + pre_block([
            ("Market", market_title[:40]),
            ("Side",   side),
            ("Size",   f"${size:,.2f}"),
            ("PnL",    pnl(pnl_value)),
        ])
    )


def render_notif_wallet_copied(
    *,
    address_short: str,
    market_title: str,
    side: str,
    size: float,
) -> str:
    return (
        f"🔁 <b>Wallet Copied</b>\n"
        f"{DIV}\n"
        + pre_block([
            ("Wallet", address_short),
            ("Market", market_title[:40]),
            ("Side",   side),
            ("Size",   f"${size:,.2f}"),
        ])
    )


def render_notif_drawdown_warning(*, drawdown_pct: float) -> str:
    return (
        f"⚠️ <b>Drawdown Warning</b>\n"
        f"{DIV}\n\n"
        f"Drawdown: <code>{drawdown_pct:.1f}%</code>\n"
        f"{cta('Review positions — auto pause may trigger')}"
    )


def render_notif_auto_pause(*, reason: str = "Daily loss limit reached") -> str:
    return (
        f"⏸ <b>Auto Pause Triggered</b>\n"
        f"{DIV}\n\n"
        f"Reason: <code>{html_escape(reason)}</code>\n\n"
        f"{cta('Review settings before resuming')}"
    )


def render_notif_daily_summary(
    *,
    trades: int,
    pnl_today: float,
    win_rate: int,
    mode: str = PAPER,
) -> str:
    return (
        f"📊 <b>Daily Summary</b>\n"
        f"{DIV}\n"
        + pre_block([
            ("Trades",   str(trades)),
            ("PnL",      pnl(pnl_today)),
            ("Win Rate", f"{win_rate}%"),
            ("Mode",     mode),
        ])
    )


# ─────────────────────────────────────────────────────────────────────────────
# 16. System states
# ─────────────────────────────────────────────────────────────────────────────


def render_syncing() -> str:
    return f"🔄 <b>Syncing...</b>\n\n{cta('Please wait')}"


def render_error_api() -> str:
    return (
        f"❌ <b>API Error</b>\n"
        f"{DIV}\n\n"
        f"Status: <code>Connection issue</code>\n\n"
        f"{cta('Try again in a moment')}"
    )


def render_error_invalid_wallet() -> str:
    return (
        f"❌ <b>Invalid Wallet</b>\n"
        f"{DIV}\n\n"
        f"Status: <code>Address not recognized</code>\n\n"
        f"{cta('Check the address and try again')}"
    )


def render_error_bot_paused() -> str:
    return (
        f"⏸ <b>Bot Paused</b>\n"
        f"{DIV}\n\n"
        f"Status: <code>Manually paused</code>\n\n"
        f"{cta('Resume from Auto Mode')}"
    )


def render_error_live_locked() -> str:
    return (
        f"🔒 <b>Live Trading Locked</b>\n"
        f"{DIV}\n\n"
        f"Status: <code>Paper mode only</code>\n\n"
        f"{cta('Contact operator to unlock live trading')}"
    )


def render_deposit_prompt() -> str:
    return (
        f"💰 <b>Deposit Funds</b>\n"
        f"{DIV}\n\n"
        f"  · Mode: <code>{PAPER}</code>\n"
        f"  · Demo Capital: <code>Ready</code>\n\n"
        f"{cta('Fund your account to increase capital')}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 17. Onboarding
# ─────────────────────────────────────────────────────────────────────────────


def render_welcome(*, user_name: str = "trader") -> str:
    return (
        f"🛡️ <b>Welcome, {html_escape(user_name)}!</b>\n"
        f"{DIV}\n\n"
        f"<b>CrusaderBot</b> — Trade prediction markets with controlled risk.\n\n"
        f"  · Mode: <code>{PAPER}</code>\n"
        f"  · Demo Capital: <code>$1,000 ready</code>\n"
        f"  · Live Trading: <code>{LOCKED}</code>\n\n"
        f"{cta('Tap Get Started to begin')}"
    )


def render_wallet_ready(*, address_short: str) -> str:
    return (
        f"✅ <b>Wallet Ready</b>\n"
        f"{DIV}\n\n"
        f"  · Address: <code>{html_escape(address_short)}</code>\n"
        f"  · Status: <code>Connected</code>\n\n"
        f"{cta('Choose a preset to continue')}"
    )
