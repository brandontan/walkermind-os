"""STRATEGY unified premium hierarchy dashboard view."""
from __future__ import annotations

from typing import Any, Mapping

from ..formatters.premium_formatter import block, divider, format_market, item, item_last, section


def _is_on(value: Any, default: bool) -> bool:
    if value is None:
        return default
    return bool(value)


def _status(value: bool) -> str:
    return "🟢 ON" if value else "🔴 OFF"


def render_strategy_view(data: Mapping[str, Any]) -> str:
    strategies = data.get("strategies") if isinstance(data.get("strategies"), dict) else {}
    ev_momentum = _is_on(strategies.get("EV Momentum"), True)
    mean_reversion = _is_on(strategies.get("Mean Reversion"), True)
    liquidity_edge = _is_on(strategies.get("Liquidity Edge"), False)

    lines = [section("🧠 STRATEGY")]
    lines.extend(format_market(data))
    lines.extend([
        "",
        "🧠 Active Engines",
        item("EV Momentum", _status(ev_momentum)),
        item("Mean Revert", _status(mean_reversion)),
        item_last("Liquidity", _status(liquidity_edge)),
        "",
        "🧠 Insight",
        "└─ Strategy toggles ready for execution",
        divider(),
    ])
    return block(lines)
