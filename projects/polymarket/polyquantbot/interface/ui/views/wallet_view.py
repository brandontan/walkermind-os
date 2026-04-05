"""WALLET unified premium hierarchy dashboard view."""
from __future__ import annotations

from typing import Any, Mapping

from ..formatters.premium_formatter import block, divider, format_money, item, item_last, section


def render_wallet_view(data: Mapping[str, Any]) -> str:
    lines = [section("💼 WALLET")]
    lines.extend(
        [
            "💼 Account",
            item("Balance", format_money(data.get("cash", data.get("balance", 0.0)))),
            item("Equity", format_money(data.get("equity", 0.0))),
            item_last("Available", format_money(data.get("free_margin", data.get("free", 0.0)))),
            "",
            "🧠 Insight",
            "└─ Wallet ledger synchronized",
            divider(),
        ]
    )
    return block(lines)
