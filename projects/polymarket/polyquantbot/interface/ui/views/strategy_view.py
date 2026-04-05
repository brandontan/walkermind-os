"""STRATEGY premium dashboard view."""
from __future__ import annotations

from typing import Any, Mapping

from .helpers import SEPARATOR, fmt, row


def _is_on(value: Any, default: bool) -> bool:
    if value is None:
        return default
    return bool(value)


def render_strategy_view(data: Mapping[str, Any]) -> str:
    strategies = data.get("strategies") if isinstance(data.get("strategies"), dict) else {}
    ev_momentum = _is_on(strategies.get("EV Momentum"), True)
    mean_reversion = _is_on(strategies.get("Mean Reversion"), True)
    liquidity_edge = _is_on(strategies.get("Liquidity Edge"), False)

    lines = [
        "🧠 STRATEGY",
        row("EV Mom", "ON" if ev_momentum else "OFF"),
        row("Mean Rev", "ON" if mean_reversion else "OFF"),
        row("Liquidity", "ON" if liquidity_edge else "OFF"),
        SEPARATOR,
        row("Runtime", fmt(data.get("mode", "dev"))),
        SEPARATOR,
        "⚙️ Insight  Strategy blend active and toggle-safe.",
    ]
    return "\n".join(lines)
