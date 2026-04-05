"""WALLET premium dashboard view."""
from __future__ import annotations

from typing import Any, Mapping

from .helpers import SEPARATOR, fmt, row


def render_wallet_view(data: Mapping[str, Any]) -> str:
    insight = "Capital structure balanced for next entries."
    if fmt(data.get("free_margin")) == "—":
        insight = "Margin data pending from runtime source."

    lines = [
        "💼 WALLET",
        row("Cash", data.get("cash", data.get("balance"))),
        row("Equity", data.get("equity")),
        row("Used", data.get("used_margin", data.get("used"))),
        SEPARATOR,
        row("Free", data.get("free_margin", data.get("free"))),
        row("Positions", data.get("positions")),
        SEPARATOR,
        f"🧠 Insight  {insight}",
    ]
    return "\n".join(lines)
