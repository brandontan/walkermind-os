"""EXPOSURE product dashboard view."""
from __future__ import annotations

from typing import Any, Mapping

from .helpers import SEPARATOR, block, generate_insight, pnl


TITLE = "📉 EXPOSURE"
SUBTITLE = "Polymarket AI Trader"


def render_exposure_view(data: Mapping[str, Any]) -> str:
    total_exposure = data.get("total_exposure", data.get("exposure"))

    sections = [
        f"{TITLE}\n{SUBTITLE}",
        block(total_exposure, "Total Exposure"),
        block(data.get("ratio", data.get("exposure_ratio")), "Exposure Ratio"),
        block(pnl(data.get("unrealized")), "Unrealized"),
        f"🧠 Insight\n{generate_insight(data)}",
    ]
    return f"\n{SEPARATOR}\n".join(sections)
