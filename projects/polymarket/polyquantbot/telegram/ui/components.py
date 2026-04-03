"""telegram.ui.components — Reusable premium UI renderers for PolyQuantBot.

All functions are pure: no I/O, no side-effects.  They accept typed data
structures and return Markdown-formatted strings ready for Telegram.

Design:
  - Consistent separators: ━━━━━━━━━━━━━━━━━━━━━━
  - Emoji signals: 🟢 RUNNING, 🔴 HALTED/error, 🟡 PAUSED, 🔵 INFO
  - Every section uses structured headers
  - Safe on missing data (None / empty list → placeholder text)
"""
from __future__ import annotations

from typing import Optional


# ── Constants ─────────────────────────────────────────────────────────────────

_SEP = "━━━━━━━━━━━━━━━━━━━━━━"
_SEP_THIN = "──────────────────────"

#: Public alias — use this in other modules
SEP = _SEP
SEP_THIN = _SEP_THIN


def _state_emoji(state: str) -> str:
    """Return a coloured circle for the given system state string."""
    s = state.upper()
    if s == "RUNNING":
        return "🟢"
    if s == "PAUSED":
        return "🟡"
    if s in ("HALTED", "STOPPED", "ERROR"):
        return "🔴"
    return "🔵"


def _pnl_sign(value: float) -> str:
    """Return '+' for positive, '' for negative (sign is in the number)."""
    return "+" if value >= 0 else ""


def _pnl_color(value: float) -> str:
    """Return 📈 for profit, 📉 for loss, ➖ for zero."""
    if value > 0:
        return "📈"
    if value < 0:
        return "📉"
    return "➖"


# ── Status Bar ────────────────────────────────────────────────────────────────


def render_status_bar(
    state: str = "RUNNING",
    mode: str = "PAPER",
    latency_ms: Optional[float] = None,
    markets_count: Optional[int] = None,
    active_signals: Optional[int] = None,
) -> str:
    """Render a compact one-line status bar injected at top of every screen.

    Args:
        state:          System state string (RUNNING / PAUSED / HALTED).
        mode:           Trading mode (PAPER / LIVE).
        latency_ms:     Latest pipeline latency in milliseconds.
        markets_count:  Number of markets currently being scanned.
        active_signals: Number of signals generated in last cycle.

    Returns:
        Single-line Markdown string, e.g.:
        ``🟢 RUNNING | 📄 PAPER | ⚡ 42ms | 🔍 128 mkts | 📡 3 signals``
    """
    state_dot = _state_emoji(state)
    mode_icon = "📄" if mode.upper() == "PAPER" else "💵"
    parts = [f"{state_dot} {state}", f"{mode_icon} {mode}"]
    if latency_ms is not None:
        parts.append(f"⚡ {latency_ms:.0f}ms")
    if markets_count is not None:
        parts.append(f"🔍 {markets_count} mkts")
    if active_signals is not None:
        parts.append(f"📡 {active_signals} sigs")
    return " | ".join(parts)


# ── Wallet Card ────────────────────────────────────────────────────────────────


