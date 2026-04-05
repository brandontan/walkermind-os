"""WALLET metrics-only view."""
from __future__ import annotations

from typing import Any, Mapping

from ..ui_blocks import row, section


def render_wallet_view(data: Mapping[str, Any]) -> str:
    rows = [
        row("Cash", str(data.get("cash", data.get("balance", "N/A")))),
        row("Equity", str(data.get("equity", "N/A"))),
        row("Used Margin", str(data.get("used_margin", data.get("used", "N/A")))),
        row("Free Margin", str(data.get("free_margin", data.get("free", "N/A")))),
        row("Positions", str(data.get("positions", "N/A"))),
    ]
    return section("WALLET", rows)
