"""STRATEGY status list view."""
from __future__ import annotations

from typing import Any, Mapping

from ..ui_blocks import row, section


def _normalize_state(value: object, default: bool) -> bool:
    if value is None:
        return default
    return bool(value)


def render_strategy_view(data: Mapping[str, Any]) -> str:
    strategies = data.get("strategies") if isinstance(data.get("strategies"), dict) else {}
    ev_momentum = _normalize_state(strategies.get("EV Momentum"), True)
    mean_reversion = _normalize_state(strategies.get("Mean Reversion"), True)
    liquidity_edge = _normalize_state(strategies.get("Liquidity Edge"), False)

    rows = [
        row("EV Momentum", "🟢 ON" if ev_momentum else "🔴 OFF"),
        row("Mean Revert", "🟢 ON" if mean_reversion else "🔴 OFF"),
        row("Liquidity", "🟢 ON" if liquidity_edge else "🔴 OFF"),
    ]
    return section("STRATEGIES", rows)