def render_wallet_card(
    cash: float,
    locked: float,
    equity: float,
    realized_pnl: float = 0.0,
    unrealized_pnl: float = 0.0,
    open_positions: int = 0,
    mode: str = "PAPER",
    status_bar: Optional[str] = None,
) -> str:
    """Render a full-detail wallet terminal card.

    Args:
        cash:             Available (unlocked) funds.
        locked:           Funds reserved for open positions.
        equity:           Total portfolio value (cash + locked).
        realized_pnl:     Cumulative realized PnL.
        unrealized_pnl:   Current mark-to-market unrealized PnL.
        open_positions:   Count of open positions.
        mode:             Trading mode for header label.
        status_bar:       Pre-rendered status bar string (optional).

    Returns:
        Markdown string.
    """
    buying_power = cash  # buying power = free cash
    exposure = locked    # exposure = locked capital

    r_sign = _pnl_sign(realized_pnl)
    u_sign = _pnl_sign(unrealized_pnl)
    r_icon = _pnl_color(realized_pnl)
    u_icon = _pnl_color(unrealized_pnl)

    lines: list[str] = []

    if status_bar:
        lines.append(status_bar)
        lines.append(_SEP)

    lines += [
        f"💼 *WALLET* — {mode} MODE",
        _SEP,
        f"💵  Cash (free)     `${cash:>12,.2f}`",
        f"🔒  Locked          `${locked:>12,.2f}`",
        f"📊  Equity (total)  `${equity:>12,.2f}`",
        _SEP_THIN,
        f"⚡  Buying Power    `${buying_power:>12,.2f}`",
        f"📉  Exposure        `${exposure:>12,.2f}`",
        f"📌  Open Positions  `{open_positions:>13}`",
        _SEP_THIN,
        f"{r_icon}  Realized PnL    `{r_sign}${realized_pnl:>11,.4f}`",
        f"{u_icon}  Unrealized PnL  `{u_sign}${unrealized_pnl:>11,.4f}`",
        _SEP,
    ]

    if mode.upper() == "PAPER":
        lines.append("_🧪 Paper trading — no real funds at risk_")
    else:
        lines.append("_⚠️ Live mode — real capital deployed_")

    return "\n".join(lines)


# ── Trade Card ────────────────────────────────────────────────────────────────


def render_trade_card(
    market_question: str,
    market_id: str,
    side: str,
    entry_price: float,
    current_price: float,
    size: float,
    unrealized_pnl: float,
    status: str = "OPEN",
    fill_pct: float = 100.0,
    slippage: float = 0.0,
    opened_at: Optional[str] = None,
    status_bar: Optional[str] = None,
) -> str:
    """Render a single trade / position detail card.

    Args:
        market_question: Human-readable market question (preferred over ID).
        market_id:       Polymarket condition ID (used as fallback).
        side:            Trade direction (YES / NO / BUY / SELL).
        entry_price:     Fill price at open.
        current_price:   Latest mark price.
        size:            Position size in USD.
        unrealized_pnl:  Current unrealized profit/loss.
        status:          Position status (OPEN / CLOSED / PARTIAL).
        fill_pct:        Fill percentage (0–100).
        slippage:        Estimated slippage in price units.
        opened_at:       Human-readable open timestamp.
        status_bar:      Pre-rendered status bar string (optional).

    Returns:
        Markdown string.
    """
    pnl_sign = _pnl_sign(unrealized_pnl)
    pnl_icon = _pnl_color(unrealized_pnl)
    side_icon = "🟢" if side.upper() in ("YES", "BUY") else "🔴"

    # Truncate long market questions
    display_name = (
        market_question if len(market_question) <= 60
        else market_question[:57] + "…"
    )

    lines: list[str] = []

    if status_bar:
        lines.append(status_bar)
        lines.append(_SEP)

    lines += [
        f"📌 *POSITION — {status}*",
        _SEP,
        f"🏷️  Market: _{display_name}_",
        f"🔑  ID: `{market_id[:20]}…`" if len(market_id) > 20 else f"🔑  ID: `{market_id}`",
        _SEP_THIN,
        f"{side_icon}  Side           `{side}`",
        f"💰  Size           `${size:>12,.4f}`",
        f"📥  Entry Price    `{entry_price:>13,.6f}`",
        f"📊  Current Price  `{current_price:>13,.6f}`",
    ]

    if fill_pct < 100.0:
        lines.append(f"⚠️  Fill           `{fill_pct:>12.1f}%`")
    if slippage != 0.0:
        lines.append(f"📐  Slippage       `{slippage:>+13,.6f}`")

    lines += [
        _SEP_THIN,
        f"{pnl_icon}  Unrealized PnL `{pnl_sign}${unrealized_pnl:>11,.4f}`",
        _SEP,
    ]

    if opened_at:
        lines.append(f"_Opened: {opened_at}_")

    return "\n".join(lines)


# ── Strategy Card ─────────────────────────────────────────────────────────────


