"""MVP v1 Telegram message renderers (flat Markdown format).

Every screen defined in docs/ux/telegram-mvp-v1.md has one render_* function
here. Renderers are pure: they take primitives, return strings. No I/O, no
DB calls. Handlers fetch data, call these renderers, and send the result.
"""
from __future__ import annotations

from typing import Iterable, Sequence

from .ui.tree import (
    CARD_DIVIDER,
    DIVIDER,
    LIVE,
    LOCKED,
    PAPER,
    STATUS_NOT_SET,
    STATUS_PAUSED,
    STATUS_RUNNING,
    STATUS_STOPPED,
    STATUS_SYNCING,
    cta,
    divider,
    join_blocks,
    leaf,
    md_escape,
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
    return (
        f"*🏠 Dashboard*\n\n"
        f"🤖 Bot Status  ·  {md_escape(bot_status)}\n"
        f"{DIVIDER}\n"
        f"*💹 Today*\n"
        f"  PnL  ·  {pnl(today_pnl)}\n"
        f"  Trades  ·  {today_trades}\n"
        f"{DIVIDER}\n"
        f"🔄 Auto Trade  »  {md_escape(active_strategy)}\n"
        f"👥 Copy Wallet  »  {copy_wallets_active} Active\n"
        f"💼 Portfolio  »  ${portfolio_value:,.2f}"
    )


def render_dashboard_new_user() -> str:
    return (
        f"*🏠 Dashboard*\n\n"
        f"👋 Welcome  ·  Not configured yet\n"
        f"{divider()}\n"
        f"🤖 Auto Trade  »  {STATUS_NOT_SET}\n"
        f"👥 Copy Wallet  »  {STATUS_NOT_SET}\n"
        f"\n{cta('Tap Setup Auto to get started')}"
    )


def render_dashboard_paused(*, reason: str = "Manual Pause", today_pnl: float = 0.0) -> str:
    return join_blocks([
        title("🏠 Dashboard"),
        section("🤖 Bot Status", [
            ("State", STATUS_PAUSED),
            ("Reason", reason),
        ]),
        leaf("💹 Today", pnl(today_pnl)),
        cta("Resume trading to continue"),
    ])


def render_dashboard_risk_alert(*, message: str = "Daily drawdown nearing limit") -> str:
    return join_blocks([
        title("🏠 Dashboard"),
        leaf("⚠ Risk Alert", message),
        leaf("🤖 Bot Protection", "Auto pause may trigger"),
        leaf("💼 Portfolio", "Review open positions"),
        cta("Adjust risk settings"),
    ])


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
    config = section("⚙️ Configuration", [
        ("Capital", f"${capital:,.0f}"),
        ("Risk", risk),
        ("Mode", mode),
    ])
    perf = section("📊 Performance", [
        ("PnL Today", pnl(pnl_today)),
        ("Executions", str(executions)),
        ("Win Rate", f"{win_rate}%"),
    ])
    return (
        f"*🤖 Auto Trade*\n\n"
        f"{leaf('Status', status)}\n"
        f"{leaf('Active Strategy', strategy)}\n"
        f"{divider()}\n"
        f"{config}\n"
        f"{divider()}\n"
        f"{perf}\n\n"
        f"{cta('Choose an action:')}"
    )


def render_autotrade_quick_start(
    *,
    strategy: str = "⚡ Momentum",
    risk: str = "🟡 Balanced",
    capital: float = 100.0,
    mode: str = PAPER,
) -> str:
    return join_blocks([
        title("🚀 Quick Start"),
        section("Recommended Setup", [
            ("🧠 Strategy", strategy),
            ("⚖️ Risk", risk),
            ("💰 Capital", f"${capital:,.0f}"),
            ("📝 Mode", mode),
        ]),
        cta("Ready to begin?"),
    ])


def render_autotrade_configure_strategy() -> str:
    return join_blocks([
        title("🤖 Auto Trade / Configure / Strategy"),
        nested("Choose a Strategy", [
            "⚡ Momentum — Fast trend following",
            "📊 Mean Reversion — Buy pullbacks",
            "🧪 Smart Hybrid — Mixed adaptive mode",
        ]),
        cta("Select a strategy:"),
    ])


def render_autotrade_configure_capital(current: float = 100.0) -> str:
    return join_blocks([
        title("🤖 Auto Trade / Configure / Capital"),
        leaf("Current Allocation", f"${current:,.0f}"),
        cta("Choose allocation:"),
    ])


def render_autotrade_configure_risk() -> str:
    return join_blocks([
        title("🤖 Auto Trade / Configure / Risk"),
        nested("Choose a Risk Level", [
            "🟢 Safe — Lower risk • fewer trades",
            "🟡 Balanced — Recommended",
            "🔴 Aggressive — Higher volatility",
        ]),
        cta("Select a risk level:"),
    ])


def render_autotrade_configure_review(
    *,
    strategy: str,
    capital: float,
    risk: str,
    mode: str = PAPER,
) -> str:
    return join_blocks([
        title("🤖 Auto Trade / Configure / Review"),
        section("Your Setup", [
            ("🧠 Strategy", strategy),
            ("💰 Capital", f"${capital:,.0f}"),
            ("⚖️ Risk", risk),
            ("📝 Mode", mode),
        ]),
        cta("Looks good?"),
    ])


def render_autotrade_strategy_status(
    *,
    strategy: str,
    status: str,
    capital: float,
    pnl_today: float,
    trades: int,
) -> str:
    return join_blocks([
        title("📊 Strategy Status"),
        section("Strategy", [
            ("Name", strategy),
            ("Status", status),
            ("Capital", f"${capital:,.0f}"),
            ("PnL Today", pnl(pnl_today)),
            ("Trades", str(trades)),
        ]),
        cta("Select an action:"),
    ])


def render_autotrade_pause_confirm() -> str:
    return join_blocks([
        title("⏸ Pause Auto Trade"),
        section("Effect", [
            ("New trades", "Stopped"),
            ("Open positions", "Remain active"),
        ]),
        cta("Confirm pause?"),
    ])


def render_autotrade_resume_confirm() -> str:
    return join_blocks([
        title("▶ Resume Auto Trade"),
        section("Effect", [
            ("Market monitoring", "Resumed"),
            ("Trade execution", "Enabled"),
        ]),
        cta("Continue trading?"),
    ])


# ────────────────────────────────────────────────────────────────────────────
# 10. Copy Wallet
# ────────────────────────────────────────────────────────────────────────────


def render_copy_home(
    *,
    status: str = STATUS_NOT_SET,
    active_wallets: int = 0,
    allocation: float = 0.0,
) -> str:
    return join_blocks([
        title("👥 Copy Wallet"),
        leaf("Status", status),
        leaf("Active Wallets", f"{active_wallets} Following"),
        leaf("Allocation", f"${allocation:,.0f}"),
        cta("Choose an action:"),
    ])


def render_copy_add_wallet_prompt() -> str:
    return join_blocks([
        title("➕ Add Wallet"),
        cta("Paste the wallet address to copy:"),
    ])


def render_copy_wallet_review(
    *,
    address_short: str,
    activity: str = STATUS_RUNNING,
    recent_trades: int = 0,
    risk: str = "🟡 Moderate",
) -> str:
    return join_blocks([
        title("👥 Wallet Review"),
        section("Wallet Info", [
            ("Address", address_short),
            ("Activity", activity),
            ("Recent Trades", str(recent_trades)),
            ("Risk", risk),
        ]),
        cta("Add this wallet?"),
    ])


def render_copy_wallet_configure(
    *,
    address_short: str,
    allocation: float,
    risk: str,
    copy_mode: str = "Mirror Trades",
) -> str:
    return join_blocks([
        title("⚙️ Wallet Configuration"),
        section("Configure", [
            ("Wallet", address_short),
            ("Allocation", f"${allocation:,.0f}"),
            ("Risk", risk),
            ("Copy Mode", copy_mode),
        ]),
        cta("Confirm settings?"),
    ])


def render_copy_active_wallets_empty() -> str:
    return join_blocks([
        title("👛 Active Wallets"),
        leaf("Status", "No wallets added"),
        leaf("Next Step", "Add a wallet address to start copying"),
    ])


def render_copy_wallet_card(
    *,
    index: int,
    address_short: str,
    status: str,
    allocation: float,
    pnl_today: float,
    trades_copied: int,
) -> str:
    card_section = section(f"Wallet #{index}", [
        ("Address", address_short),
        ("Status", status),
        ("Allocation", f"${allocation:,.0f}"),
        ("PnL Today", pnl(pnl_today)),
        ("Trades Copied", str(trades_copied)),
    ])
    return (
        f"*👛 Active Wallets*\n\n"
        f"{CARD_DIVIDER}\n"
        f"{card_section}\n\n"
        f"{cta('Select an action:')}"
    )


def render_copy_pause_confirm() -> str:
    return join_blocks([
        title("⏸ Pause Copy Wallet"),
        section("Effect", [
            ("New copied trades", "Stopped"),
            ("Existing positions", "Stay active"),
        ]),
        cta("Confirm pause?"),
    ])


# ────────────────────────────────────────────────────────────────────────────
# 11. Markets
# ────────────────────────────────────────────────────────────────────────────


def render_markets_home() -> str:
    return join_blocks([
        title("📈 Markets"),
        section("Browse", [
            ("🔥 Trending", "Most active markets"),
            ("🆕 New Markets", "Fresh opportunities"),
            ("🧠 AI Insights", "High-confidence setups"),
            ("⭐ Watchlist", "Saved markets"),
            ("🔎 Search", "Find any market"),
        ]),
        cta("Choose a view:"),
    ])


def render_markets_trending(items: Sequence[dict]) -> str:
    """items: [{rank, title, yes, no, volume, sentiment}, ...]"""
    lines: list[str] = [title("🔥 Trending Markets"), ""]
    for it in items:
        rank = str(it.get("rank", "")).strip()
        market_title = str(it.get("title", "")).replace("\n", " ").strip()
        label = f"{rank} {market_title}".strip()
        yes_val = md_escape(str(it.get("yes", "—")))
        no_val = md_escape(str(it.get("no", "—")))
        vol = md_escape(str(it.get("volume", "—")))
        sent = md_escape(str(it.get("sentiment", "—")))
        lines.append(CARD_DIVIDER)
        lines.append(f"*{md_escape(label)}*")
        lines.append(f"  Price  ·  YES {yes_val}¢ • NO {no_val}¢")
        lines.append(f"  Volume  ·  {vol}")
        lines.append(f"  Sentiment  ·  {sent}")
    lines.append(CARD_DIVIDER)
    lines.append(cta("Select a market:"))
    return "\n".join(lines)


def render_markets_detail(
    *,
    market_title: str,
    yes_price: str,
    no_price: str,
    sentiment: str,
    ai_confidence: str,
    bot_exposure: str = "No active position",
) -> str:
    return join_blocks([
        title("📊 Market Details"),
        leaf("Market", market_title),
        section("Market Price", [
            ("YES", f"{yes_price}¢"),
            ("NO", f"{no_price}¢"),
        ]),
        leaf("Sentiment", sentiment),
        leaf("AI Confidence", ai_confidence),
        leaf("Bot Exposure", bot_exposure),
        cta("Monitor • Watch • Auto"),
    ])


def render_markets_ai_insight(
    *,
    market_title: str,
    confidence: str,
    reason: str,
    bot_exposure: str = "No active position",
) -> str:
    return join_blocks([
        title("🧠 AI Insights"),
        leaf("Market", market_title),
        leaf("Confidence", confidence),
        leaf("Bot Exposure", bot_exposure),
        nested("Analysis", [reason]),
    ])


def render_markets_search_prompt() -> str:
    return join_blocks([
        title("🔎 Search Markets"),
        cta("Type a keyword — e.g. BTC, Trump, ETH"),
    ])


def render_watchlist_empty() -> str:
    return join_blocks([
        title("⭐ Watchlist"),
        leaf("Status", "No markets saved"),
        leaf("Tip", "Add markets from AI Insights or Trending"),
        cta("Browse markets to add:"),
    ])


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
    today_section = section("💹 Today", [
        ("PnL", pnl(today_pnl)),
        ("Trades", str(today_trades)),
        ("Win Rate", f"{today_win_rate}%"),
    ])
    return (
        f"*💼 Portfolio*\n\n"
        f"{leaf('💰 Balance', f'${balance:,.2f}')}\n"
        f"{divider()}\n"
        f"{today_section}\n"
        f"{divider()}\n"
        f"{leaf('📌 Open Positions', f'{open_positions} Active')}\n\n"
        f"{cta('Choose an action:')}"
    )


def render_positions_empty() -> str:
    return join_blocks([
        title("📌 Open Positions"),
        leaf("Status", "No active positions"),
        cta("Your bot will trade when opportunities appear"),
    ])


def render_positions_list(
    items: Sequence[dict],
    *,
    page: int = 1,
    total_pages: int = 1,
    total: int = 0,
) -> str:
    """Paginated card list for open positions.

    items: [{rank, title, side, pnl}, ...]
    """
    header = f"*📌 Open Positions*  ·  {total} active"
    cards: list[str] = []
    for it in items:
        rank = str(it.get("rank", "")).strip()
        market_title = str(it.get("title", "")).replace("\n", " ").strip()
        label = f"{rank} {md_escape(market_title)}".strip()
        card = (
            f"{CARD_DIVIDER}\n"
            f"*{label}*\n"
            f"  Side  ·  {md_escape(str(it.get('side', '—')))}\n"
            f"  PnL   ·  {pnl(float(it.get('pnl', 0.0)))}"
        )
        cards.append(card)
    footer = f"{CARD_DIVIDER}\n_{page} of {total_pages}_"
    return "\n".join([header, ""] + cards + [footer])


def render_position_detail(
    *,
    market_title: str,
    side: str,
    entry: str,
    current: str,
    pnl_value: float,
    status: str = STATUS_RUNNING.replace("Running", "Open"),
) -> str:
    return join_blocks([
        title("📌 Position Details"),
        leaf("Market", market_title),
        CARD_DIVIDER,
        section("Details", [
            ("Side", side),
            ("Entry", f"{entry}¢"),
            ("Current", f"{current}¢"),
            ("PnL", pnl(pnl_value)),
            ("Status", status),
        ]),
        cta("Choose an action:"),
    ])


def render_history_empty() -> str:
    return join_blocks([
        title("📜 Trade History"),
        leaf("Status", "No trades yet"),
        cta("Start automation to build history"),
    ])


def render_history_home(*, today: int = 0, week: int = 0) -> str:
    return join_blocks([
        title("📜 Trade History"),
        section("Summary", [
            ("Today", f"{today} Trades"),
            ("This Week", f"{week} Trades"),
        ]),
        cta("Choose range:"),
    ])


def render_performance(
    *,
    today_pnl: float = 0.0,
    week_pnl: float = 0.0,
    win_rate: int = 0,
    trades: int = 0,
) -> str:
    return join_blocks([
        title("💹 Performance"),
        section("Results", [
            ("Today", pnl(today_pnl)),
            ("7 Days", pnl(week_pnl)),
            ("Win Rate", f"{win_rate}%"),
            ("Trades", str(trades)),
        ]),
    ])


def render_balance(
    *,
    available: float = 0.0,
    allocated: float = 0.0,
) -> str:
    free = max(available - allocated, 0.0)
    return join_blocks([
        title("💰 Balance"),
        section("Funds", [
            ("Available", f"${available:,.2f}"),
            ("Allocated", f"${allocated:,.2f}"),
            ("Free Capital", f"${free:,.2f}"),
        ]),
    ])


# ────────────────────────────────────────────────────────────────────────────
# 13. Settings
# ────────────────────────────────────────────────────────────────────────────


def render_settings_home(*, trading_mode: str = PAPER) -> str:
    return join_blocks([
        title("⚙️ Settings"),
        leaf("🔄 Trading Mode", trading_mode),
        leaf("🛡 Risk", "Daily limits ON"),
        leaf("🔔 Alerts", "Trade alerts ON"),
        leaf("👥 Copy Wallet", "Mirroring"),
        leaf("👤 Account", "Profile"),
        leaf("🧪 Advanced", "Power user"),
    ])


def render_settings_trading_mode(*, current: str = PAPER) -> str:
    return join_blocks([
        title("🔄 Trading Mode"),
        leaf("Current Mode", current),
        section("Options", [
            ("📝 Paper Mode", "Safe simulation"),
            ("💸 Live Mode", "Real capital execution"),
        ]),
    ])


def render_settings_live_gate() -> str:
    return join_blocks([
        title("⚠ Live Trading"),
        leaf("Status", f"{LOCKED} Disabled"),
        nested("Activation Requirements", [
            "Manual owner confirmation",
            "Risk controls verified",
            "Paper mode tested first",
        ]),
        cta("Use Paper Mode until ready"),
    ])


def render_settings_risk_controls(
    *,
    daily_loss_limit: float = 20.0,
    max_position_pct: int = 10,
    max_concurrent: int = 3,
    auto_pause_enabled: bool = True,
) -> str:
    auto_pause = "🟢 Enabled" if auto_pause_enabled else "🔴 Disabled"
    return join_blocks([
        title("🛡 Risk Controls"),
        section("Limits", [
            ("Daily Loss Limit", f"${daily_loss_limit:,.0f}"),
            ("Max Position Size", f"{max_position_pct}%"),
            ("Concurrent Trades", f"{max_concurrent} Max"),
            ("Auto Pause", auto_pause),
        ]),
    ])


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
    return join_blocks([
        title("🔔 Notifications"),
        section("Events", [
            ("Trade Opened", on if trade_opened else off),
            ("Trade Closed", on if trade_closed else off),
            ("Risk Alerts", on if risk_alerts else off),
            ("Daily Summary", on if daily_summary else off),
            ("Market Alerts", on if market_alerts else off),
        ]),
    ])


def render_settings_account(
    *,
    wallet_status: str = "Connected",
    mode: str = PAPER,
    api_status: str = STATUS_RUNNING.replace("Running", "Healthy"),
    subscription: str = "MVP",
) -> str:
    return join_blocks([
        title("👤 Account"),
        section("Details", [
            ("Wallet", wallet_status),
            ("Mode", mode),
            ("API Status", api_status),
            ("Subscription", subscription),
        ]),
    ])


def render_settings_advanced(*, debug_enabled: bool = False) -> str:
    debug = "🟢 Enabled" if debug_enabled else "🔴 Disabled"
    return join_blocks([
        title("🧪 Advanced"),
        section("Developer", [
            ("Strategy Logs", "View execution logs"),
            ("Debug Mode", debug),
            ("Data Refresh", "Real-time"),
            ("System Health", "🟢 Operational"),
        ]),
    ])


# ────────────────────────────────────────────────────────────────────────────
# 14. Help & Onboarding
# ────────────────────────────────────────────────────────────────────────────


def render_help_home() -> str:
    return join_blocks([
        title("❓ Help"),
        nested("Topics", [
            "🚀 Quick Start Guide",
            "🤖 How Auto Trade Works",
            "👥 How Copy Wallet Works",
            "🛡 Risk & Safety",
            "💬 FAQ",
            "🆘 Support",
        ]),
        cta("Choose a topic:"),
    ])


def render_help_quick_start_guide() -> str:
    return join_blocks([
        title("🚀 Quick Start Guide"),
        nested("Steps", [
            "Configure Auto Trade",
            "Choose risk & capital",
            "Start in Paper Mode",
            "Monitor performance",
        ]),
        leaf("Recommendation", "Use Paper Mode first"),
    ])


def render_help_how_auto_trade() -> str:
    return join_blocks([
        title("🤖 How Auto Trade Works"),
        leaf("Purpose", "Bot trades automatically"),
        leaf("Decision Engine", "Strategy-based execution"),
        nested("You Control", ["💰 Capital", "⚖️ Risk", "🧠 Strategy"]),
        leaf("Bot Controls", "Market execution"),
        leaf("Safety", "Risk protections enabled"),
    ])


def render_help_how_copy_wallet() -> str:
    return join_blocks([
        title("👥 How Copy Wallet Works"),
        leaf("Purpose", "Mirror target wallet activity"),
        leaf("What Happens", "Trades may be copied automatically"),
        nested("You Control", ["💰 Allocation", "⚖️ Risk", "Wallet selection"]),
        leaf("Important", "Past performance ≠ future results"),
        leaf("Recommendation", "Start small"),
    ])


def render_help_safety() -> str:
    return join_blocks([
        title("🛡 Risk & Safety"),
        nested("Protections", [
            "Paper Mode — Practice without real funds",
            "Daily Loss Limit — Auto stop protection",
            "Auto Pause — Risk circuit breaker",
        ]),
        nested("Warnings", [
            "Copy Wallet — Past performance ≠ future results",
            "Never risk more than you can afford",
        ]),
    ])


def render_help_faq() -> str:
    return join_blocks([
        title("💬 FAQ"),
        nested("Questions", [
            "🤖 Is trading automatic?",
            "📝 What is Paper Mode?",
            "💸 Can I lose money?",
            "👥 How does Copy Wallet work?",
            "🔒 Is my wallet safe?",
        ]),
    ])


def render_help_support() -> str:
    return join_blocks([
        title("🆘 Support"),
        leaf("Help Center", "Common troubleshooting"),
        leaf("Report Issue", "Found a problem?"),
        leaf("Status", "🟢 Systems Operational"),
    ])


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
    return join_blocks([
        title("🤖 Auto Trade Started"),
        leaf("Strategy", strategy),
        leaf("Capital", f"${capital:,.0f}"),
        leaf("Risk", risk),
        leaf("Status", status),
    ])


def render_notif_bot_waiting() -> str:
    return join_blocks([
        title("🤖 Auto Trade Started"),
        leaf("Status", STATUS_RUNNING),
        leaf("What happens next", "Bot monitors opportunities automatically"),
        leaf("Note", "First trade may take time"),
    ])


def render_notif_trade_opened(
    *,
    market_title: str,
    side: str,
    strategy: str,
    entry: str,
    size: float,
    reason: str = "High confidence setup",
) -> str:
    return join_blocks([
        title("📈 Trade Opened"),
        leaf("Market", market_title),
        leaf("Position", side),
        leaf("Strategy", strategy),
        leaf("Entry", f"{entry}¢"),
        leaf("Size", f"${size:,.0f}"),
        leaf("Reason", reason),
    ])


def render_notif_first_trade(market_title: str) -> str:
    return join_blocks([
        title("🎉 First Trade Opened"),
        leaf("Nice start", "Your bot placed its first trade"),
        leaf("Market", market_title),
        leaf("Status", "Monitoring performance"),
    ])


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
    return join_blocks([
        title(head),
        leaf("Market", market_title),
        leaf("Result", pnl(result_pnl)),
        leaf("Exit Reason", exit_reason),
        leaf(last_label, last_value),
    ])


def render_notif_wallet_copied(
    *,
    address_short: str,
    market_title: str,
    side: str,
    size: float,
    copy_mode: str = "Proportional",
) -> str:
    return join_blocks([
        title("👥 Wallet Trade Copied"),
        leaf("Wallet", address_short),
        leaf("Market", market_title),
        leaf("Position", side),
        leaf("Size", f"${size:,.0f}"),
        leaf("Copy Mode", copy_mode),
    ])


def render_notif_drawdown_warning(
    *,
    daily_loss: float,
    limit: float,
) -> str:
    return join_blocks([
        title("⚠ Risk Alert"),
        leaf("Daily Loss", f"${daily_loss:,.0f} / ${limit:,.0f}"),
        leaf("Protection", "Auto pause nearing"),
        leaf("Recommendation", "Review exposure"),
    ])


def render_notif_auto_pause() -> str:
    return join_blocks([
        title("🛡 Safety Protection Activated"),
        leaf("Trigger", "Daily loss limit reached"),
        leaf("Auto Trade", STATUS_PAUSED),
        leaf("Open Positions", "Still monitored"),
        leaf("Action Needed", "Review settings"),
    ])


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
    return join_blocks([
        title("📅 Daily Summary"),
        leaf("Portfolio", f"${portfolio:,.2f}"),
        leaf("Today PnL", pnl(today_pnl)),
        leaf("Trades", f"{trades} completed"),
        leaf("Win Rate", f"{win_rate}%"),
        leaf("Best Trade", f"{best_trade_market} ({pnl(best_trade_pnl)})"),
        leaf("Bot Status", bot_status),
    ])


# ────────────────────────────────────────────────────────────────────────────
# 17/18. Loading & Error states
# ────────────────────────────────────────────────────────────────────────────


def render_loading(message: str = "Fetching data...") -> str:
    return join_blocks([title("⏳ Loading"), cta(message)])


def render_syncing(message: str = "Updating portfolio data...") -> str:
    return join_blocks([title("🔄 Syncing"), leaf("Status", message)])


def render_error_api() -> str:
    return join_blocks([
        title("⚠ Temporary Issue"),
        leaf("Status", "Data unavailable"),
        leaf("Action", "Try refresh in a moment"),
    ])


def render_error_invalid_wallet() -> str:
    return join_blocks([
        title("⚠ Invalid Wallet Address"),
        leaf("Expected Format", "0x... wallet address"),
        leaf("Action", "Paste a valid address"),
    ])


def render_error_bot_paused() -> str:
    return join_blocks([
        title("⏸ Bot Paused"),
        leaf("New Trades", "Stopped"),
        leaf("Existing Positions", "Still monitored"),
    ])


def render_error_live_locked() -> str:
    return join_blocks([
        title("🔒 Live Mode Locked"),
        leaf("Status", "Not enabled"),
        leaf("Requirement", "Owner activation required"),
    ])


# ────────────────────────────────────────────────────────────────────────────
# Onboarding
# ────────────────────────────────────────────────────────────────────────────


def render_welcome(*, user_name: str = "trader") -> str:
    return join_blocks([
        title(f"👋 Welcome, {user_name}"),
        leaf("Mode", PAPER),
        nested("Get Started", [
            "Initialize your wallet",
            "Choose a strategy preset",
            "Start in Paper Mode",
        ]),
        cta("Initialize your wallet to begin"),
    ])


def render_wallet_ready(*, address_short: str) -> str:
    return join_blocks([
        title("🔑 Wallet Ready"),
        leaf("Address", address_short),
        leaf("Mode", PAPER),
        cta("Choose a starter preset:"),
    ])


def render_deposit_prompt() -> str:
    return join_blocks([
        title("💰 Fund Your Bot"),
        leaf("Mode", PAPER),
        leaf("Tip", "Paper Mode runs without real capital"),
        leaf("When ready", "Use Settings → Trading Mode for Live access"),
    ])
