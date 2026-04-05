"""POSITIONS product dashboard view."""
from __future__ import annotations

from typing import Any, Mapping

from .helpers import SEPARATOR, block, fmt, generate_insight


TITLE = "📊 POSITIONS"
SUBTITLE = "Polymarket AI Trader"


def _top_position(item: Any) -> str:
    text = fmt(item)
    if text == "—":
        return text
    return text if len(text) <= 56 else f"{text[:53]}..."


def render_positions_view(data: Mapping[str, Any]) -> str:
    raw_lines = data.get("position_lines")
    items = raw_lines if isinstance(raw_lines, list) else []
    count = len(items)

    sections = [
        f"{TITLE}\n{SUBTITLE}",
        block(count, "Open Positions"),
        block(_top_position(items[0]) if count else "No open positions", "Top Position"),
        block(_top_position(items[1]) if count > 1 else "—", "Second Position"),
        f"🧠 Insight\n{generate_insight({**data, 'positions': count})}",
    ]
    return f"\n{SEPARATOR}\n".join(sections)
