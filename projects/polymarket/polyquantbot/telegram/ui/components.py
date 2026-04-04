"""telegram.ui.components — Reusable premium UI renderers for PolyQuantBot.

All functions are pure: no I/O, no side-effects.  They accept typed data
structures and return Markdown-formatted strings ready for Telegram.

Design (STYLE B — SPACING SYSTEM V2):
  - Consistent separators: ━━━━━━━━━━━━━━━━━━━━━━
  - KV lines:  LABEL        ● VALUE  (uppercase label, padded to 12 chars)
  - Sections:  emoji *TITLE* + separator + content lines + separator
  - Insight:   🧠 _Insight: <text>_  present on every major screen
  - One emoji per section header
  - Uppercase labels, no ":" alignment
  - Max line width ~32 chars
  - Safe on missing data (None / empty list → "N/A" or placeholder)
"""
from __future__ import annotations

from typing import Optional


# ── Constants ─────────────────────────────────────────────────────────────────

_SEP = "━━━━━━━━━━━━━━━━━━━━━━"
_SEP_THIN = "──────────────────────"
_LABEL_WIDTH = 12  # chars reserved for KV label field

#: Public aliases — use in other modules
SEP = _SEP
SEP_THIN = _SEP_THIN


# ── Core V2 Primitives ────────────────────────────────────────────────────────


def render_separator() -> str:
    """Return the standard STYLE B separator line."""
    return _SEP


def render_kv_line(label: str, value: str) -> str:
    """Render a key-value line using SPACING SYSTEM V2.

    Format: ``LABEL        ● VALUE``

    Args:
        label: Field label (will be uppercased and left-padded to _LABEL_WIDTH).
        value: Field value as a pre-formatted string.

    Returns:
        Single-line string ready for Markdown output.
    """
    padded = f"{label.upper():<{_LABEL_WIDTH}}"
    return f"{padded} ● {value}"


def render_section(title: str, lines: list[str]) -> str:
    """Render a named section block with separator framing.

    Format::

        *title*
        ━━━━━━━━━━━━━━━━━━━━━━
        line1
        line2
        ━━━━━━━━━━━━━━━━━━━━━━

    Args:
        title:  Section title (rendered as bold Markdown).
        lines:  Content lines included between the separators.

    Returns:
        Multi-line Markdown string.
    """
    parts = [f"*{title}*", _SEP] + lines + [_SEP]
    return "\n".join(parts)


def render_insight(text: str) -> str:
    """Render the insight line injected at the bottom of every major screen.

    Args:
        text: Insight message (e.g. "Monitoring 3 positions").

    Returns:
        Formatted italic insight line.
    """
    return f"🧠 _Insight: {text}_"


# ── Internal helpers ──────────────────────────────────────────────────────────


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
    """Return '+' for non-negative values, '' otherwise."""
    return "+" if value >= 0 else ""


def _pnl_color(value: float) -> str:
    """Return 📈 for profit, 📉 for loss, ➖ for zero."""
    if value > 0:
        return "📈"
    if value < 0:
        return "📉"
    return "➖"


def _truncate(text: str, max_len: int) -> str:
    """Truncate *text* with an ellipsis if it exceeds *max_len* characters."""
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


# ── Status Bar ────────────────────────────────────────────────────────────────


