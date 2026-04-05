"""RISK unified premium hierarchy dashboard view."""
from __future__ import annotations

from typing import Any, Mapping

from ..formatters.premium_formatter import block, divider, item, item_last, section


def render_risk_view(data: Mapping[str, Any]) -> str:
    kelly = data.get("kelly", "0.25f")
    lines = [section("🛡️ RISK")]
    lines.extend(
        [
            "🧩 Risk Controls",
            item("Kelly", kelly),
            item("Level", data.get("level", "Guarded")),
            item_last("Rule", "Fractional Kelly only"),
            "",
            "🧠 Insight",
            "└─ Runtime guardrails armed",
            divider(),
        ]
    )
    return block(lines)
