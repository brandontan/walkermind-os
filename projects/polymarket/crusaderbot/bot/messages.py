"""Message template builders — Phase 5 UX Rebuild.

All financial blocks use <pre> tags for monospace rendering (parse_mode=HTML).
All external data is escaped via html.escape() before insertion.
"""
from __future__ import annotations

import html
from decimal import Decimal


def _signed(val: Decimal | float) -> str:
    v = float(val)
    sign = "+" if v >= 0 else ""
    return f"{sign}${v:,.2f}"


def _pct(val: Decimal | float) -> str:
    v = float(val)
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.2f}"


def _fmt(val: Decimal | float) -> str:
    return f"${float(val):,.2f}"


# ── Screen 01 — Welcome ────────────────────────────────────────────────────────

WELCOME_TEXT = (
    "<b>🛡️ Welcome to CrusaderBot</b>\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "Your autonomous Polymarket trading copilot.\n\n"
    "Here's how it works:\n"
    "1️⃣  We create a wallet for you\n"
    "2️⃣  You pick a trading preset\n"
    "3️⃣  Bot trades for you 24/7\n\n"
    "<blockquote>📋 Paper Mode\nSafe sandbox trading enabled.</blockquote>\n\n"
    "Ready to start?"
)

LEARN_MORE_TEXT = (
    "<b>ℹ️ About CrusaderBot</b>\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "<b>What is CrusaderBot?</b>\n"
    "An autonomous trading bot for Polymarket prediction markets. "
    "It scans markets 24/7, identifies opportunities, and executes trades "
    "based on your chosen strategy and risk settings.\n\n"
    "<b>Paper Mode</b>\n"
    "All new accounts start in paper (sandbox) mode with virtual capital. "
    "No real money is at risk until you explicitly activate live trading.\n\n"
    "<b>Presets</b>\n"
    "Choose from 5 curated trading styles ranging from conservative "
    "whale-mirroring to fully autonomous multi-strategy execution.\n\n"
    "<b>Safety</b>\n"
    "Hard-coded risk controls: max position 10%, daily loss limit $2,000, "
    "drawdown circuit-breaker at 8%, kill switch always available."
)


def wallet_ready_text(address: str) -> str:
    short = html.escape(address[:6] + "..." + address[-3:] if len(address) > 9 else address)
    return (
        "<b>✅ Your wallet is ready</b>\n\n"
        "<pre>Address: "
        + html.escape(address)
        + "</pre>\n\n"
        "This wallet receives USDC deposits\n"
        "on Polygon network."
    )


def deposit_prompt_text(address: str) -> str:
    short = html.escape(address[:6] + "..." + address[-3:] if len(address) > 9 else address)
    return (
        "<b>💰 Fund Your Wallet</b>\n\n"
        "Deposit USDC on Polygon to start live trading.\n"
        "Minimum: $50\n\n"
        "<pre>Your address: "
        + html.escape(address)
        + "</pre>"
    )


# ── Screen 02 — Dashboard ──────────────────────────────────────────────────────

def dashboard_text(
    balance: Decimal | float,
    positions_value: Decimal | float,
    total_equity: Decimal | float,
    wins: int,
    losses: int,
    pnl_today: Decimal | float,
    pnl_today_pct: Decimal | float,
    pnl_7d: Decimal | float,
    pnl_7d_pct: Decimal | float,
    pnl_30d: Decimal | float,
    pnl_30d_pct: Decimal | float,
    pnl_alltime: Decimal | float,
    total_trades: int,
    win_rate: Decimal | float,
    total_volume: Decimal | float,
    markets_count: int,
    autotrade_on: bool,
    preset_key: str | None,
    preset_emoji: str,
    preset_name: str,
    risk_emoji: str,
    risk_label: str,
) -> str:
    status_emoji = "🟢" if autotrade_on else "⚫"
    status_label = "RUNNING" if autotrade_on else "OFF"
    preset_display = f"{html.escape(preset_emoji)} {html.escape(preset_name)}" if preset_key else "Not configured"

    return (
        "<b>📊 CrusaderBot Dashboard</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<b>💼 Portfolio</b>\n"
        "<pre>"
        f"├─ Balance:        {_fmt(balance)}\n"
        f"├─ Positions:      {_fmt(positions_value)}\n"
        f"├─ Total Equity:   {_fmt(total_equity)}\n"
        f"└─ Winning: {wins} | Losing: {losses}"
        "</pre>\n\n"
        "<b>💰 Profit &amp; Loss</b>\n"
        "<pre>"
        f"├─ Today:    {_signed(pnl_today)} ({_pct(pnl_today_pct)}%)\n"
        f"├─ 7 Day:    {_signed(pnl_7d)} ({_pct(pnl_7d_pct)}%)\n"
        f"├─ 30 Day:   {_signed(pnl_30d)} ({_pct(pnl_30d_pct)}%)\n"
        f"└─ All-Time: {_signed(pnl_alltime)}"
        "</pre>\n\n"
        "<b>📈 Trading Stats</b>\n"
        "<pre>"
        f"├─ Total Trades:   {total_trades}\n"
        f"├─ Win Rate:       {float(win_rate):.1f}% ({wins}W / {losses}L)\n"
        f"├─ Total Volume:   {_fmt(total_volume)}\n"
        f"└─ Markets Traded: {markets_count}"
        "</pre>\n\n"
        "<b>🤖 Auto-Trade</b>\n"
        "<pre>"
        f"├─ Status: {status_emoji} {status_label}\n"
        f"├─ Preset: {html.escape(preset_emoji)} {html.escape(preset_name) if preset_key else 'Not configured'}\n"
        f"├─ Risk:   {html.escape(risk_emoji)} {html.escape(risk_label)}\n"
        f"└─ Mode:   📝 Paper"
        "</pre>"
    )


