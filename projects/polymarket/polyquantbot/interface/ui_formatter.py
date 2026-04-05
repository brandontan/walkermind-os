"""Premium UI formatter for human-readable Telegram output."""
from __future__ import annotations
from typing import List, Optional
import structlog

from data.market_context import get_market_context
from intelligence.insight_engine import generate_insight

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


def _divider(title: str) -> str:
    return f"━━━━━━━━━━━━━━\n{title}\n━━━━━━━━━━━━━━"


def _hierarchy(items: List[str], prefix: str = "┣") -> str:
    return "\n".join(f"{prefix} {item}" for item in items)


def _humanize_pnl(pnl: float) -> str:
    if pnl > 0:
        return f"🟢 +{pnl:.2f}"
    elif pnl < 0:
        return f"🔴 {pnl:.2f}"
    return "🟡 0.00"


def _humanize_exposure(exposure: float) -> str:
    if exposure < 0.1:
        return "Capital mostly idle, ready to deploy"
    elif exposure > 0.8:
        return "High exposure, consider reducing"
    return "Moderate exposure"


def render_portfolio_block(equity: float, positions: int, exposure: float) -> str:
    return (
        _divider(f"{EMOJI['equity']} PORTFOLIO") + "\n"
        f"{EMOJI['equity']} Equity: ${equity:,.2f}\n"
        f"{EMOJI['positions']} Active Positions: {positions}\n"
        f"{EMOJI['exposure']} Exposure: {exposure:.1%} ({_humanize_exposure(exposure)})"
    )


def render_market_insight_block(explanation: str, edge: str, trend: str) -> str:
    trend_key = trend if trend in EMOJI else "neutral"
    edge_key = edge.lower() if edge.lower() in EMOJI else "low"
    return (
        _divider(f"{EMOJI['insight']} MARKET INSIGHT") + "\n"
        f"{EMOJI[trend_key]} Trend: {trend.capitalize()}\n"
        f"{EMOJI[edge_key]} Edge: {edge}\n"
        f"{EMOJI['insight']} {explanation}"
    )


async def render_active_position(
    market_id: str,
    side: str,
    entry_price: float,
    size: float,
    pnl: float,
) -> str:
    context = await get_market_context(market_id)
    return (
        _divider(f"{EMOJI['positions']} ACTIVE POSITION") + "\n"
        f"{EMOJI['positions']} Market: {context['name']}\n"
        f"Category: {context['category']}\n"
        f"Resolve: {context['resolution']}\n"
        f"Side: {side}\n"
        f"Entry: ${entry_price:,.2f}\n"
        f"Size: ${size:,.2f}\n"
        f"PnL: {_humanize_pnl(pnl)}"
    )


def render_risk_status(exposure_safe: bool, position_safe: bool, drawdown: float) -> str:
    return (
        _divider(f"{EMOJI['risk']} RISK STATUS") + "\n"
        f"{EMOJI['risk']} Exposure Safe: {'✅' if exposure_safe else '❌'}\n"
        f"Position Size Safe: {'✅' if position_safe else '❌'}\n"
        f"Drawdown: {drawdown:.1%}"
    )


def render_bot_decision(decision: str) -> str:
    return (
        _divider(f"{EMOJI['action']} BOT DECISION") + "\n"
        f"{EMOJI['action']} {decision.capitalize()}"
    )


async def render_dashboard(
    equity: float,
    positions: int,
    exposure: float,
    trend: str = "neutral",
    edge: str = "low",
    status: str = "waiting",
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
    """Render the full dashboard with AI insight."""
    insight = generate_insight(
        pnl=pnl if pnl is not None else 0.0,
        exposure=exposure,
        drawdown=drawdown,
        position_count=positions,
    )

    blocks: List[str] = [
        render_portfolio_block(equity, positions, exposure),
        render_market_insight_block(insight.explanation, insight.edge, insight.trend),
    ]

    if market_id:
        blocks.append(
            await render_active_position(
                market_id,
                side or "N/A",
                entry_price or 0.0,
                size or 0.0,
                pnl or 0.0,
            )
        )

    blocks.extend([
        render_risk_status(exposure_safe, position_safe, drawdown),
        render_bot_decision(insight.decision),
    ])

    return "\n\n".join(blocks)
