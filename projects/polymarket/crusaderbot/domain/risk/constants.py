"""HARD-WIRED risk constants — NOT overridable by env, yaml, or DB."""
from __future__ import annotations

KELLY_FRACTION = 0.25
MAX_POSITION_PCT = 0.10
MAX_CORRELATED_EXPOSURE = 0.40
MAX_CONCURRENT_TRADES = 5
DAILY_LOSS_HARD_STOP = -2_000.0
MAX_DRAWDOWN_HALT = 0.08
MIN_LIQUIDITY = 10_000.0
MIN_EDGE_BPS = 200
SIGNAL_STALE_SECONDS = 300
DEDUP_WINDOW_SECONDS = 300

# Slippage / market-impact guardrails (gate step 14).
# MAX_MARKET_IMPACT_PCT: reject if size_usdc / market_liquidity exceeds this.
# Prevents a single order from consuming more than 5% of visible depth.
MAX_MARKET_IMPACT_PCT = 0.05
# MAX_SLIPPAGE_PCT: maximum tolerated price deviation from mid for live orders.
# Not enforced in paper mode; validated by the readiness check before live activation.
MAX_SLIPPAGE_PCT = 0.03

PROFILES: dict[str, dict] = {
    "conservative": {
        "kelly": 0.10, "max_pos_pct": 0.03, "max_concurrent": 3,
        "daily_loss": -200.0, "min_edge_bps": 400,
        "min_liquidity": 20_000.0, "max_days": 7,
    },
    "balanced": {
        "kelly": 0.20, "max_pos_pct": 0.06, "max_concurrent": 5,
        "daily_loss": -500.0, "min_edge_bps": 300,
        "min_liquidity": 15_000.0, "max_days": 30,
    },
    "aggressive": {
        "kelly": 0.25, "max_pos_pct": 0.10, "max_concurrent": 5,
        "daily_loss": -1_000.0, "min_edge_bps": 200,
        "min_liquidity": 10_000.0, "max_days": 90,
    },
}

STRATEGY_AVAILABILITY: dict[str, list[str]] = {
    "copy_trade": ["conservative", "balanced", "aggressive"],
    "signal":     ["conservative", "balanced", "aggressive"],
    "signal_following": ["conservative", "balanced", "aggressive"],
    "value":      ["balanced", "aggressive"],   # Phase R6b+
    "momentum":   ["aggressive"],               # Phase R9+
    "momentum_reversal": ["balanced", "aggressive"],
}


def effective_daily_loss(profile: str, user_override: float | None = None) -> float:
    """Most restrictive of: system cap, profile cap, user lower override."""
    caps = [DAILY_LOSS_HARD_STOP, PROFILES[profile]["daily_loss"]]
    if user_override is not None:
        caps.append(float(user_override))
    return max(caps)  # max of negatives = least negative = most restrictive


def profile_or_default(name: str | None) -> dict:
    return PROFILES.get((name or "balanced").lower(), PROFILES["balanced"])
