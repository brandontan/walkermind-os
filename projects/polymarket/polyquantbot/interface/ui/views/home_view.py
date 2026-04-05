"""HOME summary view."""
from __future__ import annotations

from typing import Any, Mapping

from ..ui_blocks import row, section


def render_home_view(data: Mapping[str, Any]) -> str:
    system_rows = [
        row("State", str(data.get("status", "N/A"))),
        row("Mode", str(data.get("mode", "N/A"))),
        row("Latency", str(data.get("latency", "N/A"))),
    ]
    portfolio_rows = [
        row("Balance", str(data.get("balance", "N/A"))),
        row("Equity", str(data.get("equity", "N/A"))),
        row("Positions", str(data.get("positions", "N/A"))),
    ]
    performance_rows = [
        row("Realized", str(data.get("realized", "N/A"))),
        row("Unrealized", str(data.get("unrealized", "N/A"))),
    ]
    insight_text = row("Insight", str(data.get("insight", "N/A")))

    return "\n\n".join([
        section("SYSTEM", system_rows),
        section("PORTFOLIO", portfolio_rows),
        section("PERFORMANCE", performance_rows),
        section("Insight", [insight_text]),
    ])
