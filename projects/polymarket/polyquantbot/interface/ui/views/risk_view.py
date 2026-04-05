"""RISK premium dashboard view."""
from __future__ import annotations

from typing import Any, Mapping

from .helpers import SEPARATOR, fmt, row


def render_risk_view(data: Mapping[str, Any]) -> str:
    kelly = fmt(data.get("kelly", "0.25f"))
    level = fmt(data.get("level"))
    profile = fmt(data.get("profile"))

    lines = [
        "🛡️ RISK",
        row("Kelly", kelly),
        row("Level", level),
        row("Profile", profile),
        SEPARATOR,
        row("Rule", "Fractional Kelly only"),
        SEPARATOR,
        "🧠 Insight  Kelly 0.25f limits variance while preserving edge.",
    ]
    return "\n".join(lines)
