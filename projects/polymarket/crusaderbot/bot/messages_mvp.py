"""MVP v1 Telegram message renderers (hierarchy tree format).

Every screen defined in docs/ux/telegram-mvp-v1.md has one render_* function
here. Renderers are pure: they take primitives, return strings. No I/O, no
DB calls. Handlers fetch data, call these renderers, and send the result.
"""
from __future__ import annotations

from typing import Iterable, Sequence

from .ui.tree import (
    BAR,
    BRANCH,
    LAST,
    LIVE,
    LOCKED,
    PAPER,
    STATUS_NOT_SET,
    STATUS_PAUSED,
    STATUS_RUNNING,
    STATUS_STOPPED,
    STATUS_SYNCING,
    join_blocks,
    leaf,
    nested,
    pnl,
    section,
    title,
)

# ────────────────────────────────────────────────────────────────────────────
# 8. Dashboard
# ────────────────────────────────────────────────────────────────────────────


def render_dashboard_default(
    *,
    bot_status: str = STATUS_RUNNING,
    today_pnl: float = 0.0,
    today_trades: int = 0,
    active_strategy: str = "⚡ Momentum",
    copy_wallets_active: int = 0,
    portfolio_value: float = 0.0,
) -> str:
    blocks = [
        title("🏠 Dashboard"),
        leaf("🤖 Bot Status", bot_status),
        section("💹 Today", [
            ("PnL", pnl(today_pnl)),
            ("Trades", str(today_trades)),
        ]),
        leaf("🤖 Auto Trade", active_strategy),
        leaf("👥 Copy Wallet", f"{copy_wallets_active} Active"),
        leaf("💼 Portfolio", f"${portfolio_value:,.2f}", last=True),
    ]
    return join_blocks(blocks)


def render_dashboard_new_user() -> str:
    blocks = [
        title("🏠 Dashboard"),
        leaf("👋 Welcome", "Your bot is not configured yet"),
        leaf("🚀 Quick Start", "Recommended for beginners"),
        leaf("🤖 Auto Trade", STATUS_NOT_SET),
        leaf("👥 Copy Wallet", STATUS_NOT_SET),
        f"{LAST} Ready to begin?",
    ]
    return join_blocks(blocks)


def render_dashboard_paused(*, reason: str = "Manual Pause", today_pnl: float = 0.0) -> str:
    blocks = [
        title("🏠 Dashboard"),
        section("🤖 Bot Status", [
            ("State", STATUS_PAUSED),
            ("Reason", reason),
        ]),
        leaf("💹 Today", pnl(today_pnl)),
        leaf("Action Required", "Resume trading to continue", last=True),
    ]
    return join_blocks(blocks)


def render_dashboard_risk_alert(*, message: str = "Daily drawdown nearing limit") -> str:
    blocks = [
        title("🏠 Dashboard"),
        leaf("⚠ Risk Alert", message),
        leaf("🤖 Bot Protection", "Auto pause may trigger"),
        leaf("💼 Portfolio", "Review open positions"),
        leaf("Recommended Action", "Adjust risk settings", last=True),
    ]
    return join_blocks(blocks)


# ────────────────────────────────────────────────────────────────────────────
# 9. Auto Trade
# ────────────────────────────────────────────────────────────────────────────


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
    blocks = [
        title("🤖 Auto Trade"),
        leaf("Status", status),
        leaf("Active Strategy", strategy),
        section("Configuration", [
            ("💰 Capital", f"${capital:,.0f}"),
            ("⚖️ Risk", risk),
            ("📝 Mode", mode),
        ]),
        section("Performance", [
            ("📈 PnL Today", pnl(pnl_today)),
            ("🔥 Executions", str(executions)),
            ("🎯 Win Rate", f"{win_rate}%"),
        ]),
        f"{LAST} Choose an action:",
    ]
    return join_blocks(blocks)


def render_autotrade_quick_start(
    *,
    strategy: str = "⚡ Momentum",
    risk: str = "🟡 Balanced",
    capital: float = 100.0,
    mode: str = PAPER,
) -> str:
    blocks = [
        title("🚀 Quick Start"),
        section("Recommended Setup", [
            ("🧠 Strategy", strategy),
            ("⚖️ Risk", risk),
            ("💰 Capital", f"${capital:,.0f}"),
            ("📝 Mode", mode),
        ], last=False),
        f"{LAST} Ready to begin?",
    ]
    return join_blocks(blocks)


