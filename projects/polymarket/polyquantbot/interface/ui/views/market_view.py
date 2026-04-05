"""MARKET premium dashboard view."""
from __future__ import annotations

from typing import Any, Mapping

from .helpers import SEPARATOR, fmt, row


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

    lines = [
        "📡 MARKET",
        row("Scanned", _to_int(data.get("total_markets"))),
        row("Active", _to_int(data.get("active_markets"))),
        row("Signal", data.get("dominant_signal")),
        SEPARATOR,
        row("Top", top_name),
        row("Edge", data.get("top_edge_type")),
        SEPARATOR,
        "🧠 Insight  Prioritize markets where edge and depth align.",
    ]
    return "\n".join(lines)