_STRATEGY_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "ev_momentum": {
        "title": "EV Momentum",
        "description": "Trades markets where the Expected Value is skewed positively vs current price.",
        "when_to_use": "High-volume markets with strong directional price movement.",
        "risk": "Medium — can chase trends. Best with Kelly α ≤ 0.25.",
    },
    "mean_reversion": {
        "title": "Mean Reversion",
        "description": "Fades extreme moves, assuming prices revert to their historical mean.",
        "when_to_use": "Stable markets with no major news catalyst.",
        "risk": "Low-Medium — short holding periods reduce overnight exposure.",
    },
    "liquidity_edge": {
        "title": "Liquidity Edge",
        "description": "Exploits thin orderbooks to enter at better prices than market participants.",
        "when_to_use": "Illiquid long-tail markets with wide spreads.",
        "risk": "Low — position sizes auto-capped by market depth.",
    },
}

_DEFAULT_STRATEGY_DESC = {
    "title": "Custom Strategy",
    "description": "User-defined strategy.",
    "when_to_use": "As configured.",
    "risk": "Variable.",
}


def render_strategy_card(
    strategies: list[str],
    active_states: dict[str, bool],
    status_bar: Optional[str] = None,
    show_descriptions: bool = True,
) -> str:
    """Render the full strategy menu with states and descriptions.

    Args:
        strategies:        List of known strategy names.
        active_states:     Dict mapping strategy_name → bool (enabled/disabled).
        status_bar:        Pre-rendered status bar string (optional).
        show_descriptions: Whether to include per-strategy description blocks.

    Returns:
        Markdown string.
    """
    lines: list[str] = []

    if status_bar:
        lines.append(status_bar)
        lines.append(_SEP)

    active_list = [s for s, v in active_states.items() if v]
    lines += [
        "📐 *STRATEGIES*",
        _SEP,
        f"Active: {', '.join(f'`{s}`' for s in active_list) if active_list else '_none_'}",
        "",
    ]

    for strat in strategies:
        enabled = active_states.get(strat, False)
        toggle_icon = "🟢" if enabled else "🔴"
        state_label = "ENABLED" if enabled else "DISABLED"
        desc_block = _STRATEGY_DESCRIPTIONS.get(strat, _DEFAULT_STRATEGY_DESC)

        lines.append(f"{toggle_icon} *{desc_block['title']}* — `{state_label}`")

        if show_descriptions:
            lines += [
                f"   _{desc_block['description']}_",
                f"   📌 *When:* {desc_block['when_to_use']}",
                f"   ⚠️ *Risk:* {desc_block['risk']}",
                "",
            ]

    lines += [
        _SEP,
        "_Tap a strategy button to toggle it on/off._",
    ]

    return "\n".join(lines)


# ── Risk Card ─────────────────────────────────────────────────────────────────


_RISK_LEVEL_INFO: dict[str, dict[str, str]] = {
    "conservative": {
        "label": "Conservative (0.10)",
        "description": "Minimum Kelly fraction. Very small position sizes.",
        "when_to_use": "New markets, high uncertainty, first live deployments.",
        "impact": "Low drawdown risk. Slow equity growth.",
    },
    "moderate": {
        "label": "Moderate (0.25)",
        "description": "Fractional Kelly — the recommended baseline.",
        "when_to_use": "Standard operation on validated signals.",
        "impact": "Balanced risk/return. SENTINEL-approved default.",
    },
    "aggressive": {
        "label": "Aggressive (0.50)",
        "description": "Half Kelly. Larger positions, higher variance.",
        "when_to_use": "High-conviction signals only.",
        "impact": "Significant drawdown possible. Use with caution.",
    },
    "max": {
        "label": "Maximum (1.00)",
        "description": "Full Kelly — WARNING: mathematically optimal but practically dangerous.",
        "when_to_use": "NOT recommended. Research/testing only.",
        "impact": "Extreme variance. Can result in total capital loss.",
    },
}