def render_status_bar(
    state: str = "RUNNING",
    mode: str = "PAPER",
    latency_ms: Optional[float] = None,
    markets_count: Optional[int] = None,
    active_signals: Optional[int] = None,
) -> str:
    """Render a multi-line system status block using SPACING SYSTEM V2.

    Fields shown in LABEL ● VALUE format:
      WS STATUS, MODE, MARKETS (optional), SIGNALS (optional), LATENCY (optional).

    Args:
        state:          System state string (RUNNING / PAUSED / HALTED).
        mode:           Trading mode (PAPER / LIVE).
        latency_ms:     Latest pipeline latency in milliseconds.
        markets_count:  Number of markets currently being scanned.
        active_signals: Number of signals generated in last cycle.

    Returns:
        Multi-line Markdown string.
    """
    state_dot = _state_emoji(state)
    mode_icon = "📄" if mode.upper() == "PAPER" else "💵"
    lines = [
        render_kv_line("WS STATUS", f"{state_dot} {state.upper()}"),
        render_kv_line("MODE", f"{mode_icon} {mode.upper()}"),
    ]
    if markets_count is not None:
        lines.append(render_kv_line("MARKETS", str(markets_count)))
    if active_signals is not None:
        lines.append(render_kv_line("SIGNALS", str(active_signals)))
    if latency_ms is not None:
        lines.append(render_kv_line("LATENCY", f"{latency_ms:.0f}ms"))
    return "\n".join(lines)


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
    """Render a full-detail wallet terminal card (STYLE B).

    Sections:
      💼 WALLET OVERVIEW — balance, locked, equity, exposure, positions
      📊 PERFORMANCE     — realized and unrealized PnL
      🧠 Insight line    — contextual note based on position count

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
    r_sign = _pnl_sign(realized_pnl)
    u_sign = _pnl_sign(unrealized_pnl)

    positions_str = f"{open_positions}" if open_positions > 0 else "0 (IDLE)"

    if open_positions > 0:
        insight_text = f"Monitoring {open_positions} position{'s' if open_positions != 1 else ''}"
    else:
        insight_text = "Scanning markets"

    lines: list[str] = []

    if status_bar:
        lines.append(status_bar)
        lines.append(_SEP)

    mode_label = "PAPER MODE" if mode.upper() == "PAPER" else "LIVE MODE"
    lines += [
        f"💼 *WALLET OVERVIEW* — {mode_label}",
        _SEP,
        render_kv_line("BALANCE", f"${cash:,.2f}"),
        render_kv_line("LOCKED", f"${locked:,.2f}"),
        render_kv_line("EQUITY", f"${equity:,.2f}"),
        render_kv_line("EXPOSURE", f"${locked:,.2f}"),
        render_kv_line("POSITIONS", positions_str),
        _SEP,
        "📊 *PERFORMANCE*",
        _SEP_THIN,
        render_kv_line("REALIZED", f"{r_sign}${realized_pnl:,.4f}"),
        render_kv_line("UNREALIZED", f"{u_sign}${unrealized_pnl:,.4f}"),
        _SEP,
        render_insight(insight_text),
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
    """Render a single trade / position detail card (STYLE B).

    Fields shown in LABEL ● VALUE format:
      SIDE, ENTRY, CURRENT, SIZE, PNL (+ optional FILL, SLIPPAGE).

    Args:
        market_question: Human-readable market question (preferred over ID).
        market_id:       Polymarket condition ID (fallback display).
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
    side_icon = "🟢" if side.upper() in ("YES", "BUY") else "🔴"

    display_name = _truncate(market_question or market_id or "N/A", 40)

    lines: list[str] = []

    if status_bar:
        lines.append(status_bar)
        lines.append(_SEP)

    lines += [
        f"📌 *POSITION — {status.upper()}*",
        _SEP,
        f"_{display_name}_",
        _SEP_THIN,
        render_kv_line("SIDE", f"{side_icon} {side.upper()}"),
        render_kv_line("ENTRY", f"{entry_price:.6f}"),
        render_kv_line("CURRENT", f"{current_price:.6f}"),
        render_kv_line("SIZE", f"${size:,.4f}"),
        render_kv_line("PNL", f"{pnl_sign}${unrealized_pnl:,.4f}"),
    ]

    if fill_pct < 100.0:
        lines.append(render_kv_line("FILL", f"{fill_pct:.1f}%"))
    if slippage != 0.0:
        lines.append(render_kv_line("SLIPPAGE", f"{slippage:+,.6f}"))

    lines.append(_SEP)

    if opened_at:
        lines.append(f"_Opened: {opened_at}_")

    lines.append(render_insight("Monitoring 1 position"))

    return "\n".join(lines)


# ── Strategy Card ─────────────────────────────────────────────────────────────