def render_autotrade_configure_strategy() -> str:
    blocks = [
        title("🤖 Auto Trade / Configure / Strategy"),
        leaf("⚡ Momentum", "Fast trend following"),
        leaf("📊 Mean Reversion", "Buy pullbacks"),
        leaf("🧪 Smart Hybrid", "Mixed adaptive mode", last=True),
    ]
    return join_blocks(blocks)


def render_autotrade_configure_capital(current: float = 100.0) -> str:
    blocks = [
        title("🤖 Auto Trade / Configure / Capital"),
        leaf("Current Allocation", f"${current:,.0f}"),
        f"{LAST} Choose allocation:",
    ]
    return join_blocks(blocks)


def render_autotrade_configure_risk() -> str:
    blocks = [
        title("🤖 Auto Trade / Configure / Risk"),
        leaf("🟢 Safe", "Lower risk • fewer trades"),
        leaf("🟡 Balanced", "Recommended"),
        leaf("🔴 Aggressive", "Higher volatility", last=True),
    ]
    return join_blocks(blocks)


def render_autotrade_configure_review(
    *,
    strategy: str,
    capital: float,
    risk: str,
    mode: str = PAPER,
) -> str:
    blocks = [
        title("🤖 Auto Trade / Configure / Review"),
        leaf("🧠 Strategy", strategy),
        leaf("💰 Capital", f"${capital:,.0f}"),
        leaf("⚖️ Risk", risk),
        leaf("📝 Mode", mode),
        f"{LAST} Looks good?",
    ]
    return join_blocks(blocks)


def render_autotrade_strategy_status(
    *,
    strategy: str,
    status: str,
    capital: float,
    pnl_today: float,
    trades: int,
) -> str:
    blocks = [
        title("📊 Strategy Status"),
        section("Strategy", [
            ("Name", strategy),
            ("Status", status),
            ("Capital", f"${capital:,.0f}"),
            ("PnL Today", pnl(pnl_today)),
            ("Trades", str(trades)),
        ], last=False),
        f"{LAST} Select an action:",
    ]
    return join_blocks(blocks)


def render_autotrade_pause_confirm() -> str:
    blocks = [
        title("⏸ Pause Auto Trade"),
        section("Effect", [
            ("New trades", "Stopped"),
            ("Open positions", "Remain active"),
        ], last=False),
        f"{LAST} Confirm pause?",
    ]
    return join_blocks(blocks)


def render_autotrade_resume_confirm() -> str:
    blocks = [
        title("▶ Resume Auto Trade"),
        section("Effect", [
            ("Market monitoring", "Resumed"),
            ("Trade execution", "Enabled"),
        ], last=False),
        f"{LAST} Continue trading?",
    ]
    return join_blocks(blocks)


# ────────────────────────────────────────────────────────────────────────────
# 10. Copy Wallet
# ────────────────────────────────────────────────────────────────────────────


def render_copy_home(
    *,
    status: str = STATUS_NOT_SET,
    active_wallets: int = 0,
    allocation: float = 0.0,
) -> str:
    blocks = [
        title("👥 Copy Wallet"),
        leaf("Status", status),
        leaf("Active Wallets", f"{active_wallets} Following"),
        leaf("Allocation", f"${allocation:,.0f}"),
        f"{LAST} Choose an action:",
    ]
    return join_blocks(blocks)


def render_copy_add_wallet_prompt() -> str:
    blocks = [
        title("➕ Add Wallet"),
        leaf("Step 1", "Paste wallet address"),
        leaf("Example", "0x123...abc", last=True),
    ]
    return join_blocks(blocks)


def render_copy_wallet_review(
    *,
    address_short: str,
    activity: str = STATUS_RUNNING,
    recent_trades: int = 0,
    risk: str = "🟡 Moderate",
) -> str:
    blocks = [
        title("👥 Wallet Review"),
        leaf("Address", address_short),
        leaf("Activity", activity),
        leaf("Recent Trades", str(recent_trades)),
        leaf("Risk", risk, last=True),
    ]
    return join_blocks(blocks)


def render_copy_wallet_configure(
    *,
    address_short: str,
    allocation: float,
    risk: str,
    copy_mode: str = "Mirror Trades",
) -> str:
    blocks = [
        title("⚙️ Wallet Configuration"),
        leaf("Wallet", address_short),
        leaf("Allocation", f"${allocation:,.0f}"),
        leaf("Risk", risk),
        leaf("Copy Mode", copy_mode, last=True),
    ]
    return join_blocks(blocks)


