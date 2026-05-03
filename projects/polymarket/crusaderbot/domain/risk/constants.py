"""Hard-wired risk constants. PR-protected — never override at runtime."""
from __future__ import annotations

KELLY_FRACTION: float = 0.25
MAX_POSITION_PCT: float = 0.10
MAX_CORRELATED_EXPOSURE: float = 0.40
MAX_CONCURRENT_TRADES: int = 5
DAILY_LOSS_HARD_STOP: float = -2_000.0
MAX_DRAWDOWN_HALT: float = 0.08
MIN_LIQUIDITY: float = 10_000.0
MIN_EDGE_BPS: int = 200
SIGNAL_STALE_SECONDS: int = 300
DEDUP_WINDOW_SECONDS: int = 300

PROFILES: dict[str, dict[str, float | int]] = {
    "conservative": {
        "kelly": 0.10,
        "max_pos_pct": 0.03,
        "max_concurrent": 3,
        "daily_loss": -200.0,
        "min_edge_bps": 400,
        "min_liquidity": 20_000.0,
        "max_days": 7,
    },
    "balanced": {
        "kelly": 0.20,
        "max_pos_pct": 0.06,
        "max_concurrent": 5,
        "daily_loss": -500.0,
        "min_edge_bps": 300,
        "min_liquidity": 15_000.0,
        "max_days": 30,
    },
    "aggressive": {
        "kelly": 0.25,
        "max_pos_pct": 0.10,
        "max_concurrent": 5,
        "daily_loss": -1_000.0,
        "min_edge_bps": 200,
        "min_liquidity": 10_000.0,
        "max_days": 90,
    },
}

STRATEGY_AVAILABILITY: dict[str, list[str]] = {
    "copy_trade": ["conservative", "balanced", "aggressive"],
    "signal": ["conservative", "balanced", "aggressive"],
    "value": ["balanced", "aggressive"],
    "momentum": ["aggressive"],
}


def effective_daily_loss(
    profile: str, user_override: float | None = None
) -> float:
    """Most-restrictive cap among system hard stop, profile cap, optional user lower-bound.

    All caps are negative. "Most restrictive" = closest to zero, so max() of negatives.
    User can only restrict downward (smaller magnitude), never relax above profile cap.
    """
    if profile not in PROFILES:
        raise ValueError(f"unknown risk profile: {profile}")
    caps: list[float] = [DAILY_LOSS_HARD_STOP, float(PROFILES[profile]["daily_loss"])]
    if user_override is not None:
        caps.append(user_override)
    return max(caps)
