"""Premium UI formatter for human-readable Telegram output."""
from __future__ import annotations
from typing import Dict, List, Optional, Union
import structlog

log = structlog.get_logger(__name__)

# Emoji mapping for semantic UI
EMOJI = {
    "equity": "💰",
    "positions": "📦",
    "exposure": "📊",
    "insight": "🧠",
    "risk": "⚠️",
    "action": "💡",
    "bullish": "📈",
    "bearish": "📉",
    "neutral": "🔄",
    "high": "🔥",
    "medium": "🟡",
    "low": "🟢",
    "waiting": "⏳",
    "active": "🚀",
    "notrade": "🛑",
}

# Market name mapping (fallback to ID if not found)
MARKET_NAMES = {
    "BTC-USD": "Bitcoin",
    "ETH-USD": "Ethereum",
    "SOL-USD": "Solana",
    "APT-USD": "Aptos",
}

def _divider(title: str) -> str:
    """Render a section divider with title."""
    return f"━━━━━━━━━━━━━━\n{title}\n━━━━━━━━━━━━━━"

def _hierarchy(items: List[str], prefix: str = "┣") -> str:
    """Render a hierarchy tree."""
    return "\n".join(f"{prefix} {item}" for item in items)

def _humanize_pnl(pnl: float) -> str:
    """Convert PnL to human-readable string with emoji."""
    if pnl > 0:
        return f"🟢 +{pnl:.2f}"
    elif pnl < 0:
        return f"🔴 {pnl:.2f}"
    return "🟡 0.00"

def _humanize_exposure(exposure: float) -> str:
    """Convert exposure to human-readable string."""
    if exposure < 0.1:
        return "Capital mostly idle, ready to deploy"
    elif exposure > 0.8:
        return "High exposure, consider reducing"
    return "Moderate exposure"

def _market_name(market_id: str) -> str:
    """Convert market_id to human-readable name."""
    return MARKET_NAMES.get(market_id, market_id)

def render_portfolio_block(equity: float, positions: int, exposure: float) -> str:
    """Render the portfolio block."""
    return (
        _divider(f"{EMOJI['equity']} PORTFOLIO") + "\n"
        f"{EMOJI['equity']} Equity: ${equity:,.2f}\n"
        f"{EMOJI['positions']} Active Positions: {positions}\n"
        f"{EMOJI['exposure']} Exposure: {exposure:.1%} ({_humanize_exposure(exposure)})"
    )

def render_market_insight(trend: str, edge: str, status: str) -> str:
    """Render the market insight block."""
    return (
        _divider(f"{EMOJI['insight']} MARKET INSIGHT") + "\n"
        f"{EMOJI['bullish' if trend == 'bullish' else 'bearish' if trend == 'bearish' else 'neutral']} Trend: {trend.capitalize()}\n"
        f"{EMOJI[edge]} Edge: {edge.capitalize()}\n"
        f"{EMOJI[status]} Status: {status.replace('_', ' ').capitalize()}"
    )

def render_active_position(market_id: str, side: str, entry_price: float, size: float, pnl: float) -> str:
    """Render the active position block."""
    return (
        _divider(f"{EMOJI['positions']} ACTIVE POSITION") + "\n"
        f"{EMOJI['positions']} Market: {_market_name(market_id)}\n"
        f"Side: {side}\n"
        f"Entry Price: ${entry_price:,.2f}\n"
        f"Size: ${size:,.2f}\n"
        f"PnL: {_humanize_pnl(pnl)}"
    )

def render_risk_status(exposure_safe: bool, position_safe: bool, drawdown: float) -> str:
    """Render the risk status block."""
    return (
        _divider(f"{EMOJI['risk']} RISK STATUS") + "\n"
        f"{EMOJI['risk']} Exposure Safe: {'✅' if exposure_safe else '❌'}\n"
        f"Position Size Safe: {'✅' if position_safe else '❌'}\n"
        f"Drawdown: {drawdown:.1%}"
    )

def render_bot_decision(decision: str) -> str:
    """Render the bot decision block."""
    return (
        _divider(f"{EMOJI['action']} BOT DECISION") + "\n"
        f"{EMOJI['action']} {decision.capitalize()}"
    )

def render_dashboard(
    equity: float,
    positions: int,
    exposure: float,
    trend: str,
    edge: str,
    status: str,
    market_id: Optional[str] = None,
    side: Optional[str] = None,
    entry_price: Optional[float] = None,
    size: Optional[float] = None,
    pnl: Optional[float] = None,
    exposure_safe: bool = True,
    position_safe: bool = True,
    drawdown: float = 0.0,
    decision: str = "waiting for opportunity",
) -> str:
    """Render the full dashboard."""
    blocks = [
        render_portfolio_block(equity, positions, exposure),
        render_market_insight(trend, edge, status),
    ]
    if market_id:
        blocks.append(
            render_active_position(market_id, side, entry_price, size, pnl)
        )
    blocks.extend([
        render_risk_status(exposure_safe, position_safe, drawdown),
        render_bot_decision(decision),
    ])
    return "\n\n".join(blocks)