"""PERFORMANCE compact metrics view."""
from __future__ import annotations

from typing import Any, Mapping

from ..ui_blocks import row, section


def render_performance_view(data: Mapping[str, Any]) -> str:
    rows = [
        row("Total PnL", str(data.get("total_pnl", data.get("pnl", "N/A")))),
        row("Winrate", str(data.get("winrate", data.get("wr", "N/A")))),
        row("Trades", str(data.get("trades", data.get("total_trades", "N/A")))),
        row("Drawdown", str(data.get("drawdown", "N/A"))),
    ]
    return section("PERFORMANCE", rows)
