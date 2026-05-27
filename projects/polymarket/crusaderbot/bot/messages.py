"""Message template builders — Tactical Terminal v3.3 (MarkdownV2).

Financial blocks use code fences (```) for monospace rendering.
Dynamic content is escaped via md_v2_escape(); static strings are pre-escaped.
"""
from __future__ import annotations

from decimal import Decimal

from .ui.tree import md_v2_escape as _md


# ── Tactical Terminal palette ─────────────────────────────────────────────────
# Unified emoji set — every new message MUST use these constants instead of
# inlining glyphs. Existing templates still inline emoji and will be migrated
# as their handlers are touched.
EMOJI: dict[str, str] = {
    "ok":       "✅",
    "err":      "❌",
    "warn":     "⚠️",
    "info":     "ℹ️",
    "signal":   "📡",
    "position": "📊",
    "money":    "💰",
    "alert":    "🚨",
    "shield":   "🛡️",
    "tp":       "🎯",
    "sl":       "🛑",
    "robot":    "🤖",
    "lock":     "🔒",
    "fire":     "🔥",
    "spark":    "✨",
    "chart":    "📈",
    "down":     "📉",
}

# Heavy horizontal divider — width chosen to fit Telegram's mobile column.
DIV = "━" * 32


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


def _table(rows: list[tuple[str, str]], width: int = 14) -> str:
    """Right-pad keys to `width` for a code-fence block.

    Content is NOT MD2-escaped — code fences render literally.
    Returns the inside of a ``` block (no surrounding backticks).
    """
    lines = []
    for key, val in rows:
        lines.append(f"{key.ljust(width)}{val}")
    return "\n".join(lines)


def _pre(content: str) -> str:
    return f"```\n{content}\n```"


# ── Tactical Terminal alert templates (new) ──────────────────────────────────
#
# Seven canonical alert events for the bot polish pass. Each renders an
# HTML-escaped block with a heavy divider, emoji indicator, and aligned
# <pre> table for numeric data.

def signal_alert_text(
    market_question: str,
    side: str,
    price: float,
    edge_bps: int,
    source: str = "edge_finder",
) -> str:
    return (
        f"*{EMOJI['signal']} Signal · {_md(source).upper()}*\n"
        f"{DIV}\n\n"
        f"*{_md(market_question)}*\n\n"
        + _pre(_table(
            [
                ("Side:",  side.upper()),
                ("Price:", f"{price * 100:.1f}¢"),
                ("Edge:",  f"+{edge_bps} bps"),
            ]
        ))
    )


def position_open_text(
    market_question: str,
    side: str,
    entry_price: float,
    size_usdc: float,
    tp_pct: float,
    sl_pct: float,
) -> str:
    return (
        f"*{EMOJI['position']} Position Opened*\n"
        f"{DIV}\n\n"
        f"*{_md(market_question)}*\n\n"
        + _pre(_table(
            [
                ("Side:",   side.upper()),
                ("Entry:",  f"{entry_price * 100:.1f}¢"),
                ("Size:",   _fmt(size_usdc)),
                ("TP:",     f"+{tp_pct:.1f}%"),
                ("SL:",     f"−{sl_pct:.1f}%"),
            ]
        ))
    )


def position_close_text(
    market_question: str,
    reason: str,  # "tp" | "sl" | "force" | "manual" | "expired"
    entry_price: float,
    exit_price: float,
    pnl_usdc: float,
    pnl_pct: float,
) -> str:
    reason_label = {
        "tp":      f"{EMOJI['tp']} Take Profit",
        "sl":      f"{EMOJI['sl']} Stop Loss",
        "force":   f"{EMOJI['alert']} Force Close",
        "manual":  f"{EMOJI['ok']} Manual Close",
        "expired": f"{EMOJI['info']} Expired",
    }.get(reason, f"{EMOJI['info']} Closed")
    return (
        f"*{reason_label}*\n"
        f"{DIV}\n\n"
        f"*{_md(market_question)}*\n\n"
        + _pre(_table(
            [
                ("Entry:", f"{entry_price * 100:.1f}¢"),
                ("Exit:",  f"{exit_price * 100:.1f}¢"),
                ("P&L:",   _signed(pnl_usdc)),
                ("%:",     f"{_pct(pnl_pct)}%"),
            ]
        ))
    )


