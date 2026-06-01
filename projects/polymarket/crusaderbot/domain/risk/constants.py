"""HARD-WIRED risk constants — NOT overridable by env, yaml, or DB."""
from __future__ import annotations

KELLY_FRACTION = 0.25
MAX_POSITION_PCT = 0.10
MAX_CORRELATED_EXPOSURE = 0.40
DAILY_LOSS_HARD_STOP = -2_000.0
MAX_DRAWDOWN_HALT = 0.08
MIN_LIQUIDITY = 10_000.0
MIN_EDGE_BPS = 200
SIGNAL_STALE_SECONDS = 14400  # 4h: matches SIGNAL_EXPIRY_HOURS — gate uses expires_at as primary guard
DEDUP_WINDOW_SECONDS = 300

# Slippage / market-impact guardrails (gate step 14).
# MAX_MARKET_IMPACT_PCT: reject if size_usdc / market_liquidity exceeds this.
# Prevents a single order from consuming more than 5% of visible depth.
MAX_MARKET_IMPACT_PCT = 0.05
# MAX_SLIPPAGE_PCT: maximum tolerated price deviation from mid for live orders.
# Not enforced in paper mode; validated by the readiness check before live activation.
MAX_SLIPPAGE_PCT = 0.03
# SLIPPAGE_GUARD_PCT: hard pre-submission slippage fence (Track D Live Gate Hardening).
# Before any order submission, abs(intended_price - market_price) / market_price
# must not exceed this value. Orders breaching this threshold are rejected with
# SLIPPAGE_REJECTED and never reach the CLOB. Applies to live path only.
SLIPPAGE_GUARD_PCT = 0.05

PROFILES: dict[str, dict] = {
    "conservative": {
        "kelly": 0.10, "max_pos_pct": 0.03, "max_concurrent": 5,
        "daily_loss": -200.0, "min_edge_bps": 400,
        "min_liquidity": 20_000.0, "max_days": 7,
    },
    "balanced": {
        "kelly": 0.20, "max_pos_pct": 0.06, "max_concurrent": 12,
        "daily_loss": -500.0, "min_edge_bps": 300,
        "min_liquidity": 15_000.0, "max_days": 30,
    },
    "aggressive": {
        "kelly": 0.25, "max_pos_pct": 0.10, "max_concurrent": 20,
        "daily_loss": -1_000.0, "min_edge_bps": 200,
        "min_liquidity": 10_000.0, "max_days": 90,
    },
    # Custom profile: user sets capital_pct / tp_pct / sl_pct in user_settings.
    # Gate risk limits fall back to balanced floor until custom values are confirmed.
    "custom": {
        "kelly": 0.20, "max_pos_pct": 0.06, "max_concurrent": 12,
        "daily_loss": -500.0, "min_edge_bps": 300,
        "min_liquidity": 15_000.0, "max_days": 30,
        "capital_pct": None, "tp_pct": None, "sl_pct": None,
    },
}

STRATEGY_AVAILABILITY: dict[str, list[str]] = {
    "copy_trade":        ["conservative", "balanced", "aggressive", "custom"],
    "signal":            ["conservative", "balanced", "aggressive", "custom"],
    "signal_following":  ["conservative", "balanced", "aggressive", "custom"],
    "value":             ["balanced", "aggressive", "custom"],
    "momentum":          ["balanced", "aggressive", "custom"],
    "momentum_reversal": ["balanced", "aggressive", "custom"],
    "trend_breakout":    ["balanced", "aggressive", "custom"],
    "value_investor":    ["balanced", "aggressive", "custom"],
    "whale_tracking":    ["conservative", "balanced", "aggressive", "custom"],
    # ensemble emits candidates with strategy_name="ensemble" — must be listed
    # or gate step 4 rejects every ensemble candidate as unknown_strategy.
    "ensemble":          ["balanced", "aggressive", "custom"],
    # Crypto-short preset engines — candidates carry the lib/domain strategy
    # name as strategy_type. close_sweep -> late_entry_v3,
    # Crypto Scalper -> confluence_scalper.
    "expiration_timing":  ["conservative", "balanced", "aggressive", "custom"],
    "confluence_scalper": ["balanced", "aggressive", "custom"],
    "late_entry_v3":      ["conservative", "balanced", "aggressive", "custom"],
    # Weather domain strategy (weather_monitor preset). Emits candidates with
    # strategy_name="weather"; without this entry gate step 4 rejects every
    # weather candidate as unknown_strategy — the weather pipeline (mig 075/076,
    # all 5 exits) would silently convert zero trades. All profiles allowed:
    # ensemble forecast edge is not leverage-sensitive and sizing is still
    # bounded by Kelly + max-position caps downstream.
    "weather":            ["conservative", "balanced", "aggressive", "custom"],
}


