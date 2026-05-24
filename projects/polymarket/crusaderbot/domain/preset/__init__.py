"""Strategy preset system (Phase 5C).

Named bundles of strategy + capital + TP/SL + per-position cap that a user
activates as a single unit instead of configuring six fields by hand. The
risk gate constants in domain/risk/constants.py remain the hard ceiling;
preset values may only restrict downward.
"""
from .presets import (
    CANDLE_PRESET_KEYS, PRESETS, PRESET_ORDER, RECOMMENDED_PRESET,
    VISIBLE_PRESET_ORDER, Preset, PresetBadge,
    get_preset, list_all_presets, list_presets,
)

__all__ = [
    "CANDLE_PRESET_KEYS",
    "PRESETS",
    "PRESET_ORDER",
    "RECOMMENDED_PRESET",
    "VISIBLE_PRESET_ORDER",
    "Preset",
    "PresetBadge",
    "get_preset",
    "list_all_presets",
    "list_presets",
]
