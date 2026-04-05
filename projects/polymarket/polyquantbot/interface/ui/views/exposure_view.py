"""EXPOSURE premium dashboard view."""
from __future__ import annotations

from typing import Any, Mapping

from .helpers import SEPARATOR, pnl, row


def render_exposure_view(data: Mapping[str, Any]) -> str:
    count = data.get("positions", 0)
    insight = "Exposure spread is within portfolio limits." if str(count) not in {"0", "—"} else "No open exposure; scan remains active."

    lines = [
        "📉 EXPOSURE",
        row("Total Exp", data.get("total_exposure", data.get("exposure"))),
        row("Ratio", data.get("ratio")),
        row("Positions", count),
        SEPARATOR,
        row("Unrealized", pnl(data.get("unrealized"))),
        SEPARATOR,
        f"🧠 Insight  {insight}",
    ]
    return "\n".join(lines)
