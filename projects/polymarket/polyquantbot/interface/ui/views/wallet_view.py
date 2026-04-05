"""WALLET premium metrics view."""
from __future__ import annotations

from typing import Any, Mapping

from ..ui_blocks import row, section


def render_wallet_view(data: Mapping[str, Any]) -> str:
    rows = [
        row("Cash", data.get("cash", data.get("balance"))),
        row("Equity", data.get("equity")),
        row("Used Margin", data.get("used_margin", data.get("used"))),
        row("Free Margin", data.get("free_margin", data.get("free"))),
        row("Positions", data.get("positions")),
    ]
    insight = [
        row("Summary", "Margin profile stable; monitor free cash for new entries."),
    ]
    return "\n\n".join([section("💼 WALLET", rows), section("🧠 INSIGHT", insight)])
