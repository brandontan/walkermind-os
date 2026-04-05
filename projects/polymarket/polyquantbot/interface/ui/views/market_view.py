"""MARKET product dashboard view."""
from __future__ import annotations

from typing import Any, Mapping

from .helpers import SEPARATOR, block, fmt, generate_insight


TITLE = "📡 MARKET"
SUBTITLE = "Polymarket AI Trader"


def _to_int(value: Any) -> str:
    try:
        return str(int(float(value)))
    except (TypeError, ValueError):
        return "—"


def render_market_view(data: Mapping[str, Any]) -> str:
    opportunities = data.get("top_opportunities") if isinstance(data.get("top_opportunities"), list) else []
    top_name = "—"
    if opportunities and isinstance(opportunities[0], Mapping):
        top_name = fmt(opportunities[0].get("name"))

    sections = [
        f"{TITLE}\n{SUBTITLE}",
        block(_to_int(data.get("total_markets")), "Markets Scanned"),
        block(_to_int(data.get("active_markets")), "Active Markets"),
        block(top_name, "Top Opportunity"),
        f"🧠 Insight\n{generate_insight(data)}",
    ]
    return f"\n{SEPARATOR}\n".join(sections)
