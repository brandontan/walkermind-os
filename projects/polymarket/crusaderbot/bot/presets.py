"""Preset configuration registry — Phase 5 UX Rebuild.

Maps preset key → static config used by autotrade, confirmation, and customize
handlers. This is presentation + configuration layer only; no trading logic.
"""
from __future__ import annotations

from typing import TypedDict


class PresetConfig(TypedDict):
    emoji: str
    name: str
    strategy_label: str
    strategies: list[str]
    risk_label: str
    risk_emoji: str
    capital_pct: int
    tp_pct: int
    sl_pct: int
    max_pos_pct: int
    has_copy_trade: bool


PRESET_CONFIG: dict[str, PresetConfig] = {
    "whale_mirror": {
        "emoji": "🐋",
        "name": "Whale Mirror",
        "strategy_label": "Copy Trade",
        "strategies": ["copy_trade"],
        "risk_label": "Safe",
        "risk_emoji": "🟢",
        "capital_pct": 50,
        "tp_pct": 20,
        "sl_pct": 10,
        "max_pos_pct": 5,
        "has_copy_trade": True,
    },
    "signal_sniper": {
        "emoji": "📡",
        "name": "Signal Sniper",
        "strategy_label": "Signal Feed",
        "strategies": ["signal"],
        "risk_label": "Safe",
        "risk_emoji": "🟢",
        "capital_pct": 50,
        "tp_pct": 15,
        "sl_pct": 8,
        "max_pos_pct": 5,
        "has_copy_trade": False,
    },
    "hybrid": {
        "emoji": "🐋📡",
        "name": "Hybrid",
        "strategy_label": "Copy Trade + Signal",
        "strategies": ["copy_trade", "signal"],
        "risk_label": "Balanced",
        "risk_emoji": "🟡",
        "capital_pct": 60,
        "tp_pct": 15,
        "sl_pct": 10,
        "max_pos_pct": 5,
        "has_copy_trade": True,
    },
    "value_hunter": {
        "emoji": "🎯",
        "name": "Value Hunter",
        "strategy_label": "Value / Edge Model",
        "strategies": ["value"],
        "risk_label": "Advanced",
        "risk_emoji": "🟡",
        "capital_pct": 40,
        "tp_pct": 25,
        "sl_pct": 12,
        "max_pos_pct": 8,
        "has_copy_trade": False,
    },
    "full_auto": {
        "emoji": "🚀",
        "name": "Full Auto",
        "strategy_label": "All Strategies",
        "strategies": ["copy_trade", "signal", "value"],
        "risk_label": "Aggressive",
        "risk_emoji": "🔴",
        "capital_pct": 80,
        "tp_pct": 20,
        "sl_pct": 15,
        "max_pos_pct": 10,
        "has_copy_trade": True,
    },
}


def get_preset(key: str) -> PresetConfig | None:
    return PRESET_CONFIG.get(key)


PRESET_ORDER: list[str] = [
    "whale_mirror",
    "signal_sniper",
    "hybrid",
    "value_hunter",
    "full_auto",
]
