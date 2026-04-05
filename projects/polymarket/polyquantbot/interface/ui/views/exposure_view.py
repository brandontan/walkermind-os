"""EXPOSURE view with compact position list."""
from __future__ import annotations

from typing import Any, Mapping

from ..ui_blocks import format_block, format_position_lines, format_row


def render_exposure_view(data: Mapping[str, Any]) -> str:
    summary_rows = [
        format_row("exposure", str(data.get("total_exposure", data.get("exposure", "N/A")))),
        format_row("ratio", str(data.get("ratio", "N/A"))),
        format_row("positions", str(data.get("positions", "N/A"))),
        format_row("unrealized", str(data.get("unrealized", "N/A"))),
    ]

    position_items = data.get("position_lines")
    if not isinstance(position_items, list):
        position_items = []
    compact_lines = [format_row(f"pos{i+1}", line) for i, line in enumerate(format_position_lines(position_items)[:5])]

    return "\n\n".join([
        format_block("📉 EXPOSURE", summary_rows),
        format_block("📌 POSITIONS", compact_lines),
    ])
