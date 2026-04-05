"""HOME unified premium hierarchy dashboard view."""
from __future__ import annotations

from typing import Any, Mapping

from ..formatters.premium_formatter import (
    block,
    divider,
    format_count,
    format_market,
    format_money,
    format_percent,
    format_pnl,
    item,
    item_last,
    section,
)


def render_home_view(data: Mapping[str, Any]) -> str:
    total_exposure = data.get("total_exposure", data.get("exposure", 0.0))
    equity = data.get("equity", 0.0)

    exposure_pct = 0.0
    try:
        equity_num = float(equity)
        exposure_num = float(total_exposure)
        exposure_pct = (exposure_num / equity_num * 100.0) if equity_num > 0 else 0.0
    except (TypeError, ValueError):
        exposure_pct = 0.0

    lines = [section("🏠 HOME")]
    lines.extend(
        [
            "━━━━━━━━━━━━━━",
            "🚀 KRUSADER AI",
            "━━━━━━━━━━━━━━",
            item("Equity", format_money(equity)),
            item("Positions", format_count(data.get("positions", data.get("open_positions", 0)))),
            item("Exposure %", f"{exposure_pct:.2f}%"),
            item_last("PnL", format_pnl(data.get("total_pnl", data.get("pnl", 0.0)))),
            "",
        ]
    )
    lines.extend(format_market(data))
    lines.extend(
        [
            "",
            "💼 Portfolio",
            item("Balance", format_money(data.get("balance", data.get("cash", 0.0)))),
            item("Equity", format_money(equity)),
            item_last("Positions", format_count(data.get("positions", data.get("open_positions", 0)))),
            "",
            "📉 Market Exposure",
            item("Ratio", format_percent(data.get("ratio", data.get("exposure_ratio", 0.0)))),
            item_last("Value", format_money(total_exposure)),
            "",
            "💰 Profit / Loss",
            item_last("Total", format_pnl(data.get("total_pnl", data.get("pnl", 0.0)))),
            "",
            "🧠 Insight",
            "└─ Elite dashboard hierarchy synchronized",
            divider(),
        ]
    )
    return block(lines)
