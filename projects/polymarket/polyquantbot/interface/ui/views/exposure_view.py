"""EXPOSURE premium view with compact position rows."""
from __future__ import annotations

from typing import Any, Mapping

from ..ui_blocks import format_position_lines, row, section


def _short_market_id(value: object) -> str:
    text = str(value or "—").strip()
    if len(text) <= 12:
        return text
    return f"{text[:6]}...{text[-3:]}"


def render_exposure_view(data: Mapping[str, Any]) -> str:
    summary_rows = [
        row("Total Exp", data.get("total_exposure", data.get("exposure"))),
        row("Exposure", data.get("ratio")),
        row("Positions", data.get("positions")),
        row("Unrealized", data.get("unrealized")),
    ]

    position_items = data.get("position_lines")
    safe_lines = format_position_lines(position_items if isinstance(position_items, list) else [])
    compact_rows = [row(f"Pos {idx + 1}", _short_market_id(item)) for idx, item in enumerate(safe_lines[:3])]
    if not compact_rows:
        compact_rows = [row("Status", "No open positions")]

    insight_rows = [row("Summary", "Exposure concentrated in top positions; keep liquidity coverage active.")]

    return "\n\n".join(
        [
            section("📉 EXPOSURE", summary_rows),
            section("📊 POSITIONS", compact_rows),
            section("🧠 INSIGHT", insight_rows),
        ]
    )
