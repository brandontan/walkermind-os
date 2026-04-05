"""POSITIONS premium dashboard view."""
from __future__ import annotations

from typing import Any, Mapping

from .helpers import SEPARATOR, fmt, row


def _compact_position(item: Any) -> str:
    text = fmt(item)
    if text == "—":
        return text
    return text if len(text) <= 42 else f"{text[:39]}..."


def render_positions_view(data: Mapping[str, Any]) -> str:
    raw_lines = data.get("position_lines")
    items = raw_lines if isinstance(raw_lines, list) else []

    lines = ["📊 POSITIONS", row("Open", len(items))]
    if not items:
        lines.extend([SEPARATOR, row("Status", "No open positions"), SEPARATOR, "🧠 Insight  Entries will appear after first fill."])
        return "\n".join(lines)

    lines.append(SEPARATOR)
    for idx, item in enumerate(items[:5], start=1):
        lines.append(row(f"Pos {idx}", _compact_position(item)))
    lines.extend([SEPARATOR, "🧠 Insight  Top positions shown for quick scan."])
    return "\n".join(lines)
