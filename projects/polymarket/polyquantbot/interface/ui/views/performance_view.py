"""PERFORMANCE product dashboard view."""
from __future__ import annotations

from typing import Any, Mapping

from .helpers import SEPARATOR, block, generate_insight, pnl


TITLE = "📈 PERFORMANCE"
SUBTITLE = "Polymarket AI Trader"


def render_performance_view(data: Mapping[str, Any]) -> str:
    total_pnl = data.get("total_pnl", data.get("pnl", 0.0))
    unrealized = data.get("unrealized", 0.0)

    sections = [
        f"{TITLE}\n{SUBTITLE}",
        block(pnl(total_pnl), "Total PnL"),
        block(pnl(unrealized), "Unrealized"),
        block(data.get("trades", data.get("total_trades")), "Trades"),
        f"🧠 Insight\n{generate_insight(data)}",
    ]
    return f"\n{SEPARATOR}\n".join(sections)
