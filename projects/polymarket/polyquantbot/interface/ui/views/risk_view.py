"""RISK product dashboard view."""
from __future__ import annotations

from typing import Any, Mapping

from .helpers import SEPARATOR, block, fmt, generate_insight


TITLE = "🛡️ RISK"
SUBTITLE = "Polymarket AI Trader"


def render_risk_view(data: Mapping[str, Any]) -> str:
    kelly = fmt(data.get("kelly", "0.25f"))

    sections = [
        f"{TITLE}\n{SUBTITLE}",
        block(kelly, "Kelly Fraction"),
        block(data.get("level"), "Risk Level"),
        block("Fractional Kelly only", "Risk Rule"),
        f"🧠 Insight\n{generate_insight(data)}",
    ]
    return f"\n{SEPARATOR}\n".join(sections)
