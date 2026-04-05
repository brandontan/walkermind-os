"""RISK premium control view."""
from __future__ import annotations

from typing import Any, Mapping

from ..ui_blocks import section, row


def render_risk_view(data: Mapping[str, Any]) -> str:
    rows = [
        row("Kelly", data.get("kelly", "0.25f")),
        row("Level", data.get("level")),
        row("Profile", data.get("profile", "Balanced")),
    ]
    insight_rows = [row("Summary", "Risk engine active: fractional Kelly and drawdown limits enforced.")]
    return "\n\n".join([section("🛡️ RISK", rows), section("🧠 INSIGHT", insight_rows)])
