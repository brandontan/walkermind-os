"""The 5 named strategy presets.

Each preset bundles strategy selection, capital allocation, TP, SL, and
per-position cap. Values are stored as fractions (0.50 = 50%) so they map
directly to the existing user_settings columns.

Hard ceilings remain enforced by domain/risk/constants.py — preset values
must never exceed the system constants. Validation is performed at module
import time so a misconfigured preset fails the test suite, not production.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Tuple

from ..risk.constants import MAX_POSITION_PCT


class PresetBadge(str, Enum):
    """Risk badge displayed next to each preset in the picker."""
    SAFE = "🟢 Safe"
    BALANCED = "🟡 Balanced"
    ADVANCED = "🟡 Advanced"
    AGGRESSIVE = "🔴 Aggressive"


@dataclass(frozen=True)
class Preset:
    """A named strategy + risk + sizing bundle.

    All percentage fields are stored as fractions (0.50 = 50%). Strategy
    keys must match the values understood by ``user_settings.strategy_types``
    and the strategy registry: ``copy_trade``, ``signal``, ``value``.
    """
    key: str
    emoji: str
    name: str
    strategies: Tuple[str, ...]
    capital_pct: float          # fraction of bankroll (0 < x < 1)
    tp_pct: float               # take-profit fraction (e.g. 0.20 = +20%)
    sl_pct: float               # stop-loss fraction (e.g. 0.10 = -10%)
    max_position_pct: float     # per-trade position cap (fraction)
    badge: PresetBadge
    description: str            # one-line picker subtitle

    def __post_init__(self) -> None:
        if not self.strategies:
            raise ValueError(f"preset {self.key}: strategies cannot be empty")
        if not 0.0 < self.capital_pct < 1.0:
            raise ValueError(
                f"preset {self.key}: capital_pct must be in (0, 1), "
                f"got {self.capital_pct}"
            )
        if not 0.0 < self.tp_pct <= 1.0:
            raise ValueError(
                f"preset {self.key}: tp_pct must be in (0, 1], got {self.tp_pct}"
            )
        if not 0.0 < self.sl_pct <= 1.0:
            raise ValueError(
                f"preset {self.key}: sl_pct must be in (0, 1], got {self.sl_pct}"
            )
        if not 0.0 < self.max_position_pct <= MAX_POSITION_PCT:
            raise ValueError(
                f"preset {self.key}: max_position_pct {self.max_position_pct} "
                f"exceeds hard cap MAX_POSITION_PCT={MAX_POSITION_PCT}"
            )


# ---------------------------------------------------------------------------
# Preset definitions — locked, owner-approved values from CrusaderBot Phase 5C
# spec. Changing any number here requires a new lane and SENTINEL audit.
# ---------------------------------------------------------------------------

PRESETS: Dict[str, Preset] = {
    "whale_mirror": Preset(
        key="whale_mirror",
        emoji="🐋",
        name="Whale Mirror",
        strategies=("copy_trade",),
        capital_pct=0.50,
        tp_pct=0.20,
        sl_pct=0.10,
        max_position_pct=0.05,
        badge=PresetBadge.SAFE,
        description="Mirror top-performing wallets; one strategy, conservative size.",
    ),
    "signal_sniper": Preset(
        key="signal_sniper",
        emoji="📡",
        name="Signal Sniper",
        strategies=("signal",),
        capital_pct=0.50,
        tp_pct=0.15,
        sl_pct=0.08,
        max_position_pct=0.05,
        badge=PresetBadge.SAFE,
        description="Subscribe to operator signals; tight stops, frequent trades.",
    ),
    "hybrid": Preset(
        key="hybrid",
        emoji="🐋📡",
        name="Hybrid",
        strategies=("copy_trade", "signal"),
        capital_pct=0.60,
        tp_pct=0.15,
        sl_pct=0.10,
        max_position_pct=0.05,
        badge=PresetBadge.BALANCED,
        description="Combine wallet mirroring with signal feeds for broader coverage.",
    ),
    "value_hunter": Preset(
        key="value_hunter",
        emoji="🎯",
        name="Value Hunter",
        strategies=("value",),
        capital_pct=0.40,
        tp_pct=0.25,
        sl_pct=0.12,
        max_position_pct=0.08,
        badge=PresetBadge.ADVANCED,
        description="Edge-based mispricing trades; fewer entries, larger targets.",
    ),
    "full_auto": Preset(
        key="full_auto",
        emoji="🚀",
        name="Full Auto",
        strategies=("copy_trade", "signal", "value"),
        capital_pct=0.80,
        tp_pct=0.20,
        sl_pct=0.15,
        max_position_pct=0.10,
        badge=PresetBadge.AGGRESSIVE,
        description="All strategies live; maximum exposure within hard risk caps.",
    ),
}

# Display order — picker renders this top-to-bottom. Whale Mirror leads as the
# recommended starting point for new users.
PRESET_ORDER: Tuple[str, ...] = (
    "whale_mirror",
    "signal_sniper",
    "hybrid",
    "value_hunter",
    "full_auto",
)

RECOMMENDED_PRESET: str = "whale_mirror"


def get_preset(key: str) -> Preset | None:
    """Return preset by key, or None if the key is not recognised."""
    return PRESETS.get(key)


def list_presets() -> List[Preset]:
    """Return the presets in their canonical display order."""
    return [PRESETS[k] for k in PRESET_ORDER]
