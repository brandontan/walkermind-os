"""Stabilized correlation matrix — Phase 6.6.

Replaces the ad-hoc correlation_matrix dict passed to Phase 6 CorrelationEngine
with a proper stateful estimator that uses:

  1. Rolling Pearson correlation over the last `window` log-returns.
  2. Ledoit–Wolf-style shrinkage toward the identity matrix:
         C_shrunk_ij = (1 - shrinkage_factor) * C_pearson_ij
         (Off-diagonal only; diagonal stays 1.0 implicitly.)
  3. EMA smoothing across recompute cycles to absorb jitter spikes:
         C_ema[t] = alpha * C_shrunk[t] + (1 - alpha) * C_ema[t-1]
         First call initialises with C_shrunk (no history needed).
  4. Minimum data guard: skip a pair entirely if either market has
     fewer than `min_data_points` returns.
  5. NaN-safe: degenerate inputs (constant series, zero stdev) return 0.0.
  6. Output clamped to [-1, 1] at every stage.

Backward compatibility:
    get_matrix() returns the same dict[(str,str), float] interface consumed
    by Phase 6 CorrelationEngine.adjust_all().  The keys are (market_a, market_b)
    in insertion order (i < j lexicographic by first-seen order).
"""
from __future__ import annotations

import math
import statistics
from collections import deque
from dataclasses import dataclass
from typing import Optional

import structlog

log = structlog.get_logger()

# Numerical floor for log-return denominator
_PRICE_FLOOR: float = 1e-9


def _clamp(value: float, lo: float, hi: float) -> float:
    """Clamp a float to [lo, hi]."""
    return max(lo, min(hi, value))


@dataclass
class CorrelationMatrixStats:
    """Diagnostic snapshot produced by each recompute() call."""

    pairs_computed: int
    markets_eligible: int
    markets_total: int
    ema_pairs_total: int
    cycle: int
    correlation_id: str