def render_copy_active_wallets_empty() -> str:
    blocks = [
        title("👛 Active Wallets"),
        leaf("Status", "No wallets added"),
        leaf("Next Step", "Add a wallet address to start copying", last=True),
    ]
    return join_blocks(blocks)


def render_copy_wallet_card(
    *,
    index: int,
    address_short: str,
    status: str,
    allocation: float,
    pnl_today: float,
    trades_copied: int,
) -> str:
    blocks = [
        title("👛 Active Wallets"),
        section(f"Wallet #{index}", [
            ("Address", address_short),
            ("Status", status),
            ("Allocation", f"${allocation:,.0f}"),
            ("PnL Today", pnl(pnl_today)),
            ("Trades Copied", str(trades_copied)),
        ], last=False),
        f"{LAST} Select an action:",
    ]
    return join_blocks(blocks)


def render_copy_pause_confirm() -> str:
    blocks = [
        title("⏸ Pause Copy Wallet"),
        section("Effect", [
            ("New copied trades", "Stopped"),
            ("Existing positions", "Stay active"),
        ], last=False),
        f"{LAST} Confirm pause?",
    ]
    return join_blocks(blocks)


# ────────────────────────────────────────────────────────────────────────────
# 11. Markets
# ────────────────────────────────────────────────────────────────────────────


def render_markets_home() -> str:
    blocks = [
        title("📈 Markets"),
        leaf("🔥 Trending", "Most active markets"),
        leaf("🆕 New Markets", "Fresh opportunities"),
        leaf("🧠 AI Insights", "High-confidence setups"),
        leaf("⭐ Watchlist", "Saved markets"),
        leaf("🔎 Search", "Find any market", last=True),
    ]
    return join_blocks(blocks)


def render_markets_trending(items: Sequence[dict]) -> str:
    """items: [{rank, title, yes, no, volume, sentiment}, ...]"""
    blocks: list[str] = [title("🔥 Trending Markets")]
    for it in items:
        rank = it.get("rank", "")
        blocks.append(section(f"{rank} {it.get('title', '')}", [
            ("Price", f"YES {it.get('yes')}¢ • NO {it.get('no')}¢"),
            ("Volume", it.get("volume", "—")),
            ("Sentiment", it.get("sentiment", "—")),
        ]))
    blocks.append(f"{LAST} Select a market:")
    return join_blocks(blocks)


def render_markets_detail(
    *,
    market_title: str,
    yes_price: str,
    no_price: str,
    sentiment: str,
    ai_confidence: str,
    bot_exposure: str = "No active position",
) -> str:
    blocks = [
        title("📊 Market Details"),
        leaf("Market", market_title),
        section("Market Price", [
            ("YES", f"{yes_price}¢"),
            ("NO", f"{no_price}¢"),
        ]),
        leaf("Sentiment", sentiment),
        leaf("AI Confidence", ai_confidence),
        leaf("Bot Exposure", bot_exposure),
        leaf("Available Actions", "Monitor • Watch • Auto", last=True),
    ]
    return join_blocks(blocks)


def render_markets_ai_insight(
    *,
    market_title: str,
    confidence: str,
    reason: str,
    bot_exposure: str = "No active position",
) -> str:
    blocks = [
        title("🧠 AI Insights"),
        leaf("Market", market_title),
        leaf("Confidence", confidence),
        leaf("Reason", reason),
        leaf("Bot Exposure", bot_exposure, last=True),
    ]
    return join_blocks(blocks)


def render_markets_search_prompt() -> str:
    blocks = [
        title("🔎 Search Markets"),
        leaf("Send a keyword", "Example: BTC, Trump, ETH", last=True),
    ]
    return join_blocks(blocks)


def render_watchlist_empty() -> str:
    blocks = [
        title("⭐ Watchlist"),
        leaf("Status", "No markets saved"),
        leaf("Tip", "Add markets from AI Insights or Trending", last=True),
    ]
    return join_blocks(blocks)


# ────────────────────────────────────────────────────────────────────────────
# 12. Portfolio
# ────────────────────────────────────────────────────────────────────────────


