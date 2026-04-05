"""Refactored Premium UI Formatter (Production-Ready)""" from future import annotations from typing import Optional

from projects.polymarket.polyquantbot.data.market_context import get_market_context

=========================

SAFETY HELPERS

=========================

def _safe_float(x) -> float: try: return float(x) except Exception: return 0.0

def _safe_str(x) -> str: return str(x) if x is not None else "N/A"

=========================

EMOJI SYSTEM

=========================

EMOJI = { "equity": "💰", "positions": "📦", "exposure": "📊", "insight": "🧠", "risk": "⚠️", "action": "💡", "system": "⚙️", }

=========================

CORE UI BUILDERS

=========================

def _divider(title: str) -> str: return f"━━━━━━━━━━━━━━\n{title}\n━━━━━━━━━━━━━━"

def _pnl(pnl: float) -> str: pnl = _safe_float(pnl) if pnl > 0: return f"🟢 +{pnl:.2f}" elif pnl < 0: return f"🔴 {pnl:.2f}" return "🟡 0.00"

=========================

BLOCKS

=========================

def render_system(state: str, mode: str) -> str: return ( _divider(f"{EMOJI['system']} SYSTEM") + "\n" f"State : {_safe_str(state)}\n" f"Mode  : {_safe_str(mode)}" )

def render_portfolio(equity, positions, exposure) -> str: equity = _safe_float(equity) exposure = _safe_float(exposure)

return (
    _divider(f"{EMOJI['equity']} PORTFOLIO") + "\n"
    f"Equity    : ${equity:,.2f}\n"
    f"Positions : {_safe_float(positions):.0f}\n"
    f"Exposure  : {exposure:.1%}"
)

async def render_position(market_id, side, entry, size, pnl) -> str: context = await get_market_context(market_id) or {}

name = context.get("name", "Unknown Market")

entry = _safe_float(entry)
size = _safe_float(size)
pnl = _safe_float(pnl)

return (
    _divider(f"{EMOJI['positions']} POSITION") + "\n"
    f"Market : {name}\n"
    f"Side   : {_safe_str(side)}\n"
    f"Entry  : ${entry:,.2f}\n"
    f"Size   : ${size:,.2f}\n"
    f"PnL    : {_pnl(pnl)}"
)

def render_risk(drawdown) -> str: dd = _safe_float(drawdown) return ( _divider(f"{EMOJI['risk']} RISK") + "\n" f"Drawdown : {dd:.1%}" )

def render_insight(text: str) -> str: return ( _divider(f"{EMOJI['insight']} INSIGHT") + "\n" f"{_safe_str(text)}" )

def render_decision(text: str) -> str: return ( _divider(f"{EMOJI['action']} DECISION") + "\n" f"{_safe_str(text)}" )

=========================

SINGLE ENTRY POINT

=========================

async def render_dashboard(data: dict) -> str: """ONLY ENTRY POINT — do not bypass this."""

blocks = []

# SYSTEM
blocks.append(render_system(
    data.get("state"),
    data.get("mode")
))

# PORTFOLIO
blocks.append(render_portfolio(
    data.get("equity"),
    data.get("positions"),
    data.get("exposure")
))

# POSITION (optional)
if data.get("market_id"):
    blocks.append(await render_position(
        data.get("market_id"),
        data.get("side"),
        data.get("entry"),
        data.get("size"),
        data.get("pnl")
    ))

# RISK
blocks.append(render_risk(data.get("drawdown")))

# INSIGHT
blocks.append(render_insight(data.get("insight")))

# DECISION
blocks.append(render_decision(data.get("decision")))

return "\n\n".join(blocks)
