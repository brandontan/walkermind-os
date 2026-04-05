"""HOME summary view."""
from __future__ import annotations

from typing import Any, Mapping

from ..ui_blocks import format_block, format_insight, format_row


def render_home_view(data: Mapping[str, Any]) -> str:
    system_rows = [
        format_row("status", str(data.get("status", "N/A"))),
        format_row("mode", str(data.get("mode", "N/A"))),
        format_row("markets", str(data.get("markets", "N/A"))),
    ]
    portfolio_rows = [
        format_row("positions", str(data.get("positions", "N/A"))),
        format_row("exposure", str(data.get("exposure", "N/A"))),
        format_row("unrealized", str(data.get("unrealized", "N/A"))),
    ]
    performance_rows = [
        format_row("pnl", str(data.get("pnl", "N/A"))),
        format_row("winrate", str(data.get("winrate", "N/A"))),
        format_row("drawdown", str(data.get("drawdown", "N/A"))),
    ]

    return "\n\n".join([
        format_block("🧭 SYSTEM", system_rows),
        format_block("💼 PORTFOLIO", portfolio_rows),
        format_block("📈 PERFORMANCE", performance_rows),
        format_insight(str(data.get("insight", "N/A"))),
    ])
