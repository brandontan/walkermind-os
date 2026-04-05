"""STRATEGY status list view."""
from __future__ import annotations

from typing import Any, Mapping

from ..ui_blocks import format_block, format_row


_DEFAULT_STRATEGIES = [
    ("EV Momentum", True),
    ("Mean Revert", True),
    ("Liquidity", False),
]


def render_strategy_view(data: Mapping[str, Any]) -> str:
    strategies = data.get("strategies")
    rows: list[str] = []

    if isinstance(strategies, dict) and strategies:
        for name, enabled in strategies.items():
            state = "🟢 ON" if bool(enabled) else "🔴 OFF"
            rows.append(format_row(str(name), state))
    else:
        for name, enabled in _DEFAULT_STRATEGIES:
            state = "🟢 ON" if enabled else "🔴 OFF"
            rows.append(format_row(name, state))

    return format_block("🎯 STRATEGY", rows)
