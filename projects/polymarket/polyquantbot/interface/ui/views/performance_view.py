"""PERFORMANCE premium metrics view."""
from __future__ import annotations

from typing import Any, Mapping

from ..ui_blocks import row, section


def render_performance_view(data: Mapping[str, Any]) -> str:
    rows = [
        row("Total PnL", data.get("total_pnl", data.get("pnl"))),
        row("Win Rate", data.get("winrate", data.get("wr"))),
        row("Trades", data.get("trades", data.get("total_trades"))),
        row("Drawdown", data.get("drawdown")),
    ]
    insight = [row("Summary", data.get("insight", "Risk-adjusted returns are within current guardrails."))]
    return "\n\n".join([section("📈 PERFORMANCE", rows), section("🧠 INSIGHT", insight)])
