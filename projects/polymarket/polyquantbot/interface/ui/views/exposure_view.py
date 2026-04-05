"""EXPOSURE premium dashboard view."""
from __future__ import annotations

from typing import Any, Mapping

from .helpers import SEPARATOR, block, pnl


TITLE = "📉 EXPOSURE"
SUBTITLE = "Polymarket AI Trader"


def _exposure_insight(positions: Any, exposure: Any) -> str:
    try:
        count = int(float(positions))
    except (TypeError, ValueError):
        count = 0

    if count == 0:
        return "No active trades • Waiting signal"

    unrealized = pnl(exposure)
    if unrealized.startswith("+"):
        return "Low exposure • Safe positioning"
    return "1 position open • Monitoring" if count == 1 else f"{count} positions open • Monitoring"


def render_exposure_view(data: Mapping[str, Any]) -> str:
    positions = data.get("positions", 0)
    total_exposure = data.get("total_exposure", data.get("exposure"))

    sections = [
        f"{TITLE}\n{SUBTITLE}",
        block("Total Exposure", total_exposure, "Total Exposure"),
        block("Exposure Ratio", data.get("ratio"), "Portfolio Ratio"),
        block("Open Positions", positions, "Open Positions"),
        block("Unrealized PnL", pnl(data.get("unrealized")), "Unrealized PnL"),
        f"🧠 Insight\n{_exposure_insight(positions, data.get('unrealized'))}",
    ]
    return f"\n{SEPARATOR}\n".join(sections)
