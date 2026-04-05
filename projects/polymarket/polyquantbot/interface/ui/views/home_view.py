"""HOME premium dashboard view."""
from __future__ import annotations

from typing import Any, Mapping

from .helpers import SEPARATOR, fmt, pnl, row


def render_home_view(data: Mapping[str, Any]) -> str:
    insight = fmt(data.get("insight"))
    if insight == "—":
        insight = "System synced and scanning for edge."

    lines = [
        "🏠 PREMIUM HOME",
        row("State", data.get("status")),
        row("Mode", data.get("mode")),
        row("Latency", data.get("latency")),
        SEPARATOR,
        row("Balance", data.get("balance")),
        row("Equity", data.get("equity")),
        row("Positions", data.get("positions")),
        SEPARATOR,
        row("Realized", pnl(data.get("realized"))),
        row("Unrealized", pnl(data.get("unrealized"))),
        SEPARATOR,
        f"🧠 Insight  {insight}",
    ]
    return "\n".join(lines)
