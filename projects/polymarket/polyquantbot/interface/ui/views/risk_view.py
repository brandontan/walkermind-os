"""RISK premium dashboard view."""
from __future__ import annotations

from typing import Any, Mapping

from .helpers import SEPARATOR, block, fmt


TITLE = "🛡️ RISK"
SUBTITLE = "Polymarket AI Trader"


def _risk_insight(level: str, profile: str) -> str:
    lv = level.lower()
    pf = profile.lower()
    if "low" in lv or "conservative" in pf:
        return "Low exposure • Safe positioning"
    if "high" in lv or "aggressive" in pf:
        return "1 position open • Monitoring"
    return "No active trades • Waiting signal"


def render_risk_view(data: Mapping[str, Any]) -> str:
    kelly = fmt(data.get("kelly", "0.25f"))
    level = fmt(data.get("level"))
    profile = fmt(data.get("profile"))

    sections = [
        f"{TITLE}\n{SUBTITLE}",
        block("Kelly", kelly, "Fractional Kelly"),
        block("Risk Level", level, "Risk Level"),
        block("Risk Profile", profile, "Risk Profile"),
        block("Rule", "Fractional Kelly only", "Risk Guardrail"),
        f"🧠 Insight\n{_risk_insight(level, profile)}",
    ]
    return f"\n{SEPARATOR}\n".join(sections)