def render_risk_card(
    current_value: float,
    status_bar: Optional[str] = None,
) -> str:
    """Render risk level setting with explanation and impact.

    Args:
        current_value: Current Kelly fraction multiplier (e.g. 0.25).
        status_bar:    Pre-rendered status bar string (optional).

    Returns:
        Markdown string.
    """
    if current_value <= 0.10:
        level_key = "conservative"
    elif current_value <= 0.25:
        level_key = "moderate"
    elif current_value <= 0.50:
        level_key = "aggressive"
    else:
        level_key = "max"

    info = _RISK_LEVEL_INFO[level_key]
    risk_icon = "🟢" if level_key == "moderate" else ("🟡" if level_key == "conservative" else "🔴")

    lines: list[str] = []

    if status_bar:
        lines.append(status_bar)
        lines.append(_SEP)

    lines += [
        "⚠️ *RISK LEVEL*",
        _SEP,
        f"{risk_icon} Current: `{current_value:.2f}` — *{info['label']}*",
        "",
        f"📋 *What it does:*",
        f"_{info['description']}_",
        "",
        f"📌 *When to use:*",
        f"_{info['when_to_use']}_",
        "",
        f"⚡ *Risk impact:*",
        f"_{info['impact']}_",
        _SEP,
        "Select a preset below or use `/set_risk <value>` (0.10 – 1.00):",
    ]

    return "\n".join(lines)


# ── Mode Card ─────────────────────────────────────────────────────────────────


def render_mode_card(
    current_mode: str,
    status_bar: Optional[str] = None,
) -> str:
    """Render trading mode info with explanation and switch prompt.

    Args:
        current_mode: Current mode string (PAPER / LIVE).
        status_bar:   Pre-rendered status bar string (optional).

    Returns:
        Markdown string.
    """
    is_live = current_mode.upper() == "LIVE"
    mode_icon = "💵" if is_live else "📄"
    new_mode = "PAPER" if is_live else "LIVE"

    lines: list[str] = []

    if status_bar:
        lines.append(status_bar)
        lines.append(_SEP)

    lines += [
        "🔀 *TRADING MODE*",
        _SEP,
        f"{mode_icon} Current: `{current_mode}`",
        "",
    ]

    if is_live:
        lines += [
            "📋 *LIVE MODE:*",
            "_Real capital deployed on Polymarket CLOB._",
            "_Orders are filled at market prices._",
            "",
            "⚠️ *Risk:* Real money at stake. Ensure risk limits are set.",
            "",
            f"Switch to `PAPER` mode for simulation.",
        ]
    else:
        lines += [
            "📋 *PAPER MODE:*",
            "_Simulated trading — no real capital deployed._",
            "_All PnL is virtual. Safe for testing strategies._",
            "",
            "✅ *Risk:* Zero financial risk. Full pipeline active.",
            "",
            f"Switch to `LIVE` mode to deploy real capital.",
            "⚠️ Requires `ENABLE_LIVE_TRADING=true` env var.",
        ]

    lines.append(_SEP)
    lines.append(f"Confirm switch to `{new_mode}` mode?")

    return "\n".join(lines)


# ── Start Screen ──────────────────────────────────────────────────────────────