def render_portfolio_home(
    *,
    balance: float = 0.0,
    today_pnl: float = 0.0,
    today_trades: int = 0,
    today_win_rate: int = 0,
    open_positions: int = 0,
) -> str:
    blocks = [
        title("💼 Portfolio"),
        leaf("💰 Balance", f"${balance:,.2f}"),
        section("💹 Today", [
            ("PnL", pnl(today_pnl)),
            ("Trades", str(today_trades)),
            ("Win Rate", f"{today_win_rate}%"),
        ]),
        leaf("📌 Open Positions", f"{open_positions} Active"),
        f"{LAST} Choose an action:",
    ]
    return join_blocks(blocks)


def render_positions_empty() -> str:
    blocks = [
        title("📌 Open Positions"),
        leaf("Status", "No active positions"),
        leaf("Note", "Your bot will trade when opportunities appear", last=True),
    ]
    return join_blocks(blocks)


def render_positions_list(items: Sequence[dict]) -> str:
    """items: [{rank, title, side, pnl}, ...]"""
    blocks: list[str] = [title("📌 Open Positions")]
    for it in items:
        blocks.append(section(f"{it.get('rank', '')} {it.get('title', '')}", [
            ("Side", it.get("side", "—")),
            ("PnL", pnl(float(it.get("pnl", 0.0)))),
        ]))
    blocks.append(f"{LAST} Select a position:")
    return join_blocks(blocks)


def render_position_detail(
    *,
    market_title: str,
    side: str,
    entry: str,
    current: str,
    pnl_value: float,
    status: str = STATUS_RUNNING.replace("Running", "Open"),
) -> str:
    blocks = [
        title("📌 Position Details"),
        leaf("Market", market_title),
        leaf("Side", side),
        leaf("Entry", f"{entry}¢"),
        leaf("Current", f"{current}¢"),
        leaf("PnL", pnl(pnl_value)),
        leaf("Status", status, last=True),
    ]
    return join_blocks(blocks)


def render_history_empty() -> str:
    blocks = [
        title("📜 Trade History"),
        leaf("Status", "No trades yet"),
        leaf("Note", "Start automation to build history", last=True),
    ]
    return join_blocks(blocks)


def render_history_home(*, today: int = 0, week: int = 0) -> str:
    blocks = [
        title("📜 Trade History"),
        leaf("Today", f"{today} Trades"),
        leaf("This Week", f"{week} Trades"),
        f"{LAST} Choose range:",
    ]
    return join_blocks(blocks)


def render_performance(
    *,
    today_pnl: float = 0.0,
    week_pnl: float = 0.0,
    win_rate: int = 0,
    trades: int = 0,
) -> str:
    blocks = [
        title("💹 Performance"),
        leaf("Today", pnl(today_pnl)),
        leaf("7 Days", pnl(week_pnl)),
        leaf("Win Rate", f"{win_rate}%"),
        leaf("Trades", str(trades), last=True),
    ]
    return join_blocks(blocks)


def render_balance(
    *,
    available: float = 0.0,
    allocated: float = 0.0,
) -> str:
    free = max(available - allocated, 0.0)
    blocks = [
        title("💰 Balance"),
        leaf("Available", f"${available:,.2f}"),
        leaf("Allocated", f"${allocated:,.2f}"),
        leaf("Free Capital", f"${free:,.2f}", last=True),
    ]
    return join_blocks(blocks)


# ────────────────────────────────────────────────────────────────────────────
# 13. Settings
# ────────────────────────────────────────────────────────────────────────────


def render_settings_home(*, trading_mode: str = PAPER) -> str:
    blocks = [
        title("⚙️ Settings"),
        leaf("🔄 Trading Mode", trading_mode),
        leaf("🛡 Risk Controls", "Daily protections"),
        leaf("🔔 Notifications", "Trade alerts enabled"),
        leaf("👥 Copy Wallet", "Wallet mirroring settings"),
        leaf("👤 Account", "Wallet & profile"),
        leaf("🧪 Advanced", "Power user settings", last=True),
    ]
    return join_blocks(blocks)


def render_settings_trading_mode(*, current: str = PAPER) -> str:
    blocks = [
        title("🔄 Trading Mode"),
        leaf("Current Mode", current),
        leaf("📝 Paper Mode", "Safe simulation"),
        leaf("💸 Live Mode", "Real capital execution", last=True),
    ]
    return join_blocks(blocks)


