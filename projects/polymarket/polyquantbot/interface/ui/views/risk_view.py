"""RISK compact view."""
from __future__ import annotations

from typing import Any, Mapping

from ..ui_blocks import format_block, format_row


def render_risk_view(data: Mapping[str, Any]) -> str:
    rows = [
        format_row("kelly", str(data.get("kelly", "0.25f"))),
        format_row("level", str(data.get("level", "N/A"))),
        format_row("profile", str(data.get("profile", "Balanced"))),
    ]
    return format_block("🛡 RISK", rows)