def daily_summary_text(
    date_label: str,
    trades: int,
    wins: int,
    losses: int,
    pnl_usdc: float,
    pnl_pct: float,
    equity_usdc: float,
) -> str:
    win_rate = (wins / trades * 100.0) if trades else 0.0
    return (
        f"*{EMOJI['chart']} Daily Summary · {_md(date_label)}*\n"
        f"{DIV}\n\n"
        + _pre(_table(
            [
                ("Trades:",   str(trades)),
                ("Wins/Loss:", f"{wins}W / {losses}L"),
                ("Win Rate:",  f"{win_rate:.1f}%"),
                ("P&L:",       _signed(pnl_usdc)),
                ("%:",         f"{_pct(pnl_pct)}%"),
                ("Equity:",    _fmt(equity_usdc)),
            ]
        ))
    )


def health_alert_text(
    component: str,
    severity: str,  # "ok" | "warn" | "err"
    detail: str | None = None,
) -> str:
    severity_emoji = EMOJI.get(severity, EMOJI["info"])
    body = (
        f"*{severity_emoji} Health · {_md(component)}*\n"
        f"{DIV}\n\n"
        f"Status: *{_md(severity.upper())}*"
    )
    if detail:
        body += f"\n\n{_md(detail)}"
    return body



# ── Concierge Onboarding (8-step wizard) ─────────────────────────────────────

def onboard_welcome_text() -> str:
    return (
        "🏛️ *𝗖𝗥𝗨𝗦𝗔𝗗𝗘𝗥 \\| 𝗔𝗨𝗧𝗢𝗕𝗢𝗧*\n"
        + DIV + "\n\n"
        "*Step 1 of 8 — Welcome*\n\n"
        "Your autonomous Polymarket trading copilot\.\n\n"
        "> 📋 Paper Mode — safe sandbox, no real capital at risk\.\n\n"
        "Tap below to begin your 8\\-step setup\."
    )


def onboard_how_it_works_text() -> str:
    return (
        "🏛️ *𝗖𝗥𝗨𝗦𝗔𝗗𝗘𝗥 \\| 𝗔𝗨𝗧𝗢𝗕𝗢𝗧*\n"
        + DIV + "\n\n"
        "*Step 2 of 8 — How It Works*\n\n"
        "1️⃣  *Wallet* — a deposit address is created for you\n"
        "2️⃣  *Strategy* — you pick a risk profile and preset\n"
        "3️⃣  *Auto\\-Trade* — the bot scans and trades 24/7\n\n"
        "All new accounts start with $1,000 virtual USDC in paper mode\.\n"
        "No real funds are used until you explicitly go live\."
    )


def onboard_wallet_text(address: str) -> str:
    return (
        "🏛️ *𝗖𝗥𝗨𝗦𝗔𝗗𝗘𝗥 \\| 𝗔𝗨𝗧𝗢𝗕𝗢𝗧*\n"
        + DIV + "\n\n"
        "*Step 3 of 8 — Your Wallet*\n\n"
        "✅ Wallet created\. Your deposit address:\n\n"
        f"`{address}`\n\n"
        "This address accepts USDC on Polygon\.\n"
        "Minimum deposit to go live: $50"
    )