def render_start_screen(
    system_state: str,
    mode: str,
    wallet_cash: float,
    wallet_equity: float,
    open_positions: int,
    active_strategies: list[str],
    latency_ms: Optional[float] = None,
    markets_count: Optional[int] = None,
    realized_pnl: float = 0.0,
    unrealized_pnl: float = 0.0,
    version: str = "v2.0",
) -> str:
    """Render the premium boot / start screen.

    Args:
        system_state:      RUNNING / PAUSED / HALTED.
        mode:              PAPER / LIVE.
        wallet_cash:       Free cash balance.
        wallet_equity:     Total equity.
        open_positions:    Count of open positions.
        active_strategies: List of enabled strategy names.
        latency_ms:        Pipeline latency in ms.
        markets_count:     Number of markets being scanned.
        realized_pnl:      Cumulative realized PnL.
        unrealized_pnl:    Current unrealized PnL.
        version:           Bot version string.

    Returns:
        Markdown string.
    """
    state_dot = _state_emoji(system_state)
    mode_icon = "💵" if mode.upper() == "LIVE" else "📄"
    r_icon = _pnl_color(realized_pnl)
    u_icon = _pnl_color(unrealized_pnl)
    r_sign = _pnl_sign(realized_pnl)
    u_sign = _pnl_sign(unrealized_pnl)

    strats_str = (
        "  ".join(f"`{s}`" for s in active_strategies)
        if active_strategies else "_none active_"
    )

    lat_str = f"`{latency_ms:.0f}ms`" if latency_ms is not None else "_n/a_"
    mkts_str = f"`{markets_count}`" if markets_count is not None else "_n/a_"

    lines = [
        "```",
        "╔══════════════════════════════╗",
        "║  🤖  POLYQUANTBOT  " + f"{version:<11}║",
        "║  Polymarket AI Trading System ║",
        "╚══════════════════════════════╝",
        "```",
        "",
        f"{state_dot} *{system_state}*  {mode_icon} *{mode} MODE*",
        _SEP,
        "📡 *SYSTEM*",
        f"  Latency:  {lat_str}",
        f"  Markets:  {mkts_str}",
        "",
        "💼 *WALLET*",
        f"  Cash:     `${wallet_cash:,.2f}`",
        f"  Equity:   `${wallet_equity:,.2f}`",
        f"  Positions:`{open_positions}`",
        "",
        "📈 *P&L*",
        f"  {r_icon} Realized:   `{r_sign}${realized_pnl:,.4f}`",
        f"  {u_icon} Unrealized: `{u_sign}${unrealized_pnl:,.4f}`",
        "",
        "📐 *STRATEGIES*",
        f"  {strats_str}",
        _SEP,
        "_Select an option from the menu below:_",
    ]

    return "\n".join(lines)


# ── Positions Summary ─────────────────────────────────────────────────────────


def render_positions_summary(
    positions: list[dict],
    wallet_equity: float,
    market_cache_fn=None,
    status_bar: Optional[str] = None,
) -> str:
    """Render a full exposure / positions list.

    Args:
        positions:       List of position dicts with keys:
                         market_id, market_question, side, size,
                         unrealized_pnl, entry_price, exposure_pct.
        wallet_equity:   Total portfolio equity.
        market_cache_fn: Optional callable(market_id) → str question (unused,
                         question should already be resolved in dict).
        status_bar:      Pre-rendered status bar string (optional).

    Returns:
        Markdown string.
    """
    lines: list[str] = []

    if status_bar:
        lines.append(status_bar)
        lines.append(_SEP)

    if not positions:
        lines += [
            "📉 *EXPOSURE*",
            _SEP,
            "_No open positions — zero exposure._",
            _SEP,
        ]
        return "\n".join(lines)

    total_exposure = sum(p.get("size", 0.0) for p in positions)
    total_unrealized = sum(p.get("unrealized_pnl", 0.0) for p in positions)
    exposure_pct = (total_exposure / wallet_equity * 100) if wallet_equity > 0 else 0.0
    u_icon = _pnl_color(total_unrealized)
    u_sign = _pnl_sign(total_unrealized)

    lines += [
        "📉 *EXPOSURE & POSITIONS*",
        _SEP,
        f"📊  Total Exposure  `${total_exposure:>12,.2f}`",
        f"📈  Exposure %      `{exposure_pct:>12.1f}%`",
        f"📌  Positions       `{len(positions):>13}`",
        f"{u_icon}  Unrealized PnL `{u_sign}${total_unrealized:>11,.4f}`",
        _SEP_THIN,
        "*Positions:*",
        "",
    ]

    for pos in positions:
        p_pnl = pos.get("unrealized_pnl", 0.0)
        p_sign = _pnl_sign(p_pnl)
        p_icon = _pnl_color(p_pnl)
        side = pos.get("side", "?")
        side_icon = "🟢" if side.upper() in ("YES", "BUY") else "🔴"
        market_q = pos.get("market_question") or pos.get("market_id", "?")
        market_label = (
            market_q if len(market_q) <= 40 else market_q[:37] + "…"
        )
        lines.append(
            f"{side_icon} _{market_label}_\n"
            f"   {side} · `${pos.get('size', 0):.2f}` · {p_icon}`{p_sign}${p_pnl:.4f}`"
        )

    lines += ["", _SEP]
    return "\n".join(lines)
