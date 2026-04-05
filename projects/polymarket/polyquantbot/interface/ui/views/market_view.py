"""MARKET premium dashboard view."""
from __future__ import annotations

from typing import Any, Mapping

from .helpers import SEPARATOR, block, fmt


TITLE = "📡 MARKET"
SUBTITLE = "Polymarket AI Trader"


def _to_int(value: Any) -> str:
    try:
        return str(int(float(value)))
    except (TypeError, ValueError):
        return "—"


def _market_insight(signal: str, scanned: str) -> str:
    if signal == "—":
        return "No active trades • Waiting signal"

    try:
        scan_count = int(scanned)
    except (TypeError, ValueError):
        scan_count = 0

    if scan_count > 0:
        return "Low exposure • Safe positioning"
    return "1 position open • Monitoring"


def render_market_view(data: Mapping[str, Any]) -> str:
    opportunities = data.get("top_opportunities") if isinstance(data.get("top_opportunities"), list) else []
    top_name = "—"
    if opportunities and isinstance(opportunities[0], Mapping):
        top_name = fmt(opportunities[0].get("name"))

    scanned = _to_int(data.get("total_markets"))
    dominant_signal = fmt(data.get("dominant_signal"))

    sections = [
        f"{TITLE}\n{SUBTITLE}",
        block("Scanned", scanned, "Markets Scanned"),
        block("Active", _to_int(data.get("active_markets")), "Active Markets"),
        block("Signal", dominant_signal, "Dominant Signal"),
        block("Top Market", top_name, "Top Opportunity"),
        block("Edge Type", data.get("top_edge_type"), "Edge Type"),
        f"🧠 Insight\n{_market_insight(dominant_signal, scanned)}",
    ]
    return f"\n{SEPARATOR}\n".join(sections)
