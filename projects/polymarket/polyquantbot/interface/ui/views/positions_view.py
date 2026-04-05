"""POSITIONS unified premium hierarchy dashboard view."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Mapping

from ..formatters.premium_formatter import format_position


def _to_position_obj(item: Mapping[str, Any]) -> Any:
    return SimpleNamespace(
        side=item.get("side", "NO"),
        entry_price=float(item.get("entry_price", item.get("avg_price", 0.0)) or 0.0),
        current_price=float(item.get("current_price", item.get("entry_price", item.get("avg_price", 0.0)) or 0.0)),
        size=float(item.get("size", 0.0) or 0.0),
        pnl=float(item.get("pnl", item.get("unrealized_pnl", 0.0)) or 0.0),
    )


def _to_market_obj(item: Mapping[str, Any]) -> Any:
    return SimpleNamespace(
        id=item.get("market_id", "N/A"),
        title=item.get("question", item.get("title", "N/A")),
        category=item.get("category", "N/A"),
    )


def render_positions_view(data: Mapping[str, Any]) -> str:
    positions = data.get("positions")
    if isinstance(positions, list) and positions:
        first = positions[0] if isinstance(positions[0], Mapping) else {}
    else:
        first = None

    if first is None:
        return "━━━━━━━━━━━━━━\n📊 POSITIONS\n━━━━━━━━━━━━━━\nNo active positions."

    return format_position(
        position=_to_position_obj(first),
        market=_to_market_obj(first),
    )