def render_settings_live_gate() -> str:
    blocks = [
        title("⚠ Live Trading"),
        leaf("Warning", "Real funds will be used"),
        leaf("Current Status", f"{LOCKED} Disabled"),
        leaf("Requirement", "Manual confirmation required"),
        leaf("Recommendation", "Use Paper Mode first", last=True),
    ]
    return join_blocks(blocks)


def render_settings_risk_controls(
    *,
    daily_loss_limit: float = 20.0,
    max_position_pct: int = 10,
    max_concurrent: int = 3,
    auto_pause_enabled: bool = True,
) -> str:
    auto_pause = STATUS_RUNNING.replace("Running", "Enabled") if auto_pause_enabled else STATUS_STOPPED.replace("Stopped", "Disabled")
    blocks = [
        title("🛡 Risk Controls"),
        leaf("Daily Loss Limit", f"${daily_loss_limit:,.0f}"),
        leaf("Max Position Size", f"{max_position_pct}%"),
        leaf("Concurrent Trades", f"{max_concurrent} Max"),
        leaf("Auto Pause", auto_pause, last=True),
    ]
    return join_blocks(blocks)


def render_settings_notifications(
    *,
    trade_opened: bool = True,
    trade_closed: bool = True,
    risk_alerts: bool = True,
    daily_summary: bool = True,
    market_alerts: bool = False,
) -> str:
    on = "🟢 Enabled"
    off = "🔴 Disabled"
    blocks = [
        title("🔔 Notifications"),
        leaf("Trade Opened", on if trade_opened else off),
        leaf("Trade Closed", on if trade_closed else off),
        leaf("Risk Alerts", on if risk_alerts else off),
        leaf("Daily Summary", on if daily_summary else off),
        leaf("Market Alerts", on if market_alerts else off, last=True),
    ]
    return join_blocks(blocks)


def render_settings_account(
    *,
    wallet_status: str = "Connected",
    mode: str = PAPER,
    api_status: str = STATUS_RUNNING.replace("Running", "Healthy"),
    subscription: str = "MVP",
) -> str:
    blocks = [
        title("👤 Account"),
        leaf("Wallet", wallet_status),
        leaf("Mode", mode),
        leaf("API Status", api_status),
        leaf("Subscription", subscription, last=True),
    ]
    return join_blocks(blocks)


def render_settings_advanced(*, debug_enabled: bool = False) -> str:
    debug = STATUS_RUNNING.replace("Running", "Enabled") if debug_enabled else STATUS_STOPPED.replace("Stopped", "Disabled")
    blocks = [
        title("🧪 Advanced"),
        leaf("Strategy Logs", "View execution logs"),
        leaf("Debug Mode", debug),
        leaf("Data Refresh", "Real-time"),
        leaf("System Health", STATUS_RUNNING.replace("Running", "Operational"), last=True),
    ]
    return join_blocks(blocks)


# ────────────────────────────────────────────────────────────────────────────
# 14. Help & Onboarding
# ────────────────────────────────────────────────────────────────────────────


def render_help_home() -> str:
    blocks = [
        title("❓ Help"),
        leaf("🚀 Quick Start Guide", "Get started in under 2 minutes"),
        leaf("🤖 How Auto Trade Works", "Learn how automation works"),
        leaf("👥 How Copy Wallet Works", "Mirror wallet activity"),
        leaf("🛡 Risk & Safety", "Understand protections"),
        leaf("💬 FAQ", "Common questions"),
        leaf("🆘 Support", "Need help?", last=True),
    ]
    return join_blocks(blocks)


def render_help_quick_start_guide() -> str:
    blocks = [
        title("🚀 Quick Start Guide"),
        leaf("Step 1", "Configure Auto Trade"),
        leaf("Step 2", "Choose risk & capital"),
        leaf("Step 3", "Start in Paper Mode"),
        leaf("Step 4", "Monitor performance"),
        leaf("Recommendation", "Use Paper Mode first", last=True),
    ]
    return join_blocks(blocks)


def render_help_how_auto_trade() -> str:
    blocks = [
        title("🤖 How Auto Trade Works"),
        leaf("Purpose", "Bot trades automatically"),
        leaf("Decision Engine", "Strategy-based execution"),
        nested("You Control", ["💰 Capital", "⚖️ Risk", "🧠 Strategy"]),
        leaf("Bot Controls", "Market execution"),
        leaf("Safety", "Risk protections enabled", last=True),
    ]
    return join_blocks(blocks)


