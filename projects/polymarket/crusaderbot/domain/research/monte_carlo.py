"""Monte Carlo robustness simulator (Phase-2c, blueprint §12.2).

Dependency-free (stdlib only) bootstrap resampler. Given a module's *realized*
per-trade return fractions (``pnl_usdc / size_usdc`` from closed positions), it
resamples equity paths at a risk profile's per-trade sizing and estimates the
tail risks the robustness classifier gates against:

* **risk-of-ruin** — fraction of paths whose equity falls to/below a ruin floor;
* **drawdown depth** — distribution of each path's max drawdown (P95 + median);
* **losing-streak** — distribution of each path's longest losing run (P95).

Sizing model: a position consumes a fixed ``bet_fraction`` of current equity
(the profile's ``max_pos_pct`` cap — the real per-position bound), so one trade
moves equity by ``bet_fraction × r`` where ``r`` is the resampled realized
return fraction. This is a deliberately conservative upper bound on path
volatility; it does not re-derive Kelly (the realized ``r`` already embeds the
trade outcome). Pure function — no DB, no I/O, seedable for deterministic tests.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from statistics import mean


@dataclass(frozen=True)
class MCResult:
    """Aggregate tail-risk metrics across all simulated paths."""

    sample_size: int          # number of realized trades fed in
    n_paths: int              # simulated equity paths
    horizon: int              # trades per path
    ev_per_trade: float       # mean realized return fraction (pnl/size)
    ruin_probability: float   # fraction of paths that hit the ruin floor
    p95_max_drawdown: float   # 95th-pct of per-path max drawdown fraction
    median_max_drawdown: float
    p95_losing_streak: int    # 95th-pct of per-path longest losing run


def _percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile (pct in [0, 100]); empty → 0.0."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    # Nearest-rank: ceil(P/100 · N). ceil (not round) avoids banker's-rounding
    # downward bias on exact-half ranks.
    rank = max(1, min(len(ordered), math.ceil(pct / 100.0 * len(ordered))))
    return ordered[rank - 1]


def simulate(
    returns: list[float],
    *,
    bet_fraction: float,
    n_paths: int = 2_000,
    horizon: int = 200,
    ruin_floor: float = 0.5,
    seed: int | None = None,
) -> MCResult:
    """Resample ``returns`` into equity paths and return tail-risk metrics.

    ``bet_fraction`` is the share of current equity each position consumes
    (profile ``max_pos_pct``). ``ruin_floor`` is the equity fraction (of the
    1.0 start) considered ruin — default 0.5 (a 50% drawdown). ``horizon`` is
    trades per path. Empty/degenerate input → a zeroed result with the real
    sample size so the caller can mark INSUFFICIENT_DATA.
    """
    n = len(returns)
    if n == 0 or bet_fraction <= 0.0:
        return MCResult(n, 0, horizon, 0.0, 0.0, 0.0, 0.0, 0)

    rng = random.Random(seed)
    ev = mean(returns)
    max_drawdowns: list[float] = []
    losing_streaks: list[int] = []
    ruined = 0

    for _ in range(n_paths):
        equity = 1.0
        peak = 1.0
        max_dd = 0.0
        streak = 0
        worst_streak = 0
        hit_ruin = False
        for _ in range(horizon):
            r = returns[rng.randrange(n)]  # bootstrap with replacement
            equity *= 1.0 + bet_fraction * r
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd
            if r < 0.0:
                streak += 1
                if streak > worst_streak:
                    worst_streak = streak
            else:
                streak = 0
            if equity <= ruin_floor:
                hit_ruin = True
                break
        if hit_ruin:
            ruined += 1
        max_drawdowns.append(max_dd)
        losing_streaks.append(worst_streak)

    return MCResult(
        sample_size=n,
        n_paths=n_paths,
        horizon=horizon,
        ev_per_trade=ev,
        ruin_probability=ruined / n_paths,
        p95_max_drawdown=_percentile(max_drawdowns, 95.0),
        median_max_drawdown=_percentile(max_drawdowns, 50.0),
        p95_losing_streak=int(_percentile([float(s) for s in losing_streaks], 95.0)),
    )


__all__ = ["MCResult", "simulate"]
