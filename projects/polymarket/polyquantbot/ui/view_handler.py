from typing import List, Dict
import structlog

log = structlog.get_logger(__name__)


def format_tree(items: List[str], prefix: str = "") -> str:
    """Format items as a tree."""
    lines = []
    for i, item in enumerate(items):
        if i == len(items) - 1:
            lines.append(f"{prefix}└─ {item}")
        else:
            lines.append(f"{prefix}|- {item}")
    return "\n".join(lines)


def format_section(title: str, content: str) -> str:
    """Format a section with borders."""
    return f"━━━━━━━━━━━━━━\n{title}\n━━━━━━━━━━━━━━\n{content}"


def humanize_message(key: str, context: Dict) -> str:
    """Convert technical messages to human-readable."""
    messages = {
        "monitoring_positions": f"Tracking {context.get('count', 0)} active trades — within normal range",
        "market_against": "Market slightly moving against position",
        "edge_valid": "Edge still valid — holding",
        "no_trade": "No trade: insufficient edge",
    }
    return messages.get(key, key)


def render_portfolio_view(equity: float, positions: List[Dict]) -> str:
    """Render a portfolio view with tree structure."""
    position_items = [
        f"{pos['market_id']} ({pos['side']}) — Entry: {pos['entry_price']}, PnL: {pos['pnl']}"
        for pos in positions
    ]
    tree = format_tree([
        f"💰 Equity      ${equity:,.2f}",
        f"📦 Positions   {len(positions)}",
        *position_items
    ], "  ")
    return format_section("PORTFOLIO", tree)