def render_help_how_copy_wallet() -> str:
    blocks = [
        title("👥 How Copy Wallet Works"),
        leaf("Purpose", "Mirror target wallet activity"),
        leaf("What Happens", "Trades may be copied automatically"),
        nested("You Control", ["💰 Allocation", "⚖️ Risk", "Wallet selection"]),
        leaf("Important", "Past performance ≠ future results"),
        leaf("Recommendation", "Start small", last=True),
    ]
    return join_blocks(blocks)


def render_help_safety() -> str:
    blocks = [
        title("🛡 Risk & Safety"),
        leaf("Paper Mode", "Practice without real funds"),
        leaf("Daily Loss Limit", "Bot protection available"),
        leaf("Auto Pause", "Risk protection can stop trading"),
        leaf("Copy Wallet Risk", "Wallets can underperform"),
        leaf("Reminder", "Never risk more than you can afford", last=True),
    ]
    return join_blocks(blocks)


def render_help_faq() -> str:
    blocks = [
        title("💬 FAQ"),
        f"{BRANCH} 🤖 Is trading automatic?",
        f"{BRANCH} 📝 What is Paper Mode?",
        f"{BRANCH} 💸 Can I lose money?",
        f"{BRANCH} 👥 How does Copy Wallet work?",
        f"{LAST} 🔒 Is my wallet safe?",
    ]
    # Single-leaf FAQ entries; render as a flat list under the title.
    return "\n".join([blocks[0]] + blocks[1:])


def render_help_support() -> str:
    blocks = [
        title("🆘 Support"),
        leaf("Help Center", "Common troubleshooting"),
        leaf("Report Issue", "Found a problem?"),
        leaf("Status", STATUS_RUNNING.replace("Running", "Systems Operational"), last=True),
    ]
    return join_blocks(blocks)


# ────────────────────────────────────────────────────────────────────────────
# 15. Notifications
# ────────────────────────────────────────────────────────────────────────────


def render_notif_bot_started(
    *,
    strategy: str,
    capital: float,
    risk: str,
    status: str = STATUS_RUNNING,
) -> str:
    blocks = [
        title("🤖 Auto Trade Started"),
        leaf("Strategy", strategy),
        leaf("Capital", f"${capital:,.0f}"),
        leaf("Risk", risk),
        leaf("Status", status, last=True),
    ]
    return join_blocks(blocks)


def render_notif_bot_waiting() -> str:
    blocks = [
        title("🤖 Auto Trade Started"),
        leaf("Status", STATUS_RUNNING),
        leaf("What happens next", "Bot monitors opportunities automatically"),
        leaf("Note", "First trade may take time", last=True),
    ]
    return join_blocks(blocks)


def render_notif_trade_opened(
    *,
    market_title: str,
    side: str,
    strategy: str,
    entry: str,
    size: float,
    reason: str = "High confidence setup",
) -> str:
    blocks = [
        title("📈 Trade Opened"),
        leaf("Market", market_title),
        leaf("Position", side),
        leaf("Strategy", strategy),
        leaf("Entry", f"{entry}¢"),
        leaf("Size", f"${size:,.0f}"),
        leaf("Reason", reason, last=True),
    ]
    return join_blocks(blocks)


def render_notif_first_trade(market_title: str) -> str:
    blocks = [
        title("🎉 First Trade Opened"),
        leaf("Nice start", "Your bot placed its first trade"),
        leaf("Market", market_title),
        leaf("Status", "Monitoring performance", last=True),
    ]
    return join_blocks(blocks)


def render_notif_trade_closed(
    *,
    market_title: str,
    result_pnl: float,
    exit_reason: str,
    portfolio_balance: float,
) -> str:
    head = "🎯 Trade Closed" if result_pnl >= 0 else "📉 Trade Closed"
    last_label = "Portfolio Balance" if result_pnl >= 0 else "Portfolio Status"
    last_value = f"${portfolio_balance:,.2f}" if result_pnl >= 0 else "Stable"
    blocks = [
        title(head),
        leaf("Market", market_title),
        leaf("Result", pnl(result_pnl)),
        leaf("Exit Reason", exit_reason),
        leaf(last_label, last_value, last=True),
    ]
    return join_blocks(blocks)


