"""PERFORMANCE unified premium hierarchy dashboard view."""
from __future__ import annotations

from typing import Any, Mapping

from ..formatters.premium_formatter import block, divider, format_count, format_market, format_money, format_percent, item, item_last, section


def render_performance_view(data: Mapping[str, Any]) -> str:
    lines = [section("📈 PERFORMANCE")]
    lines.extend(format_market(data))
    lines.extend([
        "",
        "💰 Profit / Loss",
        item("Total", format_money(data.get("total_pnl", data.get("pnl", 0.0)))),
        item_last("Unrealized", format_money(data.get("unrealized", 0.0))),
        "",
        "📊 Trading Quality",
        item("Trades", format_count(data.get("trades", data.get("total_trades", 0)))),
        item("Win Rate", format_percent(data.get("win_rate", 0.0))),
        item_last("Drawdown", format_percent(data.get("drawdown", 0.0))),
        "",
        "🧠 Insight",
        "└─ Performance telemetry synchronized",
        divider(),
    ])
    return block(lines)
