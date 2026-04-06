"""Refactored Premium UI Formatter (Production-Ready)."""

from __future__ import annotations

from projects.polymarket.polyquantbot.data.market_context import get_market_context


# =========================
# SAFETY HELPERS
# =========================

def _safe_float(value: object) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _safe_str(value: object) -> str:
    return str(value) if value is not None else "N/A"


# =========================
# EMOJI SYSTEM
# =========================

EMOJI = {
    "equity": "💰",
    "positions": "📦",
    "exposure": "📊",
    "insight": "🧠",
    "risk": "⚠️",
    "action": "💡",
    "system": "⚙️",
}


# =========================
# CORE UI BUILDERS
# =========================

def _divider(title: str) -> str:
    return f"━━━━━━━━━━━━━━\n{title}\n━━━━━━━━━━━━━━"


def _pnl(pnl: float) -> str:
    pnl = _safe_float(pnl)
    if pnl > 0:
        return f"🟢 +{pnl:.2f}"
    if pnl < 0:
        return f"🔴 {pnl:.2f}"
    return "🟡 0.00"


# =========================
# BLOCKS
# =========================

def render_system(state: object, mode: object) -> str:
    return (
        _divider(f"{EMOJI['system']} SYSTEM")
        + "\n"
        + f"State : {_safe_str(state)}\n"
        + f"Mode  : {_safe_str(mode)}"
    )


def render_portfolio(equity: object, positions: object, exposure: object) -> str:
    equity_value = _safe_float(equity)
    exposure_value = _safe_float(exposure)

    return (
        _divider(f"{EMOJI['equity']} PORTFOLIO")
        + "\n"
        + f"Equity    : ${equity_value:,.2f}\n"
        + f"Positions : {_safe_float(positions):.0f}\n"
        + f"Exposure  : {exposure_value:.1%}"
    )


async def render_position(
    market_id: object,
    side: object,
    entry: object,
    size: object,
    pnl: object,
) -> str:
    context = await get_market_context(market_id) or {}
    name = context.get("name", "Unknown Market")

    entry_value = _safe_float(entry)
    size_value = _safe_float(size)
    pnl_value = _safe_float(pnl)

    return (
        _divider(f"{EMOJI['positions']} POSITION")
        + "\n"
        + f"Market : {name}\n"
        + f"Side   : {_safe_str(side)}\n"
        + f"Entry  : ${entry_value:,.2f}\n"
        + f"Size   : ${size_value:,.2f}\n"
        + f"PnL    : {_pnl(pnl_value)}"
    )


def render_risk(drawdown: object) -> str:
    dd = _safe_float(drawdown)
    return _divider(f"{EMOJI['risk']} RISK") + "\n" + f"Drawdown : {dd:.1%}"


def render_insight(text: object) -> str:
    return _divider(f"{EMOJI['insight']} INSIGHT") + "\n" + f"{_safe_str(text)}"


def render_decision(text: object) -> str:
    return _divider(f"{EMOJI['action']} DECISION") + "\n" + f"{_safe_str(text)}"


# =========================
# SINGLE ENTRY POINT
# =========================

async def render_dashboard(data: dict) -> str:
    """ONLY ENTRY POINT — do not bypass this."""

    blocks: list[str] = []

    blocks.append(render_system(data.get("state"), data.get("mode")))

    blocks.append(
        render_portfolio(data.get("equity"), data.get("positions"), data.get("exposure"))
    )

    if data.get("market_id"):
        blocks.append(
            await render_position(
                data.get("market_id"),
                data.get("side"),
                data.get("entry"),
                data.get("size"),
                data.get("pnl"),
            )
        )

    blocks.append(render_risk(data.get("drawdown")))
    blocks.append(render_insight(data.get("insight")))
    blocks.append(render_decision(data.get("decision")))

    return "\n\n".join(blocks)