# ── Screen 03 — Preset Picker ──────────────────────────────────────────────────

PRESET_PICKER_TEXT = (
    "<b>🤖 Auto-Trade Presets</b>\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "Pick a trading style that fits you.\n"
    "Each preset bundles strategy + risk + sizing.\n\n"
    "<b>⭐ Recommended</b>\n\n"
    "<b>🐋 Whale Mirror</b>  🟢 Safe\n"
    "Follow proven Polymarket wallets with\n"
    "verified track records. Low effort,\n"
    "steady returns.\n\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "<b>📡 Signal Sniper</b>  🟢 Safe\n"
    "Auto-trade from curated signal feeds.\n"
    "Lower frequency, higher conviction.\n\n"
    "<b>🐋📡 Hybrid</b>  🟡 Balanced\n"
    "Whale Mirror + Signal combined.\n"
    "More opportunities, moderate risk.\n\n"
    "<b>🎯 Value Hunter</b>  🟡 Advanced\n"
    "Finds mispriced markets using edge model.\n"
    "Higher reward, requires patience.\n\n"
    "<b>🚀 Full Auto</b>  🔴 Aggressive\n"
    "All strategies active. Max exposure.\n"
    "For experienced traders only."
)


# ── Screen 04 — Preset Confirmation ───────────────────────────────────────────

def preset_confirm_text(
    preset_emoji: str,
    preset_name: str,
    strategy_label: str,
    risk_emoji: str,
    risk_label: str,
    capital_pct: int,
    tp_pct: int,
    sl_pct: int,
    max_pos_pct: int,
) -> str:
    return (
        "<b>🤖 Auto-Trade Setup</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<pre>"
        f"📋 Preset: {html.escape(preset_emoji)} {html.escape(preset_name)}\n"
        f"├─ Strategy:      {html.escape(strategy_label)}\n"
        f"├─ Risk:          {html.escape(risk_emoji)} {html.escape(risk_label)}\n"
        f"├─ Capital:       {capital_pct}%\n"
        f"├─ TP / SL:       +{tp_pct}% / -{sl_pct}%\n"
        f"├─ Max per trade: {max_pos_pct}%\n"
        f"└─ Mode:          📝 Paper"
        "</pre>\n\n"
        "<i>ℹ️ You can change these anytime\n"
        "   from the Auto-Trade menu.</i>"
    )


def preset_active_text(
    preset_emoji: str,
    preset_name: str,
    activated_date: str,
    trades_today: int,
    pnl_today: Decimal | float,
    strategy_label: str,
    risk_emoji: str,
    risk_label: str,
    capital_pct: int,
    tp_pct: int,
    sl_pct: int,
) -> str:
    return (
        "<b>🤖 Auto-Trade Status</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<pre>"
        f"📋 Active Preset: {html.escape(preset_emoji)} {html.escape(preset_name)}\n"
        f"├─ Status:        🟢 RUNNING\n"
        f"├─ Since:         {html.escape(activated_date)}\n"
        f"├─ Trades today:  {trades_today}\n"
        f"└─ P&L today:     {_signed(pnl_today)}"
        "</pre>\n\n"
        "<b>⚙️ Current Config</b>\n"
        "<pre>"
        f"├─ Strategy: {html.escape(strategy_label)}\n"
        f"├─ Risk:     {html.escape(risk_emoji)} {html.escape(risk_label)}\n"
        f"├─ Capital:  {capital_pct}%\n"
        f"├─ TP / SL:  +{tp_pct}% / -{sl_pct}%\n"
        f"└─ Mode:     📝 Paper"
        "</pre>"
    )


