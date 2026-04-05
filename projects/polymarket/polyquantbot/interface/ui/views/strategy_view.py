"""STRATEGY premium dashboard view."""
from __future__ import annotations

from typing import Any, Mapping

from .helpers import SEPARATOR, block, fmt


TITLE = "🧠 STRATEGY"
SUBTITLE = "Polymarket AI Trader"


def _is_on(value: Any, default: bool) -> bool:
    if value is None:
        return default
    return bool(value)


def _strategy_insight(enabled_count: int) -> str:
    if enabled_count == 0:
        return "No active trades • Waiting signal"
    if enabled_count == 1:
        return "1 position open • Monitoring"
    return "Low exposure • Safe positioning"


def render_strategy_view(data: Mapping[str, Any]) -> str:
    strategies = data.get("strategies") if isinstance(data.get("strategies"), dict) else {}
    ev_momentum = _is_on(strategies.get("EV Momentum"), True)
    mean_reversion = _is_on(strategies.get("Mean Reversion"), True)
    liquidity_edge = _is_on(strategies.get("Liquidity Edge"), False)

    enabled_count = sum([ev_momentum, mean_reversion, liquidity_edge])

    mode = fmt(data.get("mode", "dev"))
    status = fmt(data.get("status"))
    runtime = mode if mode == "—" or status == "—" else f"{mode} • {status}"

    sections = [
        f"{TITLE}\n{SUBTITLE}",
        block("EV Momentum", "ON" if ev_momentum else "OFF", "EV Momentum"),
        block("Mean Reversion", "ON" if mean_reversion else "OFF", "Mean Reversion"),
        block("Liquidity Edge", "ON" if liquidity_edge else "OFF", "Liquidity Edge"),
        block("Runtime", runtime, "Mode • Status"),
        f"⚙️ Insight\n{_strategy_insight(enabled_count)}",
    ]
    return f"\n{SEPARATOR}\n".join(sections)
