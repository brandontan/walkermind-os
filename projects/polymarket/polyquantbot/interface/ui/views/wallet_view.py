"""WALLET product dashboard view."""
from __future__ import annotations

from typing import Any, Mapping

from .helpers import SEPARATOR, block, generate_insight


TITLE = "💼 WALLET"
SUBTITLE = "Polymarket AI Trader"


def render_wallet_view(data: Mapping[str, Any]) -> str:
    sections = [
        f"{TITLE}\n{SUBTITLE}",
        block(data.get("cash", data.get("balance")), "Balance"),
        block(data.get("equity"), "Equity"),
        block(data.get("free_margin", data.get("free")), "Available"),
        f"🧠 Insight\n{generate_insight(data)}",
    ]
    return f"\n{SEPARATOR}\n".join(sections)