def onboard_paper_credit_text() -> str:
    return (
        "🏛️ *𝗖𝗥𝗨𝗦𝗔𝗗𝗘𝗥 \\| 𝗔𝗨𝗧𝗢𝗕𝗢𝗧*\n"
        + DIV + "\n\n"
        "*Step 4 of 8 — Paper Credit*\n\n"
        + _pre(_table([
            ("Balance:", "$1,000.00 USDC"),
            ("Mode:",    "Paper (Safe)"),
        ], width=9))
        + "\n\n"
        "✅ $1,000 virtual USDC has been credited to your account\.\n"
        "All trades are simulated — zero financial risk\."
    )


def onboard_risk_text() -> str:
    return (
        "🏛️ *𝗖𝗥𝗨𝗦𝗔𝗗𝗘𝗥 \\| 𝗔𝗨𝗧𝗢𝗕𝗢𝗧*\n"
        + DIV + "\n\n"
        "*Step 5 of 8 — Risk Profile*\n\n"
        "*📡 Conservative*  🟢 Low risk\n"
        "Capital: 20% per trade · fewer, higher\\-conviction entries\n\n"
        "*⚡ Balanced*  🟡 Medium risk  ⭐ Recommended\n"
        "Capital: 40% per trade · steady daily opportunities\n\n"
        "*🚀 Aggressive*  🔴 High risk\n"
        "Capital: 60% per trade · all signals active, max exposure\n\n"
        "Choose your trading style:"
    )


def onboard_preset_pick_text() -> str:
    return (
        "🏛️ *𝗖𝗥𝗨𝗦𝗔𝗗𝗘𝗥 \\| 𝗔𝗨𝗧𝗢𝗕𝗢𝗧*\n"
        + DIV + "\n\n"
        "*Step 6 of 8 — Strategy Preset*\n\n"
        "Each preset bundles a strategy, risk settings, and sizing\.\n\n"
        "*🐋 Whale Mirror* — follow proven Polymarket wallets\n"
        "*📡 Signal Sniper* — trade from curated signal feeds\n"
        "*🐋📡 Hybrid* — whale \\+ signal combined\n"
        "*🎯 Value Hunter* — edge model, mispriced markets\n"
        "*📈 Trend Breakout* — momentum\\-based entries\n"
        "*🔄 Contrarian* — fade the crowd strategy\n"
        "*🤖 Smart Mix* — multi\\-strategy, AI\\-weighted\n"
        "*🚀 Full Auto* — all strategies, max exposure\n\n"
        "Pick a preset to continue:"
    )


def onboard_review_text(risk_label: str, preset_emoji: str, preset_name: str) -> str:
    return (
        "🏛️ *𝗖𝗥𝗨𝗦𝗔𝗗𝗘𝗥 \\| 𝗔𝗨𝗧𝗢𝗕𝗢𝗧*\n"
        + DIV + "\n\n"
        "*Step 7 of 8 — Review Your Setup*\n\n"
        + _pre(_table([
            ("Risk:",    risk_label),
            ("Preset:",  f"{preset_emoji} {preset_name}"),
            ("Balance:", "$1,000.00 USDC"),
            ("Mode:",    "Paper (Safe)"),
        ], width=9))
        + "\n\n"
        "Everything looks good? Tap *🚀 Start Trading* to activate\.\n"
        "You can change any setting from the menu at any time\."
    )


# ── Screen 01 — Welcome ────────────────────────────────────────────────────────

BRAND = "🏛️ *𝗖𝗥𝗨𝗦𝗔𝗗𝗘𝗥 \\| 𝗔𝗨𝗧𝗢𝗕𝗢𝗧*"

WELCOME_TEXT = (
    "🏛️ *𝗖𝗥𝗨𝗦𝗔𝗗𝗘𝗥 \\| 𝗔𝗨𝗧𝗢𝗕𝗢𝗧*\n"
    + DIV + "\n\n"
    "Your autonomous Polymarket trading copilot\.\n\n"
    "Here's how it works:\n"
    "1️⃣  We create a wallet for you\n"
    "2️⃣  You pick a trading preset\n"
    "3️⃣  Bot trades for you 24/7\n\n"
    "> 📋 Paper Mode\n> Safe sandbox trading enabled\.\n\n"
    "Ready to start?"
)

