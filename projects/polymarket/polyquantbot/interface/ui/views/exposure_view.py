"""EXPOSURE unified premium hierarchy dashboard view."""
from __future__ import annotations

from typing import Any, Mapping

from ..formatters.premium_formatter import block, divider, format_market, format_money, format_percent, item, item_last, section


def render_exposure_view(data: Mapping[str, Any]) -> str:
    lines = [section("📉 EXPOSURE")]
    lines.extend(format_market(data))
    lines.extend([
        "",
        "📉 Market Exposure",
        item("Total", format_money(data.get("total_exposure", data.get("exposure", 0.0)))),
        item("Ratio", format_percent(data.get("ratio", data.get("exposure_ratio", 0.0)))),
        item_last("Unrealized", format_money(data.get("unrealized", 0.0))),
        "",
        "🧠 Insight",
        "└─ Exposure monitored against limits",
        divider(),
    ])
    return block(lines)