_STRATEGY_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "ev_momentum": {
        "title": "EV MOMENTUM",
        "description": "Trades markets where EV skews positively vs current price.",
        "when_to_use": "High-volume markets with strong directional price movement.",
        "risk": "Medium — can chase trends. Best with Kelly α ≤ 0.25.",
    },
    "mean_reversion": {
        "title": "MEAN REVERSION",
        "description": "Fades extreme moves, assumes prices revert to the mean.",
        "when_to_use": "Stable markets with no major news catalyst.",
        "risk": "Low-Medium — short holding periods reduce overnight exposure.",
    },
    "liquidity_edge": {
        "title": "LIQUIDITY EDGE",
        "description": "Exploits thin orderbooks for better entry prices.",
        "when_to_use": "Illiquid long-tail markets with wide spreads.",
        "risk": "Low — position sizes auto-capped by market depth.",
    },
}

_DEFAULT_STRATEGY_DESC = {
    "title": "CUSTOM STRATEGY",
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
    """Render the full strategy menu (STYLE B).

    Each strategy rendered as:
      ● NAME
        short description
        Status: 🟢 ACTIVE / 🔴 DISABLED

    Args:
        strategies:        List of known strategy names.
        active_states:     Dict mapping strategy_name → bool (enabled/disabled).
        status_bar:        Pre-rendered status bar string (optional).
        show_descriptions: Whether to include per-strategy description line.

    Returns:
        Markdown string.
    """
    lines: list[str] = []

    if status_bar:
        lines.append(status_bar)
        lines.append(_SEP)

    active_count = sum(1 for v in active_states.values() if v)
    lines += [
        "🧠 *STRATEGY ENGINE*",
        _SEP,
    ]

    for strat in strategies:
        enabled = active_states.get(strat, False)
        status_icon = "🟢" if enabled else "🔴"
        status_label = "ACTIVE" if enabled else "DISABLED"
        desc_block = _STRATEGY_DESCRIPTIONS.get(strat, _DEFAULT_STRATEGY_DESC)

        lines.append(f"● *{desc_block['title']}*")

        if show_descriptions:
            lines.append(f"  _{desc_block['description']}_")

        lines.append(f"  Status: {status_icon} {status_label}")
        lines.append("")

    lines.append(_SEP)

    if active_count == 0:
        insight_text = "No strategies active — market scanning paused"
    else:
        insight_text = f"{active_count} strateg{'y' if active_count == 1 else 'ies'} active"

    lines.append(render_insight(insight_text))
    lines.append("_Tap a strategy button to toggle it on/off._")

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
    """Render risk level setting with LABEL ● VALUE formatting.

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
        render_kv_line("KELLY", f"{current_value:.2f}"),
        render_kv_line("LEVEL", f"{risk_icon} {info['label']}"),
        _SEP_THIN,
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
    """Render trading mode info with LABEL ● VALUE formatting.

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
        render_kv_line("CURRENT", f"{mode_icon} {current_mode.upper()}"),
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
            "Switch to `PAPER` mode for simulation.",
        ]
    else:
        lines += [
            "📋 *PAPER MODE:*",
            "_Simulated trading — no real capital deployed._",
            "_All PnL is virtual. Safe for testing strategies._",
            "",
            "✅ *Risk:* Zero financial risk. Full pipeline active.",
            "",
            "Switch to `LIVE` mode to deploy real capital.",
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
    """Render the premium STYLE B boot / start screen.

    Layout:
      🚀 KRUSADER AI v2.0
      ⚙️ SYSTEM block   — state, mode, markets, latency
      💼 PORTFOLIO block — balance, equity, positions
      📈 PERFORMANCE    — realized, unrealized PnL
      🧠 STRATEGY ENGINE — active strategies
      🧠 Insight line

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
    r_sign = _pnl_sign(realized_pnl)
    u_sign = _pnl_sign(unrealized_pnl)

    positions_str = f"{open_positions}" if open_positions > 0 else "0 (IDLE)"
    lat_str = f"{latency_ms:.0f}ms" if latency_ms is not None else "N/A"
    mkts_str = str(markets_count) if markets_count is not None else "N/A"

    if open_positions > 0:
        insight_text = f"Monitoring {open_positions} position{'s' if open_positions != 1 else ''}"
    elif not active_strategies:
        insight_text = "Market efficient, waiting edge"
    else:
        insight_text = "Scanning markets"

    lines = [
        f"🚀 *KRUSADER AI {version}*",
        _SEP,
        "⚙️ *SYSTEM*",
        _SEP_THIN,
        render_kv_line("STATE", f"{state_dot} {system_state.upper()}"),
        render_kv_line("MODE", f"{mode_icon} {mode.upper()}"),
        render_kv_line("MARKETS", mkts_str),
        render_kv_line("LATENCY", lat_str),
        _SEP,
        "💼 *PORTFOLIO*",
        _SEP_THIN,
        render_kv_line("BALANCE", f"${wallet_cash:,.2f}"),
        render_kv_line("EQUITY", f"${wallet_equity:,.2f}"),
        render_kv_line("POSITIONS", positions_str),
        _SEP,
        "📈 *PERFORMANCE*",
        _SEP_THIN,
        render_kv_line("REALIZED", f"{r_sign}${realized_pnl:,.4f}"),
        render_kv_line("UNREALIZED", f"{u_sign}${unrealized_pnl:,.4f}"),
        _SEP,
        "🧠 *STRATEGY ENGINE*",
        _SEP_THIN,
    ]

    if active_strategies:
        for strat in active_strategies:
            lines.append(f"● {strat.upper().replace('_', ' ')}")
    else:
        lines.append("_No strategies active_")

    lines += [
        _SEP,
        render_insight(insight_text),
    ]

    return "\n".join(lines)


# ── Positions Summary ─────────────────────────────────────────────────────────


def render_positions_summary(
    positions: list[dict],
    wallet_equity: float,
    market_cache_fn=None,
    status_bar: Optional[str] = None,
) -> str:
    """Render a full exposure / positions list (STYLE B).

    Aggregate metrics shown in LABEL ● VALUE format, followed by per-position
    cards, and a contextual insight line at the bottom.

    Args:
        positions:       List of position dicts with keys:
                         market_id, market_question, side, size,
                         unrealized_pnl, entry_price, exposure_pct.
        wallet_equity:   Total portfolio equity (used for exposure %).
        market_cache_fn: Unused — question must already be resolved in dict.
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
            render_kv_line("POSITIONS", "0 (IDLE)"),
            render_kv_line("EXPOSURE", "$0.00"),
            _SEP,
            render_insight("No open positions — scanning markets"),
        ]
        return "\n".join(lines)

    total_exposure = sum(p.get("size", 0.0) for p in positions)
    total_unrealized = sum(p.get("unrealized_pnl", 0.0) for p in positions)
    exposure_pct = (total_exposure / wallet_equity * 100) if wallet_equity > 0 else 0.0
    u_sign = _pnl_sign(total_unrealized)

    lines += [
        "📉 *EXPOSURE & POSITIONS*",
        _SEP,
        render_kv_line("TOTAL EXP", f"${total_exposure:,.2f}"),
        render_kv_line("EXPOSURE", f"{exposure_pct:.1f}%"),
        render_kv_line("POSITIONS", str(len(positions))),
        render_kv_line("UNREALIZED", f"{u_sign}${total_unrealized:,.4f}"),
        _SEP,
        "*Positions:*",
        "",
    ]

    for pos in positions:
        p_pnl = pos.get("unrealized_pnl", 0.0)
        p_sign = _pnl_sign(p_pnl)
        p_icon = _pnl_color(p_pnl)
        side = pos.get("side", "?")
        side_icon = "🟢" if side.upper() in ("YES", "BUY") else "🔴"
        market_q = pos.get("market_question") or pos.get("market_id", "N/A")
        market_label = _truncate(market_q, 36)
        lines.append(
            f"{side_icon} _{market_label}_\n"
            f"   {side.upper()} · `${pos.get('size', 0):.2f}` · {p_icon}`{p_sign}${p_pnl:.4f}`"
        )

    insight_text = f"Monitoring {len(positions)} position{'s' if len(positions) != 1 else ''}"
    lines += ["", _SEP, render_insight(insight_text)]
    return "\n".join(lines)
