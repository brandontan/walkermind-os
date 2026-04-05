"""HOME premium dashboard view."""
from __future__ import annotations

from typing import Any, Mapping

from .helpers import SEPARATOR, block, fmt, pnl


TITLE = "🏠 PREMIUM HOME"
SUBTITLE = "Polymarket AI Trader"


def _home_insight(positions: Any, status: Any) -> str:
    try:
        position_count = int(float(positions))
    except (TypeError, ValueError):
        position_count = 0

    status_text = fmt(status).lower()
    if position_count > 0:
        suffix = "position" if position_count == 1 else "positions"
        return f"{position_count} {suffix} open • Monitoring"
    if status_text in {"idle", "ready", "scanning", "active", "running"}:
        return "No active trades • Waiting signal"
    return "Low exposure • Safe positioning"


def render_home_view(data: Mapping[str, Any]) -> str:
    latency = data.get("latency")
    mode = fmt(data.get("mode"))
    status = fmt(data.get("status"))
    system_line = mode if mode == "—" or status == "—" else f"{mode} • {status}"

    sections = [
        f"{TITLE}\n{SUBTITLE}",
        block("Balance", data.get("balance"), "Balance"),
        block("Equity", data.get("equity"), "Equity"),
        block("Open Positions", data.get("positions"), "Positions"),
        block("Total PnL", pnl(data.get("total_pnl", data.get("pnl", 0.0))), "Total PnL"),
        block("System", system_line, "Mode • Status"),
    ]

    if latency is not None:
        sections.append(block("Latency", latency, "Runtime latency"))

    sections.append(f"🧠 Insight\n{_home_insight(data.get('positions'), status)}")
    return f"\n{SEPARATOR}\n".join(sections)
