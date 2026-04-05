"""POSITIONS unified premium hierarchy dashboard view."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Mapping

from ..formatters.premium_formatter import block, format_position, section


def _to_position_obj(item: Mapping[str, Any]) -> Any:
    return SimpleNamespace(
        side=item.get("side", "NO"),
        entry_price=float(item.get("entry_price", item.get("avg_price", 0.0)) or 0.0),
        current_price=float(item.get("current_price", item.get("entry_price", item.get("avg_price", 0.0)) or 0.0)),
        size=float(item.get("size", 0.0) or 0.0),
        pnl=float(item.get("pnl", item.get("unrealized_pnl", 0.0)) or 0.0),
    )


def _to_market_obj(item: Mapping[str, Any]) -> Any:
    title = item.get("question") or item.get("title")
    if not title:
        title = "Unknown Market"

    return SimpleNamespace(
        id=item.get("market_id") or "—",
        title=title,
        category=item.get("category") or "—",
    )


def render_positions_view(data: Mapping[str, Any]) -> str:
    positions = data.get("positions")
    if not isinstance(positions, list) or not positions:
        return block(
            [
                section("📊 POSITIONS"),
                "📭 No active positions",
                "└─ Waiting for execution-qualified setup",
            ]
        )

    cards: list[str] = [section("📊 POSITIONS")]
    for idx, raw in enumerate(positions, start=1):
        item = raw if isinstance(raw, Mapping) else {}
        cards.append(
            format_position(
                position=_to_position_obj(item),
                market=_to_market_obj(item),
                index=idx,
            )
        )

    return "\n\n".join(cards)