LEARN_MORE_TEXT = (
    "*ℹ️ About CrusaderBot*\n"
    + DIV + "\n\n"
    "*What is CrusaderBot?*\n"
    "An autonomous trading bot for Polymarket prediction markets\. "
    "It scans markets 24/7, identifies opportunities, and executes trades "
    "based on your chosen strategy and risk settings\.\n\n"
    "*Paper Mode*\n"
    "All new accounts start in paper \\(sandbox\\) mode with virtual capital\. "
    "No real money is at risk until you explicitly activate live trading\.\n\n"
    "*Presets*\n"
    "Choose from 5 curated trading styles ranging from conservative "
    "whale\\-mirroring to fully autonomous multi\\-strategy execution\.\n\n"
    "*Safety*\n"
    "Hard\\-coded risk controls: max position 10%, daily loss limit $2,000, "
    "drawdown circuit\\-breaker at 8%, kill switch always available\."
)


def wallet_ready_text(address: str) -> str:
    return (
        "*✅ Your wallet is ready*\n\n"
        f"```\nAddress: {address}\n```\n\n"
        "This wallet receives USDC deposits\n"
        "on Polygon network\."
    )


def deposit_prompt_text(address: str) -> str:
    return (
        "*💰 Fund Your Wallet*\n\n"
        "Deposit USDC on Polygon to start live trading\.\n"
        "Minimum: $50\n\n"
        f"```\nYour address: {address}\n```"
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
    pulse_line: str = "📡 Scanning Polymarket liquidity...",
    last_scan: str = "—",
) -> str:
    status_emoji = "🟢" if autotrade_on else "⚫"
    status_label = "RUNNING" if autotrade_on else "OFF"
    today_icon = "📈" if float(pnl_today) >= 0 else "📉"
    preset_display = (
        f"{preset_emoji} {preset_name}"
        if preset_key else "—"
    )

    return (
        "🏛️ *𝗖𝗥𝗨𝗦𝗔𝗗𝗘𝗥 \\| 𝗔𝗨𝗧𝗢𝗕𝗢𝗧*\n"
        f"{DIV}\n\n"
        f"{_md(pulse_line)}\n"
        f"`Last scan: {last_scan}`\n\n"
        f"{DIV}\n"
        "*💼 Portfolio*\n"
        + _pre(_table([
            ("Equity:",   _fmt(total_equity)),
            ("Balance:",  _fmt(balance)),
            ("Exposure:", _fmt(positions_value)),
        ], width=10))
        + f"\n{DIV}\n"
        "*💰 P&L*\n"
        + _pre(_table([
            ("Today:",    f"{today_icon} {_signed(pnl_today)} ({_pct(pnl_today_pct)}%)"),
            ("7-Day:",    f"{_signed(pnl_7d)} ({_pct(pnl_7d_pct)}%)"),
            ("All-Time:", _signed(pnl_alltime)),
        ], width=10))
        + f"\n{DIV}\n"
        "*🤖 Auto Mode*\n"
        + _pre(_table([
            ("Status:", f"{status_emoji} {status_label}"),
            ("Preset:", preset_display),
            ("Risk:",   f"{risk_emoji} {risk_label}"),
            ("Trades:", f"{total_trades}  WR: {float(win_rate):.0f}%"),
        ], width=8))
    )


# ── Screen 03 — Preset Picker ──────────────────────────────────────────────────

