"""HOME unified premium hierarchy dashboard view."""
from __future__ import annotations

from typing import Any, Mapping

from ..formatters.premium_formatter import block, divider, format_count, format_market, format_money, format_percent, item, item_last, section


def render_home_view(data: Mapping[str, Any]) -> str:
    lines = [section("🏠 HOME")]
    lines.extend(format_market(data))
    lines.extend([
        "",
        "💼 Portfolio",
        item("Balance", format_money(data.get("balance", data.get("cash", 0.0)))),
        item("Equity", format_money(data.get("equity", 0.0))),
        item_last("Positions", format_count(data.get("positions", data.get("open_positions", 0)))),
        "",
        "📉 Market Exposure",
        item("Ratio", format_percent(data.get("ratio", data.get("exposure_ratio", 0.0)))),
        item_last("Value", format_money(data.get("total_exposure", data.get("exposure", 0.0)))),
        "",
        "💰 Profit / Loss",
        item_last("Total", format_money(data.get("total_pnl", data.get("pnl", 0.0)))),
        "",
        "🧠 Insight",
        "└─ Unified premium dashboard active",
        divider(),
    ])
    return block(lines)