def preset_activated_success_text(preset_emoji: str, preset_name: str) -> str:
    return (
        f"<b>✅ Auto-Trade Activated</b>\n\n"
        f"Preset <b>{html.escape(preset_emoji)} {html.escape(preset_name)}</b> is now active.\n\n"
        "<blockquote>📝 Paper Mode — no real capital at risk.</blockquote>\n\n"
        "Returning to dashboard..."
    )


# ── Screen 05/06 — My Trades ───────────────────────────────────────────────────

def trades_empty_text() -> str:
    return (
        "<b>📈 My Trades</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "No open positions yet.\n\n"
        "Start your auto-trade preset to\n"
        "begin building your portfolio."
    )


def trades_text(
    open_positions: list[dict],
    recent_closed: list[dict],
) -> str:
    lines = [
        "<b>📈 My Trades</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"<b>📌 Open Positions ({len(open_positions)})</b>",
        "",
    ]

    for i, pos in enumerate(open_positions, 1):
        q = html.escape(pos.get("market_question", "Unknown market"))
        side = html.escape(pos.get("side", "YES"))
        entry = float(pos.get("entry_price", 0))
        size = float(pos.get("size_usdc", 0))
        current = float(pos.get("current_price", entry))
        pnl_pct = ((current - entry) / entry * 100) if entry else 0
        pos_id = pos.get("id", "")
        sign = "+" if pnl_pct >= 0 else ""
        lines.append(f"{i}️⃣ <b>{q}</b>")
        lines.append(
            f"<pre>├─ Side: {side} @ ${entry:.4f}\n"
            f"├─ Size: ${size:.2f}\n"
            f"└─ Current: ${current:.4f} ({sign}{pnl_pct:.1f}%)</pre>"
        )
        lines.append("")

    if recent_closed:
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("")
        lines.append("<b>📋 Recent Activity (last 5)</b>")
        for trade in recent_closed:
            q = html.escape(trade.get("market_question", "Unknown"))
            pnl = float(trade.get("pnl_usdc", 0))
            emoji = "✅" if pnl >= 0 else "❌"
            sign = "+" if pnl >= 0 else ""
            lines.append(f"{emoji} {q} → {sign}${pnl:.2f}")

    return "\n".join(lines)


def close_confirm_text(market_question: str, pnl: float, pnl_pct: float) -> str:
    sign = "+" if pnl >= 0 else ""
    return (
        "<b>⚠️ Close Position?</b>\n\n"
        f"<b>{html.escape(market_question)}</b>\n"
        f"Current P&amp;L: {sign}${pnl:.2f} ({sign}{pnl_pct:.1f}%)\n\n"
        "This will close at market price."
    )


# ── Wallet Screen ──────────────────────────────────────────────────────────────

def wallet_text(balance: Decimal | float, address: str) -> str:
    return (
        "<b>💰 Wallet</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<blockquote>📋 Paper Mode — sandbox balance</blockquote>\n\n"
        "<pre>"
        f"Balance:   {_fmt(balance)}\n"
        f"Address:   {html.escape(address[:6] + '...' + address[-4:] if len(address) > 10 else address)}"
        "</pre>\n\n"
        "Deposit USDC on Polygon to go live.\n"
        "Min deposit: $50"
    )


# ── Emergency Menu ─────────────────────────────────────────────────────────────

EMERGENCY_TEXT = (
    "<b>🚨 Emergency Controls</b>\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "⚠️ These actions take effect immediately."
)

EMERGENCY_CONFIRM_TEXTS: dict[str, tuple[str, str]] = {
    "pause": (
        "⏸ Pause Auto-Trade",
        "Stops all new trade entries immediately.\nOpen positions are kept as-is.",
    ),
    "pause_close": (
        "⏸🛑 Pause + Close All",
        "Stops trading AND closes every open position at market price.\nThis cannot be undone.",
    ),
    "lock": (
        "🔒 Lock Account",
        "Freezes all trading and account actions.\nRequires admin support to unlock.",
    ),
}


def emergency_confirm_text(action: str) -> str:
    name, desc = EMERGENCY_CONFIRM_TEXTS.get(action, ("Unknown Action", ""))
    return (
        f"<b>⚠️ Confirm: {html.escape(name)}?</b>\n\n"
        f"{html.escape(desc)}"
    )


def emergency_feedback_text(action: str) -> str:
    labels = {
        "pause": "✅ Auto-trade paused. No new trades will be entered.",
        "pause_close": "✅ Auto-trade paused and all positions queued for close.",
        "lock": "🔒 Account locked. Contact support to unlock.",
    }
    return labels.get(action, "✅ Action completed.")