PRESET_PICKER_TEXT = (
    "*🤖 Auto\\-Trade — Strategy*\n"
    + DIV + "\n\n"
    "*🧹 Close Sweep*  🟢 Safe  ⭐\n\n"
    "Enters in the final 35s of a BTC/ETH/SOL\n"
    "candle\. Requires a strong lean \\(≥55¢ side\\)\.\n\n"
    "```\n"
    "TP:      +90%\n"
    "SL:      -40%\n"
    "Capital: 40% per trade\n"
    "Mode:    Paper"
    "\n```\n\n"
    "Tap below to activate:"
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
        "*🤖 Auto\\-Trade Setup*\n"
        + DIV + "\n\n"
        f"📋 Preset: {_md(preset_emoji)} {_md(preset_name)}\n"
        f"├─ Strategy:      {_md(strategy_label)}\n"
        f"├─ Risk:          {_md(risk_emoji)} {_md(risk_label)}\n"
        f"├─ Capital:       {capital_pct}%\n"
        f"├─ TP / SL:       \\+{tp_pct}% / \\-{sl_pct}%\n"
        f"├─ Max per trade: {max_pos_pct}%\n"
        f"└─ Mode:          📝 Paper\n\n"
        "_ℹ️ You can change these anytime\n"
        "   from the Auto\\-Trade menu\\._"
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
        "*🤖 Auto\\-Trade Status*\n"
        + DIV + "\n\n"
        f"📋 Active Preset: {_md(preset_emoji)} {_md(preset_name)}\n"
        f"├─ Status:        🟢 RUNNING\n"
        f"├─ Since:         {_md(activated_date)}\n"
        f"├─ Trades today:  {trades_today}\n"
        f"└─ P&L today:     `{_signed(pnl_today)}`\n\n"
        "*⚙️ Current Config*\n"
        f"├─ Strategy: {_md(strategy_label)}\n"
        f"├─ Risk:     {_md(risk_emoji)} {_md(risk_label)}\n"
        f"├─ Capital:  {capital_pct}%\n"
        f"├─ TP / SL:  \\+{tp_pct}% / \\-{sl_pct}%\n"
        f"└─ Mode:     📝 Paper"
    )


def preset_activated_success_text(preset_emoji: str, preset_name: str) -> str:
    return (
        "*✅ Auto\\-Trade Activated*\n\n"
        f"Preset *{_md(preset_emoji)} {_md(preset_name)}* is now active\.\n\n"
        "> 📝 Paper Mode — no real capital at risk\.\n\n"
        "Returning to dashboard\.\.\."
    )


# ── Screen 05/06 — My Trades ───────────────────────────────────────────────────

def trades_empty_text() -> str:
    return (
        "*📈 My Trades*\n"
        + DIV + "\n\n"
        "No open positions yet\.\n\n"
        "Start your auto\\-trade preset to\n"
        "begin building your portfolio\."
    )


def trades_text(
    open_positions: list[dict],
    recent_closed: list[dict],
) -> str:
    lines = [
        "*📈 My Trades*",
        DIV,
        "",
        f"*📌 Open Positions \\({len(open_positions)}\\)*",
        "",
    ]

    for i, pos in enumerate(open_positions, 1):
        q = _md(pos.get("market_question", "Unknown market"))
        side = _md(pos.get("side", "YES"))
        entry = float(pos.get("entry_price", 0))
        size = float(pos.get("size_usdc", 0))
        current = float(pos.get("current_price", entry))
        pnl_pct = ((current - entry) / entry * 100) if entry else 0
        sign = "+" if pnl_pct >= 0 else ""
        lines.append(f"{i}️⃣ *{q}*")
        lines.append(
            f"```\n"
            f"Side:    {pos.get('side', 'YES').upper()} @ ${entry:.4f}\n"
            f"Size:    ${size:.2f}\n"
            f"Current: ${current:.4f} ({sign}{pnl_pct:.1f}%)\n"
            f"```"
        )
        lines.append("")

    if recent_closed:
        lines.append(DIV)
        lines.append("")
        lines.append("*📋 Recent Activity \\(last 5\\)*")
        for trade in recent_closed:
            q = _md(trade.get("market_question", "Unknown"))
            pnl = float(trade.get("pnl_usdc", 0))
            emoji = "✅" if pnl >= 0 else "❌"
            sign = "+" if pnl >= 0 else ""
            lines.append(f"{emoji} {q} → `{sign}${pnl:.2f}`")

    return "\n".join(lines)


