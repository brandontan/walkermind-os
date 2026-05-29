"""Preset configuration registry.

Maps preset key → static config used by autotrade, confirmation, and customize
handlers. Presentation + configuration layer only; no trading logic.

WARP/R00T/strategy-system-cleanup narrowed this set to the 3 candle presets,
all backed by late_entry_v3. The legacy multi-strategy presets (whale_mirror,
signal_sniper, hybrid, value_hunter, full_auto, trend_breakout, contrarian,
pair_arb, ensemble, confluence_scalper) were removed — every one of them
referenced a strategy that no longer exists or had no real trigger path.

Adding a new preset means: (1) implement the backing strategy under
domain/strategy/strategies/ or lib/strategies/, (2) wire scan/exit, (3) seed
a `strategies` table row (mig 067), (4) add it to _ADMIN_STRATEGIES + the
_PRESET_TO_STRATEGY map in webtrader/backend/router.py, (5) append the key
here AND in domain/preset/presets.py (the canonical registry).
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
    "close_sweep": {
        "emoji": "🧹",
        "name": "Close Sweep",
        "strategy_label": "late_entry_v3",
        "strategies": ["late_entry_v3"],
        "risk_label": "Safe",
        "risk_emoji": "🟢",
        "capital_pct": 40,
        "tp_pct": 90,
        "sl_pct": 40,
        "max_pos_pct": 5,
        "has_copy_trade": False,
    },
    "safe_close": {
        "emoji": "🔒",
        "name": "Safe Close",
        "strategy_label": "late_entry_v3",
        "strategies": ["late_entry_v3"],
        "risk_label": "Safe",
        "risk_emoji": "🟢",
        "capital_pct": 30,
        "tp_pct": 80,
        "sl_pct": 35,
        "max_pos_pct": 5,
        "has_copy_trade": False,
    },
    "flip_hunter": {
        "emoji": "🎯",
        "name": "Flip Hunter",
        "strategy_label": "late_entry_v3",
        "strategies": ["late_entry_v3"],
        "risk_label": "Advanced",
        "risk_emoji": "🟡",
        "capital_pct": 40,
        "tp_pct": 150,
        "sl_pct": 50,
        "max_pos_pct": 5,
        "has_copy_trade": False,
    },
}


def get_preset(key: str) -> PresetConfig | None:
    return PRESET_CONFIG.get(key)


PRESET_ORDER: list[str] = [
    "close_sweep",
    "safe_close",
    "flip_hunter",
]
