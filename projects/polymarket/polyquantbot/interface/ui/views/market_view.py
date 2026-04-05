"""MARKET unified premium hierarchy dashboard view."""
from __future__ import annotations

from typing import Any, Mapping

from ..formatters.premium_formatter import block, divider, format_count, item, item_last, section


def render_market_view(data: Mapping[str, Any]) -> str:
    opportunities = data.get("top_opportunities") if isinstance(data.get("top_opportunities"), list) else []
    top_name = "—"
    if opportunities and isinstance(opportunities[0], Mapping):
        top_name = str(opportunities[0].get("name") or "—")

    lines = [section("📡 MARKET")]
    lines.extend(
        [
            "📊 Market Pulse",
            item("Scanned", format_count(data.get("total_markets"))),
            item("Active", format_count(data.get("active_markets"))),
            item_last("Top Setup", top_name),
            "",
            "🧠 Insight",
            "└─ Opportunity scanner synchronized",
            divider(),
        ]
    )
    return block(lines)
