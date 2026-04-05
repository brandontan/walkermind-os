"""PORTFOLIO unified premium hierarchy dashboard view."""
from __future__ import annotations

from typing import Any, Mapping

from ..formatters.premium_formatter import block, divider, format_market, format_money, item, item_last, section


def render_portfolio_view(data: Mapping[str, Any]) -> str:
    lines = [section("💼 PORTFOLIO")]
    lines.extend(format_market(data))
    lines.extend([
        "",
        "💼 Account",
        item("Balance", format_money(data.get("balance", data.get("cash", 0.0)))),
        item("Equity", format_money(data.get("equity", 0.0))),
        item_last("Free Margin", format_money(data.get("free_margin", data.get("free", 0.0)))),
        "",
        "💰 Profit / Loss",
        item_last("Total", format_money(data.get("total_pnl", data.get("pnl", 0.0)))),
        "",
        "🧠 Insight",
        "└─ Portfolio state synchronized",
        divider(),
    ])
    return block(lines)
