"""MARKET INTELLIGENCE premium read-only view."""
from __future__ import annotations

from typing import Any, Mapping

from ..ui_blocks import row, section


def short_name(name: object) -> str:
    text = str(name or "N/A").strip()
    return text[:18] + "..." if len(text) > 18 else text


def _safe_int(value: object) -> str:
    try:
        if value is None:
            return "N/A"
        return str(int(float(value)))
    except (TypeError, ValueError):
        return "N/A"


def _safe_text(value: object, default: str = "N/A") -> str:
    text = str(value).strip() if value is not None else ""
    return text if text else default


def _opportunity_line(item: Mapping[str, Any]) -> str:
    name = short_name(item.get("name", "N/A"))
    ev_raw = item.get("ev")
    signal = _safe_text(item.get("signal"))
    try:
        ev_text = f"{float(ev_raw):.3f}"
    except (TypeError, ValueError):
        ev_text = "N/A"
    return f"{name:<22} EV {ev_text}   {signal}"


def render_market_view(data: Mapping[str, Any]) -> str:
    top = data.get("top_opportunities")
    opportunities = top if isinstance(top, list) else []

    intel_rows = [
        row("Scanned", _safe_int(data.get("total_markets"))),
        row("Active", _safe_int(data.get("active_markets"))),
        row("Top Edge", _safe_text(data.get("top_edge_type"))),
        row("Signal", _safe_text(data.get("dominant_signal"))),
    ]

    if not opportunities:
        opportunity_rows = [row("Status", "No data")]
    else:
        opportunity_rows = [
            _opportunity_line(item if isinstance(item, Mapping) else {})
            for item in opportunities[:5]
        ]

    return "\n\n".join(
        [
            section("📡 MARKET INTEL", intel_rows),
            section("🔥 TOP OPPORTUNITIES", opportunity_rows),
        ]
    )
