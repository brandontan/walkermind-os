"""EXPOSURE view with compact summary and positions."""
from __future__ import annotations

from typing import Any, Mapping

from ..ui_blocks import format_position_lines, row, section


def _short_market_id(value: object) -> str:
    text = str(value or "N/A").strip()
    if len(text) <= 12:
        return text
    return f"{text[:6]}...{text[-3:]}"


def render_exposure_view(data: Mapping[str, Any]) -> str:
    summary_rows = [
        row("Total Exp", str(data.get("total_exposure", data.get("exposure", "N/A")))),
        row("Exposure", str(data.get("ratio", "N/A"))),
        row("Positions", str(data.get("positions", "N/A"))),
        row("Unrealized", str(data.get("unrealized", "N/A"))),
    ]

    position_items = data.get("position_lines")
    if not isinstance(position_items, list):
        position_items = []

    safe_lines = format_position_lines(position_items)
    compact_rows = []
    for idx, item in enumerate(safe_lines[:3]):
        compact_rows.append(row(f"Pos {idx+1}", _short_market_id(item)))

    return "\n\n".join([
        section("EXPOSURE", summary_rows),
        section("POSITIONS", compact_rows),
    ])