def close_confirm_text(market_question: str, pnl: float, pnl_pct: float) -> str:
    sign = "+" if pnl >= 0 else ""
    return (
        "*⚠️ Close Position?*\n\n"
        f"*{_md(market_question)}*\n"
        f"Current P&L: `{sign}${pnl:.2f} ({sign}{pnl_pct:.1f}%)`\n\n"
        "This will close at market price\."
    )


# ── Wallet Screen ──────────────────────────────────────────────────────────────

def wallet_text(balance: Decimal | float, address: str) -> str:
    addr = address[:6] + "..." + address[-4:] if len(address) > 10 else address
    return (
        "💰 *Wallet*\n"
        + DIV + "\n\n"
        "📋 _Paper Mode — sandbox balance_\n\n"
        "```\n"
        f"Balance:   {_fmt(balance)}\n"
        f"Address:   {addr}\n"
        "```\n"
        "Deposit USDC on Polygon to go live\\.\n"
        "Min deposit: $50"
    )


def wallet_deposit_text(address: str, balance: Decimal | float) -> str:
    short = address[:6] + "..." + address[-4:] if len(address) > 10 else address
    return (
        "📥 *Deposit USDC*\n"
        + DIV + "\n\n"
        "*How to deposit:*\n"
        "1\\. Send USDC on *Polygon \\(MATIC\\)* network only\n"
        "2\\. Min deposit: *$50 USDC*\n"
        "3\\. Allow ~2 min for 32\\-block confirmation\n\n"
        "*Your deposit address:*\n"
        f"`{address}`\n\n"
        f"_Short: {_md(short)}_\n\n"
        f"Current balance: `{_fmt(balance)}`\n\n"
        "⚠️ _Do NOT send from exchange — use self\\-custody wallet\\._\n"
        "_Only Polygon network\\. Other chains \\= lost funds\\._"
    )


def withdraw_ask_amount_text(balance: Decimal | float) -> str:
    return (
        "📤 *Withdraw USDC*\n"
        + DIV + "\n\n"
        f"Available balance: `{_fmt(balance)}`\n\n"
        "Enter the amount to withdraw \\(min $5\\):\n"
        "_Example: 25\\.00_"
    )


def withdraw_ask_address_text(amount: str) -> str:
    return (
        "📤 *Withdraw — Step 2/3*\n"
        + DIV + "\n\n"
        f"Amount: `${amount} USDC`\n\n"
        "Enter your Polygon wallet address:\n"
        "_Example: 0xAbCd\\.\\.\\.1234_"
    )


def withdraw_confirm_text(amount: str, address: str) -> str:
    short = address[:6] + "..." + address[-4:] if len(address) > 10 else address
    return (
        "📤 *Confirm Withdrawal*\n"
        + DIV + "\n\n"
        f"Amount:  `${amount} USDC`\n"
        f"To:      `{address}`\n"
        f"         _\\({_md(short)}\\)_\n\n"
        "📋 _Paper mode — no on\\-chain transfer yet\\._\n"
        "_Funds will be debited from your paper balance\\._\n"
        "_Admin approval required\\._"
    )


def withdraw_submitted_text(amount: str, mode: str) -> str:
    if mode == "auto":
        approval_line = "✅ Auto\\-approved — balance debited\\."
    else:
        approval_line = "⏳ Pending admin approval\\."
    return (
        "📤 *Withdrawal Submitted*\n"
        + DIV + "\n\n"
        f"Amount: `${amount} USDC`\n"
        f"{approval_line}\n\n"
        "You will be notified once processed\\."
    )


