"""POSITIONS premium dashboard view."""
from __future__ import annotations

from typing import Any, Mapping

from .helpers import SEPARATOR, block, fmt


TITLE = "📊 POSITIONS"
SUBTITLE = "Polymarket AI Trader"


def _compact_position(item: Any) -> str:
    text = fmt(item)
    if text == "—":
        return text
    return text if len(text) <= 54 else f"{text[:51]}..."


def _positions_insight(count: int) -> str:
    if count == 0:
        return "No active trades • Waiting signal"
    if count == 1:
        return "1 position open • Monitoring"
    return "Low exposure • Safe positioning" if count <= 3 else f"{count} positions open • Monitoring"


def render_positions_view(data: Mapping[str, Any]) -> str:
    raw_lines = data.get("position_lines")
    items = raw_lines if isinstance(raw_lines, list) else []
    count = len(items)

    sections = [
        f"{TITLE}\n{SUBTITLE}",
        block("Open Positions", count, "Open Positions"),
    ]

    if count == 0:
        sections.append(block("Status", "No open positions", "Position Status"))
        sections.append(f"🧠 Insight\n{_positions_insight(count)}")
        return f"\n{SEPARATOR}\n".join(sections)

    for idx, item in enumerate(items[:5], start=1):
        sections.append(block(f"Position {idx}", _compact_position(item), f"Position {idx}"))

    sections.append(f"🧠 Insight\n{_positions_insight(count)}")
    return f"\n{SEPARATOR}\n".join(sections)
