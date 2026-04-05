"""HOME premium dashboard view."""
from __future__ import annotations

from typing import Any, Mapping

from ..ui_blocks import row, section


def render_home_view(data: Mapping[str, Any]) -> str:
    system_rows = [
        row("State", data.get("status")),
        row("Mode", data.get("mode")),
        row("Latency", data.get("latency")),
    ]
    portfolio_rows = [
        row("Balance", data.get("balance")),
        row("Equity", data.get("equity")),
        row("Positions", data.get("positions")),
    ]
    performance_rows = [
        row("Realized", data.get("realized")),
        row("Unrealized", data.get("unrealized")),
    ]
    insight_rows = [
        row("Summary", data.get("insight", "Portfolio and system telemetry synced.")),
    ]

    return "\n\n".join(
        [
            section("🏠 HOME", system_rows),
            section("💼 PORTFOLIO", portfolio_rows),
            section("📈 PERFORMANCE", performance_rows),
            section("🧠 INSIGHT", insight_rows),
        ]
    )
