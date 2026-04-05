"""WALLET premium dashboard view."""
from __future__ import annotations

from typing import Any, Mapping

from .helpers import SEPARATOR, block, fmt


TITLE = "💼 WALLET"
SUBTITLE = "Polymarket AI Trader"


def _wallet_insight(data: Mapping[str, Any]) -> str:
    positions = data.get("positions")
    try:
        count = int(float(positions))
    except (TypeError, ValueError):
        count = 0

    free_margin = fmt(data.get("free_margin", data.get("free")))
    if count > 0:
        suffix = "position" if count == 1 else "positions"
        return f"{count} {suffix} open • Monitoring"
    if free_margin == "—":
        return "No active trades • Waiting signal"
    return "Low exposure • Safe positioning"


def render_wallet_view(data: Mapping[str, Any]) -> str:
    sections = [
        f"{TITLE}\n{SUBTITLE}",
        block("Balance", data.get("cash", data.get("balance")), "Balance"),
        block("Equity", data.get("equity"), "Equity"),
        block("Used Margin", data.get("used_margin", data.get("used")), "Used Margin"),
        block("Free Margin", data.get("free_margin", data.get("free")), "Free Margin"),
        block("Positions", data.get("positions"), "Open Positions"),
        f"🧠 Insight\n{_wallet_insight(data)}",
    ]
    return f"\n{SEPARATOR}\n".join(sections)