def render_notif_wallet_copied(
    *,
    address_short: str,
    market_title: str,
    side: str,
    size: float,
    copy_mode: str = "Proportional",
) -> str:
    blocks = [
        title("👥 Wallet Trade Copied"),
        leaf("Wallet", address_short),
        leaf("Market", market_title),
        leaf("Position", side),
        leaf("Size", f"${size:,.0f}"),
        leaf("Copy Mode", copy_mode, last=True),
    ]
    return join_blocks(blocks)


def render_notif_drawdown_warning(
    *,
    daily_loss: float,
    limit: float,
) -> str:
    blocks = [
        title("⚠ Risk Alert"),
        leaf("Daily Loss", f"${daily_loss:,.0f} / ${limit:,.0f}"),
        leaf("Protection", "Auto pause nearing"),
        leaf("Recommendation", "Review exposure", last=True),
    ]
    return join_blocks(blocks)


def render_notif_auto_pause() -> str:
    blocks = [
        title("🛡 Safety Protection Activated"),
        leaf("Trigger", "Daily loss limit reached"),
        leaf("Auto Trade", STATUS_PAUSED),
        leaf("Open Positions", "Still monitored"),
        leaf("Action Needed", "Review settings", last=True),
    ]
    return join_blocks(blocks)


def render_notif_daily_summary(
    *,
    portfolio: float,
    today_pnl: float,
    trades: int,
    win_rate: int,
    best_trade_market: str,
    best_trade_pnl: float,
    bot_status: str = STATUS_RUNNING,
) -> str:
    blocks = [
        title("📅 Daily Summary"),
        leaf("Portfolio", f"${portfolio:,.2f}"),
        leaf("Today PnL", pnl(today_pnl)),
        leaf("Trades", f"{trades} completed"),
        leaf("Win Rate", f"{win_rate}%"),
        leaf("Best Trade", f"{best_trade_market} ({pnl(best_trade_pnl)})"),
        leaf("Bot Status", bot_status, last=True),
    ]
    return join_blocks(blocks)


# ────────────────────────────────────────────────────────────────────────────
# 17/18. Loading & Error states
# ────────────────────────────────────────────────────────────────────────────


def render_loading(message: str = "Fetching data...") -> str:
    return f"⏳ Loading\n{BAR}\n{LAST} {message}"


def render_syncing(message: str = "Updating portfolio data...") -> str:
    return f"🔄 Syncing\n{BAR}\n{LAST} {message}"


def render_error_api() -> str:
    blocks = [
        title("⚠ Temporary Issue"),
        leaf("Status", "Data unavailable"),
        leaf("Action", "Try refresh in a moment", last=True),
    ]
    return join_blocks(blocks)


def render_error_invalid_wallet() -> str:
    blocks = [
        title("⚠ Invalid Wallet Address"),
        leaf("Expected Format", "0x... wallet address"),
        leaf("Action", "Paste a valid address", last=True),
    ]
    return join_blocks(blocks)


def render_error_bot_paused() -> str:
    blocks = [
        title("⏸ Bot Paused"),
        leaf("New Trades", "Stopped"),
        leaf("Existing Positions", "Still monitored", last=True),
    ]
    return join_blocks(blocks)


def render_error_live_locked() -> str:
    blocks = [
        title("🔒 Live Mode Locked"),
        leaf("Status", "Not enabled"),
        leaf("Requirement", "Owner activation required", last=True),
    ]
    return join_blocks(blocks)


# ────────────────────────────────────────────────────────────────────────────
# Onboarding
# ────────────────────────────────────────────────────────────────────────────


def render_welcome(*, user_name: str = "trader") -> str:
    blocks = [
        title(f"👋 Welcome, {user_name}"),
        leaf("CrusaderBot", "Autonomous Polymarket trading"),
        leaf("Mode", PAPER),
        leaf("Next Step", "Initialize your wallet to begin", last=True),
    ]
    return join_blocks(blocks)


def render_wallet_ready(*, address_short: str) -> str:
    blocks = [
        title("🔑 Wallet Ready"),
        leaf("Address", address_short),
        leaf("Mode", PAPER),
        leaf("Next Step", "Choose a starter preset", last=True),
    ]
    return join_blocks(blocks)


def render_deposit_prompt() -> str:
    blocks = [
        title("💰 Fund Your Bot"),
        leaf("Mode", PAPER),
        leaf("Tip", "Paper Mode runs without real capital"),
        leaf("When ready", "Use Settings → Trading Mode for Live access", last=True),
    ]
    return join_blocks(blocks)
