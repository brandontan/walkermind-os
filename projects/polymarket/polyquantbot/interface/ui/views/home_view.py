"""HOME product dashboard view."""
from __future__ import annotations

from typing import Any, Mapping

from .helpers import SEPARATOR, block, generate_insight, pnl


TITLE = "🏠 HOME"
SUBTITLE = "Polymarket AI Trader"


def render_home_view(data: Mapping[str, Any]) -> str:
    latency = data.get("latency")

    sections = [
        f"{TITLE}\n{SUBTITLE}",
        block(data.get("balance"), "Balance"),
        block(data.get("positions"), "Open Positions"),
        block(pnl(data.get("total_pnl", data.get("pnl", 0.0))), "Total PnL"),
    ]

    if latency is not None:
        sections.append(block(latency, "Latency"))

    sections.append(f"🧠 Insight\n{generate_insight(data)}")
    return f"\n{SEPARATOR}\n".join(sections)
