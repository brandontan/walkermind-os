"""Strategy preset system (Phase 5C).

Named bundles of strategy + capital + TP/SL + per-position cap that a user
activates as a single unit instead of configuring six fields by hand. The
risk gate constants in domain/risk/constants.py remain the hard ceiling;
preset values may only restrict downward.
"""
from .presets import (
    PRESETS, PRESET_ORDER, RECOMMENDED_PRESET, Preset, PresetBadge,
    get_preset, list_presets,
)

__all__ = [
    "PRESETS",
    "PRESET_ORDER",
    "RECOMMENDED_PRESET",
    "Preset",
    "PresetBadge",
    "get_preset",
    "list_presets",
]
