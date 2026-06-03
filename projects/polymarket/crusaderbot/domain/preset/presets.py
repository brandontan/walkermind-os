"""Named Auto-Trade strategy presets for CrusaderBot MVP.

3 candle presets, all routing to late_entry_v3. Each preset defines:
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
    ADVANCED = "🟠 Advanced"
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
        if not 0.0 < self.tp_pct <= 2.0:
            raise ValueError(
                f"preset {self.key}: tp_pct must be in (0, 2], got {self.tp_pct}"
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
    "custom":       0.40,  # fallback; actual value read from user_settings.capital_alloc_pct
}


def capital_for_risk_profile(profile: str) -> float:
    """Return capital fraction for the given risk profile.

    Conservative → 0.20 | Balanced → 0.40 | Aggressive → 0.60
    Defaults to balanced if profile is unrecognised.
    """
    return _CAPITAL_BY_PROFILE.get((profile or "balanced").lower(), 0.40)


# ---------------------------------------------------------------------------
# Preset definitions — 3 candle presets, all routing to late_entry_v3
# ---------------------------------------------------------------------------

PRESETS: Dict[str, Preset] = {
    # All current presets route to late_entry_v3 with different timing and
    # conviction thresholds. Designed for BTC/ETH/SOL 5m and 15m candles.
    # The legacy multi-strategy presets (whale_mirror, signal_sniper, hybrid,
    # value_hunter, full_auto) were removed in WARP/R00T/strategy-system-
    # cleanup along with the lib/strategies/* modules that backed them — none
    # of those strategies had a real trigger path.
    "candle_auto": Preset(
        key="candle_auto",
        emoji="🔥",
        name="Smart Strike",
        strategies=("late_entry_v3",),
        capital_pct=0.40,
        tp_pct=0.90,
        sl_pct=0.40,
        max_position_pct=0.05,
        badge=PresetBadge.BALANCED,
        description="Auto-router: picks Flip/Safe/Close per candle stage. Set-and-forget.",
    ),
    "close_sweep": Preset(
        key="close_sweep",
        emoji="🧹",
        name="Close Sweep",
        strategies=("late_entry_v3",),
        capital_pct=0.40,
        tp_pct=0.90,
        sl_pct=0.40,
        max_position_pct=0.05,
        badge=PresetBadge.SAFE,
        description="Final 35s entry. Strong lean required. Recommended starting point.",
    ),
    "safe_close": Preset(
        key="safe_close",
        emoji="🔒",
        name="Safe Close",
        strategies=("late_entry_v3",),
        capital_pct=0.30,
        tp_pct=0.80,
        sl_pct=0.35,
        max_position_pct=0.05,
        badge=PresetBadge.SAFE,
        description="Final 60s, tighter lean filter. Fewer trades, cleaner entries.",
    ),
    "flip_hunter": Preset(
        key="flip_hunter",
        emoji="🎯",
        name="Flip Hunter",
        strategies=("late_entry_v3",),
        capital_pct=0.40,
        tp_pct=1.50,
        sl_pct=0.50,
        max_position_pct=0.05,
        badge=PresetBadge.ADVANCED,
        description="Early 140s entry on low-odds lean. Asymmetric upside on flips.",
    ),
    "weather_monitor": Preset(
        key="weather_monitor",
        emoji="🌤",
        name="Weather Monitor",
        strategies=("weather",),
        capital_pct=0.20,
        tp_pct=0.25,
        sl_pct=0.20,
        max_position_pct=0.05,
        badge=PresetBadge.BALANCED,
        description="Daily temperature markets across 20 cities. Ensemble forecast edge.",
    ),
    # PLAYBOOK — sports strategy router (the sports equivalent of Smart Strike).
    # Auto-routes each sports market to the highest-EV module (Closing Edge wired
    # in Phase-1; Sharp Money / Public Fade / Injury Alpha sequenced V2). Routes
    # to the single `playbook` strategy engine, mirroring candle_auto/late_entry_v3.
    "playbook": Preset(
        key="playbook",
        emoji="🏟",
        name="Playbook",
        strategies=("playbook",),
        capital_pct=0.40,
        tp_pct=0.25,
        sl_pct=0.12,
        max_position_pct=0.06,
        badge=PresetBadge.BALANCED,
        description="Autonomous sports orchestration. Auto-routes to the highest-EV module.",
    ),
}

# Display order — picker renders top-to-bottom.
PRESET_ORDER: Tuple[str, ...] = (
    "candle_auto",
    "close_sweep",
    "safe_close",
    "flip_hunter",
    "weather_monitor",
    "playbook",
)

# Candle preset keys — used by the picker to render a section divider.
# candle_auto is the lifecycle-router over the three single-rule candle presets;
# it routes to the same late_entry_v3 engine, so it belongs to the candle group.
CANDLE_PRESET_KEYS: frozenset[str] = frozenset(
    {"candle_auto", "close_sweep", "safe_close", "flip_hunter"}
)

# Presets visible in the Telegram picker.
# NOTE: `playbook` is intentionally NOT visible yet — it is registered + routable
# (PRESET_ORDER / registry / STRATEGY_AVAILABILITY) but its live scan-loop dispatch
# is Phase-2 (deny-by-default in signal_scan_job._PRESET_ALLOWED). Exposing it as a
# selectable preset now would let a user activate a no-op that emits zero candidates
# (Codex P2, PR #1567). Re-add here when WARP/ROOT/playbook-live-dispatch lands.
VISIBLE_PRESET_ORDER: Tuple[str, ...] = (
    "candle_auto",
    "close_sweep",
    "safe_close",
    "flip_hunter",
    "weather_monitor",
)

RECOMMENDED_PRESET: str = "candle_auto"

# Presets that are REGISTERED + routable but NOT yet user-activatable — their live
# scan-loop dispatch is not wired (deny-by-default in signal_scan_job._PRESET_ALLOWED).
# Activating one would persist active_preset=<key> while the scanner emits zero
# candidates (a no-op trap). Hiding from the pickers alone is insufficient: stale
# Telegram inline buttons and cached WebTrader clients can still hit the activation
# path, and the backend roster still accepts the key. So activation is gated on this
# set in EVERY entry point (WebTrader /autotrade/preset + Telegram _on_pick/_on_activate)
# via is_activatable(). Empty this set per preset as its Phase-2 dispatch lands.
# (Codex P2 + Gemini, PR #1570; follow-up to PR #1567.)
HIDDEN_PRESETS: frozenset[str] = frozenset({"playbook"})


def get_preset(key: str) -> Preset | None:
    """Return preset by key, or None if the key is not recognised."""
    return PRESETS.get(key)


def is_activatable(key: str) -> bool:
    """True if ``key`` is a registered preset a user may activate right now.

    A preset in ``HIDDEN_PRESETS`` is registered + routable but its live dispatch
    is not yet wired, so it must not be activated (would be a silent no-op).
    """
    return key in PRESETS and key not in HIDDEN_PRESETS


def list_presets() -> List[Preset]:
    """Return visible presets in display order (picker-safe subset)."""
    return [PRESETS[k] for k in VISIBLE_PRESET_ORDER]


def list_all_presets() -> List[Preset]:
    """Return all presets including hidden ones (for internal use / admin)."""
    return [PRESETS[k] for k in PRESET_ORDER]
