"""PERFORMANCE compact metrics view."""
from __future__ import annotations

from typing import Any, Mapping

from ..ui_blocks import format_block, format_row


def render_performance_view(data: Mapping[str, Any]) -> str:
    rows = [
        format_row("pnl", str(data.get("pnl", data.get("total_pnl", "N/A")))),
        format_row("winrate", str(data.get("winrate", data.get("wr", "N/A")))),
        format_row("trades", str(data.get("trades", data.get("total_trades", "N/A")))),
        format_row("drawdown", str(data.get("drawdown", "N/A"))),
    ]
    return format_block("📊 PERFORMANCE", rows)
