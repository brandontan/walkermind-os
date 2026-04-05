"""STRATEGY product dashboard view."""
from __future__ import annotations

from typing import Any, Mapping

from .helpers import SEPARATOR, block, generate_insight


TITLE = "🧠 STRATEGY"
SUBTITLE = "Polymarket AI Trader"


def _is_on(value: Any, default: bool) -> bool:
    if value is None:
        return default
    return bool(value)


def render_strategy_view(data: Mapping[str, Any]) -> str:
    strategies = data.get("strategies") if isinstance(data.get("strategies"), dict) else {}
    ev_momentum = _is_on(strategies.get("EV Momentum"), True)
    mean_reversion = _is_on(strategies.get("Mean Reversion"), True)
    liquidity_edge = _is_on(strategies.get("Liquidity Edge"), False)

    sections = [
        f"{TITLE}\n{SUBTITLE}",
        block("ON" if ev_momentum else "OFF", "EV Momentum"),
        block("ON" if mean_reversion else "OFF", "Mean Reversion"),
        block("ON" if liquidity_edge else "OFF", "Liquidity Edge"),
        f"🧠 Insight\n{generate_insight(data)}",
    ]
    return f"\n{SEPARATOR}\n".join(sections)