class CorrelationMatrix:
    """Stabilized rolling correlation matrix with shrinkage and EMA smoothing.

    Designed for single-threaded asyncio use.  All methods are synchronous
    (no I/O); call recompute() from an async context without await.

    Usage::
        matrix = CorrelationMatrix.from_config(cfg)

        # Feed prices each tick:
        matrix.update_price("market_A", 0.62)
        matrix.update_price("market_B", 0.38)

        # Recompute every N ticks:
        corr_dict = matrix.recompute(correlation_id="abc")

        # Pass to Phase 6 CorrelationEngine:
        adjusted = await corr_engine.adjust_all(signals, corr_dict, cid)
    """

    def __init__(
        self,
        window: int = 30,
        min_data_points: int = 30,
        shrinkage_factor: float = 0.7,
        ema_alpha: float = 0.3,
    ) -> None:
        """Initialise with estimation hyperparameters.

        Args:
            window: Number of log-returns to keep per market (rolling buffer).
                    Minimum 2; values < min_data_points will never produce output.
            min_data_points: Minimum returns required before a market is eligible
                    for correlation computation.  Must be <= window.
            shrinkage_factor: Intensity of Ledoit–Wolf shrinkage toward zero
                    (identity off-diagonal).  0.0 = pure Pearson, 1.0 = all zeros.
            ema_alpha: EMA weight on the newest estimate.  0 < alpha <= 1.
                    0.3 → ~3-cycle half-life; lower = smoother but slower.
        """
        if not (2 <= min_data_points <= max(window, 2)):
            raise ValueError(
                f"min_data_points={min_data_points} must be in [2, window={window}]"
            )
        if not 0.0 <= shrinkage_factor <= 1.0:
            raise ValueError(f"shrinkage_factor must be in [0, 1], got {shrinkage_factor}")
        if not 0.0 < ema_alpha <= 1.0:
            raise ValueError(f"ema_alpha must be in (0, 1], got {ema_alpha}")

        self._window = window
        self._min_pts = min_data_points
        self._shrinkage = shrinkage_factor
        self._alpha = ema_alpha

        # Price ring-buffers: market_id → deque(maxlen = window + 1)
        # We keep window+1 prices to compute exactly window returns.
        self._prices: dict[str, deque[float]] = {}

        # EMA-smoothed correlation matrix: (market_a, market_b) → float ∈ [-1, 1]
        self._ema: dict[tuple[str, str], float] = {}

        self._cycle: int = 0

    # ── Price ingestion ───────────────────────────────────────────────────────

    def update_price(self, market_id: str, price: float) -> None:
        """Record a new price observation for a market.

        Safe for any positive float.  Prices <= 0 are silently floored to
        _PRICE_FLOOR to avoid math domain errors in log-return computation.

        Args:
            market_id: Market identifier string.
            price: Latest mid-price.
        """
        safe = max(price, _PRICE_FLOOR)
        if market_id not in self._prices:
            self._prices[market_id] = deque(maxlen=self._window + 1)
        self._prices[market_id].append(safe)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _log_returns(self, market_id: str) -> list[float]:
        """Compute log-returns from stored price history.

        Returns an empty list if fewer than 2 prices are available.
        """
        prices = list(self._prices.get(market_id, []))
        if len(prices) < 2:
            return []
        result: list[float] = []
        for i in range(1, len(prices)):
            denom = max(prices[i - 1], _PRICE_FLOOR)
            try:
                result.append(math.log(prices[i] / denom))
            except (ValueError, ZeroDivisionError):
                result.append(0.0)
        return result

    def _pearson(self, xs: list[float], ys: list[float]) -> float:
        """Pearson correlation using stdlib statistics.correlation (Python 3.10+).

        Returns 0.0 on all degenerate inputs:
          - series too short (< min_data_points)
          - either series is constant (stdev ≈ 0)
          - non-finite result (NaN / inf)
        """
        n = min(len(xs), len(ys), self._window)
        if n < self._min_pts:
            return 0.0

        a = xs[-n:]
        b = ys[-n:]

        # Guard: constant series → stdev = 0 → undefined correlation
        try:
            if statistics.stdev(a) < 1e-12 or statistics.stdev(b) < 1e-12:
                return 0.0
        except statistics.StatisticsError:
            return 0.0

        try:
            corr = statistics.correlation(a, b)
        except (statistics.StatisticsError, ZeroDivisionError):
            return 0.0

        if not math.isfinite(corr):
            return 0.0

        return corr

    def _shrink(self, pearson: float) -> float:
        """Apply Ledoit–Wolf shrinkage toward the identity (zero off-diagonal).

        C_shrunk = (1 - shrinkage_factor) * C_pearson + shrinkage_factor * 0
        """
        return (1.0 - self._shrinkage) * pearson

    # ── Core public API ───────────────────────────────────────────────────────

    def recompute(self, correlation_id: str) -> dict[tuple[str, str], float]:
        """Recompute all pairwise correlations and update EMA.

        Algorithm:
          1. Filter markets to those with >= min_data_points log-returns.
          2. For each eligible pair (i < j by insertion order):
               Pearson → shrink → EMA update.
          3. Clamp every updated EMA value to [-1, 1].
          4. Decay orphaned EMA entries (pairs no longer eligible) toward zero
             by one EMA step; drop when magnitude < 1e-6.
          5. Emit structured log "correlation_update".

        If fewer than 2 markets are eligible, returns the existing (possibly
        empty) EMA matrix unchanged.

        Args:
            correlation_id: Request ID for structured log correlation.

        Returns:
            dict[(market_a, market_b), float] — current EMA-smoothed matrix.
            All keys use the canonical (first-seen, second-seen) ordering.
        """
        self._cycle += 1
        all_markets = list(self._prices.keys())

        # Build return cache once per recompute to avoid redundant computation
        returns_cache: dict[str, list[float]] = {
            mid: self._log_returns(mid) for mid in all_markets
        }
        eligible = [
            mid for mid in all_markets
            if len(returns_cache[mid]) >= self._min_pts
        ]

        new_ema: dict[tuple[str, str], float] = {}

        if len(eligible) >= 2:
            for i in range(len(eligible)):
                for j in range(i + 1, len(eligible)):
                    a, b = eligible[i], eligible[j]
                    pearson = self._pearson(returns_cache[a], returns_cache[b])
                    shrunk = _clamp(self._shrink(pearson), -1.0, 1.0)

                    # EMA: first occurrence → initialise to shrunk (no history bias)
                    prev = self._ema.get((a, b), shrunk)
                    updated = _clamp(
                        self._alpha * shrunk + (1.0 - self._alpha) * prev,
                        -1.0, 1.0,
                    )
                    new_ema[(a, b)] = round(updated, 6)

        # Decay orphaned pairs (not recomputed this cycle) toward zero
        for key, prev_val in self._ema.items():
            if key not in new_ema:
                decayed = (1.0 - self._alpha) * prev_val
                if abs(decayed) > 1e-6:
                    new_ema[key] = round(_clamp(decayed, -1.0, 1.0), 6)
                # else: magnitude negligible — let the pair expire

        self._ema = new_ema

        log.info(
            "correlation_update",
            correlation_id=correlation_id,
            cycle=self._cycle,
            pairs_computed=len(new_ema),
            markets_eligible=len(eligible),
            markets_total=len(all_markets),
            shrinkage_factor=self._shrinkage,
            ema_alpha=self._alpha,
            window=self._window,
        )

        return dict(self._ema)

    def get(self, market_a: str, market_b: str) -> float:
        """Return smoothed correlation between two markets.

        Checks both key orderings.  Returns 0.0 if the pair is unknown
        (insufficient data or never computed).

        Args:
            market_a: First market ID.
            market_b: Second market ID.
        """
        return self._ema.get(
            (market_a, market_b),
            self._ema.get((market_b, market_a), 0.0),
        )

    def get_matrix(self) -> dict[tuple[str, str], float]:
        """Return a snapshot copy of the current EMA correlation matrix.

        Compatible with Phase 6 CorrelationEngine.adjust_all() interface.
        """
        return dict(self._ema)

    def market_count(self) -> int:
        """Return the number of markets currently being tracked."""
        return len(self._prices)

    def eligible_market_count(self) -> int:
        """Return markets with enough return history for correlation."""
        return sum(
            1 for mid in self._prices
            if len(self._log_returns(mid)) >= self._min_pts
        )

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_config(cls, cfg: dict) -> "CorrelationMatrix":
        """Construct from a config dict (reads the 'correlation' sub-block).

        Args:
            cfg: Top-level config dict loaded from config.yaml.

        Example YAML::
            correlation:
              window: 50
              min_data_points: 30
              shrinkage_factor: 0.7
              ema_alpha: 0.3
        """
        c = cfg.get("correlation", {})
        window = int(c.get("window", 30))
        min_pts = int(c.get("min_data_points", 30))
        # Clamp min_pts to window if config is inconsistent
        min_pts = min(min_pts, window)
        return cls(
            window=window,
            min_data_points=min_pts,
            shrinkage_factor=float(c.get("shrinkage_factor", 0.7)),
            ema_alpha=float(c.get("ema_alpha", 0.3)),
        )
