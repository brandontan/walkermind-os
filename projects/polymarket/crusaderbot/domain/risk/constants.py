"""HARD-WIRED risk constants — NOT overridable by env, yaml, or DB."""
from __future__ import annotations

KELLY_FRACTION = 0.25
MAX_POSITION_PCT = 0.10
MAX_CORRELATED_EXPOSURE = 0.40
DAILY_LOSS_HARD_STOP = -2_000.0
MAX_DRAWDOWN_HALT = 0.08
MIN_LIQUIDITY = 10_000.0
MIN_EDGE_BPS = 200
# Concurrent open positions are governed PER USER, not by a global ceiling
# (WARP🔹CMD / owner directive 2026-06-03). The limit is each user's own
# setting: their `max_concurrent_override` when set, otherwise their profile
# default (conservative 5 / balanced 12 / aggressive 20 — see PROFILES below).
# There is intentionally NO system-wide hard cap clamping the result down; the
# other capital brakes (Kelly 0.25, max position ≤10%, daily-loss −$2k,
# drawdown 8%, correlated-exposure 40% at gate step 8, kill switch) still apply.
# An override is bounded only by the user_settings DB CHECK (1..20) at write time.
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

# Complete-set arbitrage hard floor. AGENTS.md RISK CONSTANTS: "Arbitrage —
# execute only if net_edge > fees + slippage AND > 2%". MIN_COMPLETE_SET_EDGE
# (config, default 0.0) keeps the path dormant; the instant an operator
# activates it with ANY positive value, the effective per-pair margin floor is
# clamped UP to at least this 2% net edge plus the explicit fee/slippage
# allowance below, so a sub-2% (or fee-uncovered) set can never book.
COMPLETE_SET_MIN_NET_EDGE = 0.02
# Explicit fee + slippage allowance folded into the complete-set margin floor.
# Polymarket charges no maker/taker fee today (0.0); kept as a named, tunable
# constant so the arb cost model is explicit in the threshold, not implicit.
COMPLETE_SET_FEE_SLIPPAGE_ALLOWANCE = 0.0

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
    # PLAYBOOK sports strategy router (playbook preset). Emits candidates with
    # strategy_name="playbook"; without this entry gate step 4 rejects every
    # sports candidate as unknown_strategy. All profiles allowed — module sizing
    # is still bounded by Kelly + max-position + exposure caps downstream.
    "playbook":           ["conservative", "balanced", "aggressive", "custom"],
    # Complete-set arbitrage (WARP/ROOT/complete-set-arb epic, Lane 2C). Books a
    # hedged YES+NO pair held to resolution — riskless by construction, so all
    # profiles are allowed; sizing is still bounded by Kelly + max-position caps
    # in gate step 13 (complete_set hard-cap path). Without this entry gate step 4
    # rejects every set as unknown_strategy. Scan + booking remain gated behind
    # COMPLETE_SET_ARB_ENABLED (default OFF).
    "complete_set_arb":   ["conservative", "balanced", "aggressive", "custom"],
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
    """Per-user concurrent-trades limit — the user's own setting governs.

    Per the owner directive (2026-06-03), open-position capacity is a PER-USER
    setting, not a global ceiling: when the user has set ``max_concurrent_override``
    it is authoritative and may raise OR lower the limit freely; otherwise the
    user's profile default applies (conservative 5 / balanced 12 / aggressive 20).
    There is no system-wide clamp — a user is no longer forced below their own
    chosen value. (Other capital brakes — Kelly, position cap, daily-loss,
    drawdown, correlated-exposure step 8, kill switch — remain in force.)

    ``user_override`` is None when the user hasn't set ``max_concurrent_override``
    in ``user_settings`` — the profile default governs alone. Negative / zero
    / accidentally non-positive overrides are defensively coerced to the profile
    default so a typo cannot brick a user (gate step 7 would reject every trade
    with ``cur >= 0``). The DB CHECK constraint (1..20) bounds the override at
    write time; this defence handles legacy rows / direct DB writes.
    """
    # Normalise: profile may arrive with mixed case (e.g. 'Conservative' from
    # a UI form) or as None — match the lowercase-default behaviour of
    # ``profile_or_default`` so an upper/title-cased name resolves correctly
    # instead of silently falling back to 'balanced'.
    base = (profile or "balanced").lower()
    if base not in PROFILES:
        base = "balanced"
    profile_cap = int(PROFILES[base]["max_concurrent"])
    # The user's override is authoritative when validly set (≥1) — it may be
    # above or below the profile default. A missing / non-positive / unparseable
    # override falls back to the profile default (never bricks the user).
    if user_override is not None:
        try:
            # Parse via float first so a numeric string like "12.0" (legacy row /
            # direct DB write / API payload) is honoured instead of raising and
            # silently falling back to the profile default.
            ov = int(float(user_override))
        except (TypeError, ValueError):
            ov = 0
        if ov >= 1:
            return ov
    return profile_cap


def profile_or_default(name: str | None) -> dict:
    return PROFILES.get((name or "balanced").lower(), PROFILES["balanced"])


# WARP-83 E.2 (Path C): canonical capital + TP/SL per risk profile.
#
# Risk profile governs CAPITAL SIZING ONLY (capital_alloc_pct). TP/SL is a
# STRATEGY-LEVEL property — the SAME for every profile (Balanced 150% / 50%) —
# NOT a per-profile bundle. A tighter profile (conservative) risks fewer dollars
# via a smaller capital allocation; it does NOT exit faster. The previous
# per-profile TP/SL values (10/5, 20/15, 30/20) were a UX-deception: they were
# written into user_settings on profile/preset activation but the strategy
# applied a hardcoded 150/50 anyway, so the configured numbers were silently
# ignored. The user's configured user_settings.tp_pct / sl_pct is now the single
# source of truth the strategy reads at entry; these defaults seed it to the
# strategy default for non-custom profiles. Fractions (1.5 = +150%). 'custom'
# has no fixed TP/SL — the user supplies them (advanced override).
STRATEGY_DEFAULT_TP_PCT: float = 1.5
STRATEGY_DEFAULT_SL_PCT: float = 0.5

PROFILE_TP_SL: dict[str, dict[str, float]] = {
    "conservative": {"capital_alloc_pct": 0.20, "tp_pct": STRATEGY_DEFAULT_TP_PCT, "sl_pct": STRATEGY_DEFAULT_SL_PCT},
    "balanced":     {"capital_alloc_pct": 0.40, "tp_pct": STRATEGY_DEFAULT_TP_PCT, "sl_pct": STRATEGY_DEFAULT_SL_PCT},
    "aggressive":   {"capital_alloc_pct": 0.60, "tp_pct": STRATEGY_DEFAULT_TP_PCT, "sl_pct": STRATEGY_DEFAULT_SL_PCT},
}


def tp_sl_for_profile(name: str | None) -> dict[str, float]:
    """Canonical capital/TP/SL for a named profile; defaults to balanced.

    Used by preset activation + new-user bootstrap so TP/SL always follows the
    risk profile rather than the activated preset. 'custom' is NOT here — custom
    TP/SL is user-supplied and may be TP-only or SL-only.
    """
    return PROFILE_TP_SL.get((name or "balanced").lower(), PROFILE_TP_SL["balanced"])
