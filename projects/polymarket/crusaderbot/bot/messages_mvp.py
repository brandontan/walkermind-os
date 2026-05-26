"""MVP v2 Telegram message renderers — MarkdownV2 format (WARP/telegram-ux-v2).

Every screen has one render_* function: pure, no I/O, no DB calls.
Handlers fetch data, call these renderers, send the result with
parse_mode="MarkdownV2".

Layout rules:
- *Bold* headers, `inline code` for values, ```block``` for aligned numbers
- _Italic_ for CTA prompts
- ─ × 28 as section divider
- md_v2_escape() applied to ALL dynamic strings in raw text regions
- Values inside `code` or ```block``` do NOT need escaping
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
    join_blocks,
    leaf,
    md_v2_escape,
    nested,
    pnl,
    pre_block,
    section,
    title,
)

# Keep html_escape as alias so any stray import still resolves
html_escape = md_v2_escape

# ─────────────────────────────────────────────────────────────────────────────
# 8. Dashboard
# ─────────────────────────────────────────────────────────────────────────────


def render_dashboard_default(
    *,
    bot_status: str = STATUS_RUNNING,
    today_pnl: float = 0.0,
    today_trades: int = 0,
    active_strategy: str = "Close Sweep",
    copy_wallets_active: int = 0,
    portfolio_value: float = 0.0,
) -> str:
    return (
        f"🏠 *Dashboard*\n"
        f"{DIV}\n\n"
        f"Status: `{bot_status}`\n\n"
        f"*💹 Today*\n"
        f"{pre_block([('PnL', pnl(today_pnl)), ('Trades', str(today_trades))])}\n\n"
        f"*📊 Overview*\n"
        f"  · Strategy: `{md_v2_escape(active_strategy)}`\n"
        f"  · Copy Wallet: `{copy_wallets_active} active`\n"
        f"  · Portfolio: `${portfolio_value:,.2f}`"
    )


def render_dashboard_new_user() -> str:
    return (
        f"🏠 *Dashboard*\n"
        f"{DIV}\n\n"
        f"Status: `{STATUS_NOT_SET}`\n\n"
        f"*📊 Overview*\n"
        f"  · Auto Trade: `{STATUS_NOT_SET}`\n"
        f"  · Copy Wallet: `{STATUS_NOT_SET}`\n\n"
        f"{cta('Tap Setup Auto to get started')}"
    )


def render_dashboard_paused(*, reason: str = "Manual Pause", today_pnl: float = 0.0) -> str:
    return (
        f"🏠 *Dashboard*\n"
        f"{DIV}\n\n"
        f"Status: `{STATUS_PAUSED}`\n"
        f"Reason: `{md_v2_escape(reason)}`\n\n"
        f"Today PnL: `{pnl(today_pnl)}`\n\n"
        f"{cta('Resume trading to continue')}"
    )


def render_dashboard_risk_alert(*, message: str = "Daily drawdown nearing limit") -> str:
    return (
        f"🏠 *Dashboard*\n"
        f"{DIV}\n\n"
        f"⚠️ Risk Alert: `{md_v2_escape(message)}`\n"
        f"Protection: `Auto pause may trigger`\n\n"
        f"{cta('Adjust risk settings')}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 9. Auto Trade
# ─────────────────────────────────────────────────────────────────────────────


def render_autotrade_home(
    *,
    status: str = STATUS_NOT_SET,
    strategy: str = "Close Sweep",
    capital: float = 100.0,
    risk: str = "🟡 Balanced",
    mode: str = PAPER,
    pnl_today: float = 0.0,
    executions: int = 0,
    win_rate: int = 0,
) -> str:
    return (
        f"🤖 *Auto Trade*\n"
        f"{DIV}\n\n"
        f"Status: `{md_v2_escape(status)}`\n"
        f"Strategy: `{md_v2_escape(strategy)}`\n\n"
        f"*⚙️ Configuration*\n"
        f"{pre_block([('Capital', f'${capital:,.2f}'), ('Risk', risk), ('Mode', mode)])}\n\n"
        f"*📊 Performance*\n"
        f"{pre_block([('PnL Today', pnl(pnl_today)), ('Executions', str(executions)), ('Win Rate', f'{win_rate}%')])}\n"
        f"{DIV}\n"
        f"{cta('Choose an action:')}"
    )


def render_autotrade_quick_start(
    *,
    strategy: str = "Close Sweep",
    risk: str = "🟡 Balanced",
    capital: float = 100.0,
    mode: str = PAPER,
) -> str:
    return (
        f"🚀 *Quick Start*\n"
        f"{DIV}\n\n"
        f"*Recommended Setup*\n"
        f"  · Strategy: `{md_v2_escape(strategy)}`\n"
        f"  · Risk: `{md_v2_escape(risk)}`\n"
        f"  · Capital: `${capital:,.0f}`\n"
        f"  · Mode: `{md_v2_escape(mode)}`\n\n"
        f"{cta('Ready to begin?')}"
    )


def render_autotrade_configure_strategy() -> str:
    return (
        f"🤖 *Auto Trade* · Configure · Strategy\n"
        f"{DIV}\n\n"
        f"*Choose a Strategy*\n"
        f"  · 🧹 *Close Sweep* — Near\\-expiry markets\n"
        f"  · 📈 *Trend Breakout* — Trend following\n"
        f"  · 🔄 *Contrarian* — Buy pullbacks\n"
        f"  · 🚀 *Crypto Scalper* — Short\\-term scalps\n\n"
        f"{cta('Select a strategy:')}"
    )


def render_autotrade_configure_capital(current: float = 100.0) -> str:
    return (
        f"🤖 *Auto Trade* · Configure · Capital\n"
        f"{DIV}\n\n"
        f"Current Allocation: `${current:,.0f}`\n\n"
        f"{cta('Choose allocation:')}"
    )


def render_autotrade_configure_risk() -> str:
    return (
        f"🤖 *Auto Trade* · Configure · Risk\n"
        f"{DIV}\n\n"
        f"*Choose a Risk Level*\n"
        f"  · 🟢 *Safe* — Lower risk · fewer trades\n"
        f"  · 🟡 *Balanced* — Recommended\n"
        f"  · 🔴 *Aggressive* — Higher volatility\n\n"
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
        f"🤖 *Auto Trade* · Configure · Review\n"
        f"{DIV}\n\n"
        f"*Your Setup*\n"
        f"  · Strategy: `{md_v2_escape(strategy)}`\n"
        f"  · Capital: `${capital:,.0f}`\n"
        f"  · Risk: `{md_v2_escape(risk)}`\n"
        f"  · Mode: `{md_v2_escape(mode)}`\n\n"
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
        f"📊 *Strategy Status*\n"
        f"{DIV}\n\n"
        f"{pre_block([('Name', strategy), ('Status', status), ('Capital', f'${capital:,.0f}'), ('PnL Today', pnl(pnl_today)), ('Trades', str(trades))])}\n"
        f"{DIV}\n"
        f"{cta('Select an action:')}"
    )


def render_autotrade_pause_confirm() -> str:
    return (
        f"⏸ *Pause Auto Trade*\n"
        f"{DIV}\n\n"
        f"  · New trades: `Stopped`\n"
        f"  · Open positions: `Remain active`\n\n"
        f"{cta('Confirm pause?')}"
    )


def render_autotrade_resume_confirm() -> str:
    return (
        f"▶ *Resume Auto Trade*\n"
        f"{DIV}\n\n"
        f"  · Market monitoring: `Resumed`\n"
        f"  · Trade execution: `Enabled`\n\n"
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
        f"👥 *Copy Wallet*\n"
        f"{DIV}\n\n"
        f"  · Status: `{md_v2_escape(status)}`\n"
        f"  · Active Wallets: `{active_wallets} following`\n"
        f"  · Allocation: `${allocation:,.0f}`\n\n"
        f"{cta('Choose an action:')}"
    )


def render_copy_add_wallet_prompt() -> str:
    return (
        f"➕ *Add Wallet*\n"
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
        f"👥 *Wallet Review*\n"
        f"{DIV}\n\n"
        f"*Wallet Info*\n"
        f"{pre_block([('Address', address_short), ('Activity', activity), ('Recent Trades', str(recent_trades)), ('Risk', risk)])}\n"
        f"{DIV}\n"
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
        f"⚙️ *Wallet Configuration*\n"
        f"{DIV}\n\n"
        f"{pre_block([('Wallet', address_short), ('Allocation', f'${allocation:,.0f}'), ('Risk', risk), ('Copy Mode', copy_mode)])}\n"
        f"{DIV}\n"
        f"{cta('Confirm settings?')}"
    )


def render_copy_active_wallets_empty() -> str:
    return (
        f"👛 *Active Wallets*\n"
        f"{DIV}\n\n"
        f"  · Status: `No wallets added`\n\n"
        f"{cta('Add a wallet address to start copying')}"
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
        f"👛 *Active Wallets*\n"
        f"{DIV}\n\n"
        f"*Wallet \\#{index}*\n"
        f"{pre_block([('Address', address_short), ('Status', status), ('Allocation', f'${allocation:,.2f}'), ('PnL Today', pnl(pnl_today)), ('Trades', str(trades_copied))])}\n"
        f"{DIV}\n"
        f"{cta('Select an action:')}"
    )


def render_copy_pause_confirm() -> str:
    return (
        f"⏸ *Pause Copy Wallet*\n"
        f"{DIV}\n\n"
        f"  · New copied trades: `Stopped`\n"
        f"  · Existing positions: `Stay active`\n\n"
        f"{cta('Confirm pause?')}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 11. Markets
# ─────────────────────────────────────────────────────────────────────────────


def render_markets_home() -> str:
    return (
        f"📈 *Markets*\n"
        f"{DIV}\n\n"
        f"*Browse*\n"
        f"  · 🔥 Trending — Most active markets\n"
        f"  · 🆕 New Markets — Fresh opportunities\n"
        f"  · 🧠 AI Insights — High\\-confidence setups\n"
        f"  · ⭐ Watchlist — Saved markets\n"
        f"  · 🔎 Search — Find any market\n\n"
        f"{cta('Choose a view:')}"
    )


def render_markets_trending(items) -> str:
    lines = [f"🔥 *Trending Markets*\n{DIV}"]
    for it in (items or []):
        rank = md_v2_escape(str(it.get("rank", "")))
        t = md_v2_escape(str(it.get("title", "")).replace("\n", " ").strip()[:60])
        yes = str(it.get("yes", "—"))
        no = str(it.get("no", "—"))
        vol = str(it.get("volume", "—"))
        lines.append(
            f"*{rank}\\. {t}*\n"
            f"  YES `{yes}` · NO `{no}` · Vol `{vol}`"
        )
    if not items:
        lines.append("_No trending markets right now_")
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
        f"🎯 *{md_v2_escape(title)}*\n"
        f"{DIV}\n"
        f"{pre_block([('YES', yes), ('NO', no), ('Volume', volume), ('Closes', closes), ('Sentiment', sentiment)])}\n"
        f"{DIV}\n"
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
        f"💼 *Portfolio*\n"
        f"{DIV}\n"
        f"{pre_block([('Balance', f'${balance:,.2f}'), ('Equity', f'${equity:,.2f}'), ('Positions', str(open_positions))])}\n\n"
        f"*💰 Performance*\n"
        f"{pre_block([('Today', pnl(today_pnl)), ('7 Days', pnl(week_pnl))])}\n"
        f"{DIV}\n"
        f"{cta('Select a view:')}"
    )


def render_positions_empty() -> str:
    return (
        f"📋 *Open Positions*\n"
        f"{DIV}\n\n"
        f"  · Status: `No open positions`\n\n"
        f"{cta('Start automation to open positions')}"
    )


def render_positions_list(
    items,
    *,
    page: int = 1,
    total_pages: int = 1,
    total: int = 0,
) -> str:
    header = f"📋 *Open Positions*  ·  {total} active\n{DIV}"
    cards = []
    for it in (items or []):
        raw_rank = str(it.get("rank", "")).strip()
        market_title = md_v2_escape(
            str(it.get("title", "")).replace("\n", " ").strip()
        )
        label = (
            f"{md_v2_escape(raw_rank)}\\. {market_title}" if raw_rank else market_title
        )
        side = str(it.get("side", "—"))
        pnl_val = float(it.get("pnl", 0.0))
        block = pre_block([("Side", side), ("PnL", pnl(pnl_val))])
        cards.append(f"*{label}*\n{block}")
    if not cards:
        cards = ["_No open positions_"]
    footer = f"{DIV}\n_Page {page} of {total_pages}_"
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
        f"📌 *Position Details*\n"
        f"{DIV}\n\n"
        f"*{md_v2_escape(market_title)}*\n"
        f"{pre_block([('Side', side), ('Entry', f'{entry}¢'), ('Current', f'{current}¢'), ('PnL', pnl(pnl_value)), ('Status', status)])}\n"
        f"{DIV}\n"
        f"{cta('Choose an action:')}"
    )


def render_history_empty() -> str:
    return (
        f"📜 *Trade History*\n"
        f"{DIV}\n\n"
        f"Status: `No trades yet`\n\n"
        f"{cta('Start automation to build history')}"
    )


def render_history_home(*, today: int = 0, week: int = 0) -> str:
    return (
        f"📜 *Trade History*\n"
        f"{DIV}\n\n"
        f"  · Today: `{today} trades`\n"
        f"  · This Week: `{week} trades`\n\n"
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
        f"💹 *Performance*\n"
        f"{DIV}\n"
        f"{pre_block([('Today', pnl(today_pnl)), ('7 Days', pnl(week_pnl)), ('Win Rate', f'{win_rate}%'), ('Trades', str(trades))])}"
    )


def render_balance(
    *,
    available: float = 0.0,
    allocated: float = 0.0,
) -> str:
    free = max(available - allocated, 0.0)
    return (
        f"💰 *Balance*\n"
        f"{DIV}\n"
        f"{pre_block([('Available', f'${available:,.2f}'), ('Allocated', f'${allocated:,.2f}'), ('Free Capital', f'${free:,.2f}')])}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 13. Settings
# ─────────────────────────────────────────────────────────────────────────────


def render_settings_home(*, trading_mode: str = PAPER) -> str:
    return (
        f"⚙️ *Settings*\n"
        f"{DIV}\n\n"
        f"  · 🔄 Trading Mode: `{md_v2_escape(trading_mode)}`\n"
        f"  · 🛡 Risk: `Balanced`\n"
        f"  · 🔔 Alerts: `ON`\n"
        f"  · 👥 Copy Wallet: `OFF`\n"
        f"  · 👤 Account: `Profile`\n"
        f"  · 🧪 Advanced: `Power user`"
    )


def render_settings_trading_mode(*, current: str = PAPER) -> str:
    return (
        f"🔄 *Trading Mode*\n"
        f"{DIV}\n\n"
        f"Current Mode: `{md_v2_escape(current)}`\n\n"
        f"*Options*\n"
        f"  · 📝 Paper Mode — Safe simulation\n"
        f"  · 💸 Live Mode — Real capital execution"
    )


def render_settings_live_gate() -> str:
    return (
        f"⚠️ *Live Trading*\n"
        f"{DIV}\n\n"
        f"Status: `{LOCKED} Disabled`\n\n"
        f"*Activation Requirements*\n"
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
        f"🛡 *Risk Controls*\n"
        f"{DIV}\n"
        f"{pre_block([('Daily Loss Limit', f'${daily_loss_limit:,.0f}'), ('Max Position Size', f'{max_position_pct}%'), ('Concurrent Trades', f'{max_concurrent} max'), ('Auto Pause', auto_pause)])}"
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
        f"🔔 *Notifications*\n"
        f"{DIV}\n\n"
        f"  · Trade Opened: `{on if trade_opened else off}`\n"
        f"  · Trade Closed: `{on if trade_closed else off}`\n"
        f"  · Risk Alerts: `{on if risk_alerts else off}`\n"
        f"  · Daily Summary: `{on if daily_summary else off}`\n"
        f"  · Market Alerts: `{on if market_alerts else off}`"
    )


def render_settings_account(
    *,
    wallet_status: str = "Connected",
    mode: str = PAPER,
    api_status: str = "🟢 Healthy",
    subscription: str = "MVP",
) -> str:
    return (
        f"👤 *Account*\n"
        f"{DIV}\n\n"
        f"  · Wallet: `{md_v2_escape(wallet_status)}`\n"
        f"  · Mode: `{md_v2_escape(mode)}`\n"
        f"  · API Status: `{md_v2_escape(api_status)}`\n"
        f"  · Subscription: `{md_v2_escape(subscription)}`"
    )


def render_settings_advanced(*, debug_enabled: bool = False) -> str:
    debug = "🟢 Enabled" if debug_enabled else "🔴 Disabled"
    return (
        f"🧪 *Advanced*\n"
        f"{DIV}\n\n"
        f"  · Strategy Logs: `View execution logs`\n"
        f"  · Debug Mode: `{debug}`\n"
        f"  · Data Refresh: `Real\\-time`\n"
        f"  · System Health: `🟢 Operational`"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 14. Help
# ─────────────────────────────────────────────────────────────────────────────


def render_help_home() -> str:
    return (
        f"❓ *Help*\n"
        f"{DIV}\n\n"
        f"*Topics*\n"
        f"  · 🚀 Quick Start Guide\n"
        f"  · 🤖 How Auto Trade Works\n"
        f"  · 👥 How Copy Wallet Works\n"
        f"  · 🛡 Risk & Safety\n"
        f"  · 💬 FAQ\n"
        f"  · 🆘 Support\n\n"
        f"{cta('Choose a topic:')}"
    )


def render_help_quick_start_guide() -> str:
    return (
        f"🚀 *Quick Start Guide*\n"
        f"{DIV}\n\n"
        f"*Steps*\n"
        f"  1\\. Configure Auto Trade\n"
        f"  2\\. Choose risk & capital\n"
        f"  3\\. Start in Paper Mode\n"
        f"  4\\. Monitor performance\n\n"
        f"Tip: `Use Paper Mode first`"
    )


def render_help_how_auto_trade() -> str:
    return (
        f"🤖 *How Auto Trade Works*\n"
        f"{DIV}\n\n"
        f"  · Purpose: `Bot trades automatically`\n"
        f"  · Decision Engine: `Strategy\\-based execution`\n"
        f"  · You Control: `Capital · Risk · Strategy`\n"
        f"  · Bot Controls: `Market execution`\n"
        f"  · Safety: `Risk protections enabled`"
    )


def render_help_how_copy_wallet() -> str:
    return (
        f"👥 *How Copy Wallet Works*\n"
        f"{DIV}\n\n"
        f"  · Purpose: `Mirror target wallet activity`\n"
        f"  · What Happens: `Trades may be copied automatically`\n"
        f"  · You Control: `Allocation · Risk · Wallet`\n"
        f"  · Important: `Past performance ≠ future results`\n"
        f"  · Recommendation: `Start small`"
    )


def render_help_safety() -> str:
    return (
        f"🛡 *Risk & Safety*\n"
        f"{DIV}\n\n"
        f"*Protections*\n"
        f"  · Paper Mode — Practice without real funds\n"
        f"  · Daily Loss Limit — Auto stop protection\n"
        f"  · Auto Pause — Risk circuit breaker\n\n"
        f"*Warnings*\n"
        f"  · Copy Wallet — Past performance ≠ future results\n"
        f"  · Never risk more than you can afford"
    )


def render_help_faq() -> str:
    return (
        f"💬 *FAQ*\n"
        f"{DIV}\n\n"
        f"  · Is the bot safe? `Yes — paper mode by default`\n"
        f"  · Can I lose money? `Paper mode uses virtual funds only`\n"
        f"  · How to stop? `Tap Pause or Stop Bot in Auto Mode`"
    )


def render_help_support() -> str:
    return (
        f"🆘 *Support*\n"
        f"{DIV}\n\n"
        f"  · Help Center: `Common troubleshooting`\n"
        f"  · Report Issue: `Found a problem?`\n"
        f"  · Status: `🟢 Systems Operational`"
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
        f"🤖 *Auto Trade Started*\n"
        f"{DIV}\n"
        f"{pre_block([('Strategy', strategy), ('Capital', f'${capital:,.2f}'), ('Risk', risk), ('Status', status)])}"
    )


def render_notif_bot_waiting() -> str:
    return (
        f"⏳ *Waiting for Signal*\n"
        f"{DIV}\n\n"
        f"Status: `Scanning markets\\.\\.\\.`"
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
        f"⚡ *Position Opened*\n"
        f"{DIV}\n"
        f"{pre_block([('Market', market_title[:40]), ('Side', side), ('Size', f'${size:,.2f}'), ('Price', f'{price:.3f}'), ('Mode', mode)])}\n"
        f"{DIV}"
    )


def render_notif_first_trade(
    *,
    market_title: str,
    side: str,
    size: float,
) -> str:
    return (
        f"🎉 *First Trade\\!*\n"
        f"{DIV}\n"
        f"{pre_block([('Market', market_title[:40]), ('Side', side), ('Size', f'${size:,.2f}')])}"
    )


def render_notif_trade_closed(
    *,
    market_title: str,
    side: str,
    size: float,
    pnl_value: float,
) -> str:
    return (
        f"✅ *Position Closed*\n"
        f"{DIV}\n"
        f"{pre_block([('Market', market_title[:40]), ('Side', side), ('Size', f'${size:,.2f}'), ('PnL', pnl(pnl_value))])}"
    )


def render_notif_wallet_copied(
    *,
    address_short: str,
    market_title: str,
    side: str,
    size: float,
) -> str:
    return (
        f"🔁 *Wallet Copied*\n"
        f"{DIV}\n"
        f"{pre_block([('Wallet', address_short), ('Market', market_title[:40]), ('Side', side), ('Size', f'${size:,.2f}')])}"
    )


def render_notif_drawdown_warning(*, drawdown_pct: float) -> str:
    return (
        f"⚠️ *Drawdown Warning*\n"
        f"{DIV}\n\n"
        f"Drawdown: `{drawdown_pct:.1f}%`\n"
        f"{cta('Review positions — auto pause may trigger')}"
    )


def render_notif_auto_pause(*, reason: str = "Daily loss limit reached") -> str:
    return (
        f"⏸ *Auto Pause Triggered*\n"
        f"{DIV}\n\n"
        f"Reason: `{md_v2_escape(reason)}`\n\n"
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
        f"📊 *Daily Summary*\n"
        f"{DIV}\n"
        f"{pre_block([('Trades', str(trades)), ('PnL', pnl(pnl_today)), ('Win Rate', f'{win_rate}%'), ('Mode', mode)])}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 16. System states
# ─────────────────────────────────────────────────────────────────────────────


def render_syncing() -> str:
    return f"🔄 *Syncing\\.\\.\\.*\n\n{cta('Please wait')}"


def render_error_api() -> str:
    return (
        f"❌ *API Error*\n"
        f"{DIV}\n\n"
        f"Status: `Connection issue`\n\n"
        f"{cta('Try again in a moment')}"
    )


def render_error_invalid_wallet() -> str:
    return (
        f"❌ *Invalid Wallet*\n"
        f"{DIV}\n\n"
        f"Status: `Address not recognized`\n\n"
        f"{cta('Check the address and try again')}"
    )


def render_error_bot_paused() -> str:
    return (
        f"⏸ *Bot Paused*\n"
        f"{DIV}\n\n"
        f"Status: `Manually paused`\n\n"
        f"{cta('Resume from Auto Mode')}"
    )


def render_error_live_locked() -> str:
    return (
        f"🔒 *Live Trading Locked*\n"
        f"{DIV}\n\n"
        f"Status: `Paper mode only`\n\n"
        f"{cta('Contact operator to unlock live trading')}"
    )


def render_deposit_prompt() -> str:
    return (
        f"💰 *Deposit Funds*\n"
        f"{DIV}\n\n"
        f"  · Mode: `{PAPER}`\n"
        f"  · Demo Capital: `Ready`\n\n"
        f"{cta('Fund your account to increase capital')}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 17. Onboarding
# ─────────────────────────────────────────────────────────────────────────────


def render_welcome(*, user_name: str = "trader") -> str:
    return (
        f"🛡️ *Welcome, {md_v2_escape(user_name)}\\!*\n"
        f"{DIV}\n\n"
        f"*CrusaderBot* — Trade prediction markets with controlled risk\\.\n\n"
        f"  · Mode: `{PAPER}`\n"
        f"  · Demo Capital: `$1,000 ready`\n"
        f"  · Live Trading: `{LOCKED}`\n\n"
        f"{cta('Tap Get Started to begin')}"
    )


def render_wallet_ready(*, address_short: str) -> str:
    return (
        f"✅ *Wallet Ready*\n"
        f"{DIV}\n\n"
        f"  · Address: `{md_v2_escape(address_short)}`\n"
        f"  · Status: `Connected`\n\n"
        f"{cta('Choose a preset to continue')}"
    )
