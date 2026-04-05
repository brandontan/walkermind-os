"""WALLET metrics-only view."""
from __future__ import annotations

from typing import Any, Mapping

from ..ui_blocks import format_block, format_row


def render_wallet_view(data: Mapping[str, Any]) -> str:
    rows = [
        format_row("cash", str(data.get("cash", data.get("balance", "N/A")))),
        format_row("equity", str(data.get("equity", "N/A"))),
        format_row("used", str(data.get("used", "N/A"))),
        format_row("free", str(data.get("free", "N/A"))),
        format_row("positions", str(data.get("positions", "N/A"))),
    ]
    return format_block("💰 WALLET", rows)
