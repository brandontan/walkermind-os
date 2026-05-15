"""Named Auto-Trade strategy presets for CrusaderBot MVP.

5 presets covering the full strategy spectrum. Each preset defines:
  - strategy routing (which execution strategies the engine activates)
  - TP / SL / max-position-per-trade sizing
  - a sensible capital_pct DEFAULT for the customize wizard UI

IMPORTANT: capital_pct is the wizard UI default only.
Actual capital applied at activation comes from the user's risk profile:
  Conservative → 20% | Balanced → 40% | Aggressive → 60%
Use capital_for_risk_profile() as the authoritative source at activation time.

Hard ceilings remain enforced by domain/risk/constants.py — preset values
must never exceed system constants. Validation runs at module import so
a misconfigured preset fails the test suite, not production.
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
    keys must match values understood by user_settings.strategy_types
    and the strategy registry: copy_trade, signal, value.
    """
    key: str
    emoji: str
    name: str
    strategies: Tuple[str, ...]
    capital_pct: float          # wizard UI default only — NOT used at activation
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
# Risk-profile capital allocation — authoritative source used at activation
# ---------------------------------------------------------------------------

_CAPITAL_BY_PROFILE: dict[str, float] = {
    "conservative": 0.20,
    "balanced":     0.40,
    "aggressive":   0.60,
}


def capital_for_risk_profile(profile: str) -> float:
    """Return capital fraction for the given risk profile.

    Conservative → 0.20 | Balanced → 0.40 | Aggressive → 0.60
    Defaults to balanced if profile is unrecognised.
    """
    return _CAPITAL_BY_PROFILE.get((profile or "balanced").lower(), 0.40)


# ---------------------------------------------------------------------------
# Preset definitions — 5 presets covering full strategy spectrum
# ---------------------------------------------------------------------------

PRESETS: Dict[str, Preset] = {
    "whale_mirror": Preset(
        key="whale_mirror",
        emoji="🐋",
        name="Whale Mirror",
        strategies=("copy_trade",),
        capital_pct=0.40,           # wizard default; activation uses risk profile
        tp_pct=0.20,
        sl_pct=0.10,
        max_position_pct=0.05,
        badge=PresetBadge.BALANCED,
        description="Follow proven Polymarket wallets. Low effort, steady returns.",
    ),
    "signal_sniper": Preset(
        key="signal_sniper",
        emoji="📡",
        name="Signal Sniper",
        strategies=("signal",),
        capital_pct=0.40,           # wizard default; activation uses risk profile
        tp_pct=0.15,
        sl_pct=0.08,
        max_position_pct=0.05,
        badge=PresetBadge.SAFE,
        description="Auto-trade from curated signal feeds. Lower frequency, higher conviction.",
    ),
    "hybrid": Preset(
        key="hybrid",
        emoji="🐋📡",
        name="Hybrid",
        strategies=("copy_trade", "signal"),
        capital_pct=0.40,           # wizard default; activation uses risk profile
        tp_pct=0.15,
        sl_pct=0.10,
        max_position_pct=0.05,
        badge=PresetBadge.BALANCED,
        description="Whale Mirror + Signal Sniper combined. More opportunities.",
    ),
    "value_hunter": Preset(
        key="value_hunter",
        emoji="🎯",
        name="Value Hunter",
        strategies=("value",),
        capital_pct=0.40,           # wizard default; activation uses risk profile
        tp_pct=0.25,
        sl_pct=0.12,
        max_position_pct=0.08,
        badge=PresetBadge.ADVANCED,
        description="Finds mispriced markets using edge model. Higher reward, requires patience.",
    ),
    "full_auto": Preset(
        key="full_auto",
        emoji="🚀",
        name="Full Auto",
        strategies=("copy_trade", "signal", "value"),
        capital_pct=0.40,           # wizard default; activation uses risk profile
        tp_pct=0.20,
        sl_pct=0.15,
        max_position_pct=0.10,
        badge=PresetBadge.AGGRESSIVE,
        description="All strategies active. Max exposure. For experienced traders.",
    ),
}

# Display order — picker renders top-to-bottom.
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