def withdraw_history_text(withdrawals: list[dict]) -> str:
    if not withdrawals:
        return (
            "📜 *Withdrawal History*\n"
            + DIV + "\n\n"
            "_No withdrawals yet\\._"
        )
    lines = ["📜 *Withdrawal History*", DIV, ""]
    status_icons = {
        "pending": "⏳", "approved": "✅", "rejected": "❌",
        "processing": "🔄", "completed": "✅", "failed": "❌",
    }
    for w in withdrawals[:8]:
        icon = status_icons.get(w["status"], "❓")
        ts = w["created_at"].strftime("%m-%d %H:%M") if w.get("created_at") else "—"
        short_addr = str(w["destination_address"])[:6] + "…" + str(w["destination_address"])[-4:]
        lines.append(
            f"{icon} `${w['amount_usdc']:.2f}` → "
            f"`{short_addr}` · {_md(ts)}"
        )
    return "\n".join(lines)


def admin_withdrawal_item_text(w: dict) -> str:
    short_addr = str(w["destination_address"])[:6] + "…" + str(w["destination_address"])[-4:]
    ts = w["created_at"].strftime("%Y-%m-%d %H:%M") if w.get("created_at") else "—"
    user_label = w.get("username") or str(w["telegram_id"])
    return (
        "*Withdrawal Request*\n"
        f"User:    @{_md(str(user_label))}\n"
        f"Amount:  `${w['amount_usdc']:.2f} USDC`\n"
        f"To:      `{w['destination_address']}`\n"
        f"         _\\({_md(short_addr)}\\)_\n"
        f"Time:    `{ts}`\n"
        f"ID:      `{str(w['id'])[:8]}…`"
    )


# ── Emergency Menu ─────────────────────────────────────────────────────────────

EMERGENCY_TEXT = (
    "🚨 *Emergency Controls*\n"
    + DIV + "\n\n"
    "⚠️ These actions take effect immediately\\."
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
    "stop_auto_trade": (
        "🛑 Stop All Auto Trade",
        "Disables auto-trading immediately.\nOpen positions are kept as-is.",
    ),
    "kill_all_positions": (
        "💀 Kill All Positions",
        "Queues every open position for immediate close at market price.\nThis cannot be undone.",
    ),
    "lock_bot": (
        "🔒 Lock Bot",
        "Disables all trading and locks your account.\nRequires admin support to unlock.",
    ),
}


def emergency_confirm_text(action: str) -> str:
    name, desc = EMERGENCY_CONFIRM_TEXTS.get(action, ("Unknown Action", ""))
    return (
        f"*⚠️ Confirm: {_md(name)}?*\n\n"
        f"{_md(desc)}"
    )


def emergency_feedback_text(action: str) -> str:
    labels = {
        "pause":             "✅ Auto\\-trade paused\\. No new trades will be entered\\.",
        "pause_close":       "✅ Auto\\-trade paused and all positions queued for close\\.",
        "lock":              "🔒 Account locked\\. Contact support to unlock\\.",
        "stop_auto_trade":   "🛑 Auto\\-trading stopped\\. No new trades will be entered\\.",
        "kill_all_positions":"💀 All positions queued for close\\.",
        "lock_bot":          "🔒 Bot locked\\. All trading disabled\\. Contact support to unlock\\.",
    }
    return labels.get(action, "✅ Action completed\\.")


def emergency_system_status_text(
    *,
    auto_icon: str,
    auto_on: bool,
    paused: bool,
    lock_icon: str,
    locked: bool,
    open_positions: int,
    copy_active: int,
) -> str:
    auto_label = "ON" if (auto_on and not paused and not locked) else "OFF"
    return (
        "ℹ️ *System Status*\n"
        + DIV + "\n"
        f"{auto_icon} Auto\\-Trade: *{auto_label}*"
        + (" \\(paused\\)" if paused and not locked else "")
        + "\n"
        f"{lock_icon} Account: *{'LOCKED' if locked else 'ACTIVE'}*\n"
        f"📊 Open Positions: *{open_positions}*\n"
        f"🐋 Active Copy Tasks: *{copy_active}*"
    )