def effective_daily_loss(
    profile: str,
    user_override: float | None = None,
    system_floor: float | None = None,
) -> float:
    """Most restrictive of: system hard cap, profile cap, user lower override, system floor.

    All values are negative dollar amounts (e.g. -200.0 = "halt at -$200").
    ``max()`` of negatives = least negative = most restrictive.

    ``system_floor`` is an operator-tunable env-side cap (``settings.MAX_DAILY_LOSS_USD``)
    that, when supplied, participates in the most-restrictive selection. This is
    the single point that reconciles the historical Track-D cap (step 0 cap 3)
    with the profile-aware gate (step 5) so the UI's stated profile limit is the
    actual enforced limit unless the operator explicitly tightens it further.
    """
    base = profile if profile in PROFILES else "balanced"
    caps = [DAILY_LOSS_HARD_STOP, PROFILES[base]["daily_loss"]]
    # Defensive: an accidentally-positive override or system_floor (env typo
    # "50" instead of "-50") would poison max(of negatives) and halt every
    # user on any non-positive pnl. Coerce to its negative magnitude so the
    # operator's intent ("halt at $X loss") cannot be silently flipped into a
    # bot-wide DoS.
    if user_override is not None:
        caps.append(-abs(float(user_override)))
    if system_floor is not None:
        caps.append(-abs(float(system_floor)))
    return max(caps)  # max of negatives = least negative = most restrictive


def effective_exposure_cap(system_cap: float | None = None) -> float:
    """Most restrictive correlated-exposure cap.

    Reconciles the historical Track-D cap (step 0 cap 2 = ``settings.MAX_TOTAL_EXPOSURE_PCT``)
    with the system constant (gate step 8 = ``MAX_CORRELATED_EXPOSURE``) so a
    single value is evaluated, in one place, against ``(open_exp + proposed) / balance``.
    Fractions in (0, 1]; the smaller value is more restrictive and wins.
    """
    caps: list[float] = [float(MAX_CORRELATED_EXPOSURE)]
    if system_cap is not None:
        caps.append(float(system_cap))
    return min(caps)


def effective_max_concurrent(
    profile: str,
    user_override: int | None = None,
) -> int:
    """Most-restrictive concurrent-trades cap for a user.

    Selects ``min(profile["max_concurrent"], user_override)`` so a user can
    only tighten — never loosen — the profile cap. Mirrors the semantics of
    ``effective_daily_loss`` and ``max_drawdown_pct``: the bot is multi-user;
    each user controls their own risk/reward but cannot exceed the cap their
    chosen profile permits.

    ``user_override`` is None when the user hasn't set ``max_concurrent_override``
    in ``user_settings`` — the profile default governs alone. Negative / zero
    / accidentally non-positive overrides are defensively coerced to None so
    a typo cannot brick a user (gate step 7 would reject every trade with
    ``cur >= 0``). The DB CHECK constraint (1..20) prevents this at write
    time; this defence handles legacy rows / direct DB writes.
    """
    # Normalise: profile may arrive with mixed case (e.g. 'Conservative' from
    # a UI form) or as None — match the lowercase-default behaviour of
    # ``profile_or_default`` so an upper/title-cased name resolves correctly
    # instead of silently falling back to 'balanced'.
    base = (profile or "balanced").lower()
    if base not in PROFILES:
        base = "balanced"
    profile_cap = int(PROFILES[base]["max_concurrent"])
    caps: list[int] = [profile_cap]
    if user_override is not None:
        try:
            ov = int(user_override)
        except (TypeError, ValueError):
            ov = 0
        if ov >= 1:
            caps.append(ov)
    return min(caps)


def profile_or_default(name: str | None) -> dict:
    return PROFILES.get((name or "balanced").lower(), PROFILES["balanced"])


# Canonical TP/SL + capital per risk profile — the SINGLE source of truth for
# a position's take-profit / stop-loss. Preset activation must NOT override
# these with preset-specific values; the user's risk profile owns TP/SL so the
# behaviour matches the Kreo reference ("auto TP/SL = user risk profile").
# Fractions (0.20 = +20%). 'custom' has no fixed values — the user sets them.
PROFILE_TP_SL: dict[str, dict[str, float]] = {
    "conservative": {"capital_alloc_pct": 0.20, "tp_pct": 0.10, "sl_pct": 0.05},
    "balanced":     {"capital_alloc_pct": 0.40, "tp_pct": 0.20, "sl_pct": 0.15},
    "aggressive":   {"capital_alloc_pct": 0.60, "tp_pct": 0.30, "sl_pct": 0.20},
}


def tp_sl_for_profile(name: str | None) -> dict[str, float]:
    """Canonical capital/TP/SL for a named profile; defaults to balanced.

    Used by preset activation + new-user bootstrap so TP/SL always follows the
    risk profile rather than the activated preset. 'custom' is NOT here — custom
    TP/SL is user-supplied and may be TP-only or SL-only.
    """
    return PROFILE_TP_SL.get((name or "balanced").lower(), PROFILE_TP_SL["balanced"])
