"""Adaptive exit engine — Phase 6.6.

Replaces the static TP/SL percentages in Phase 6 config with
volatility-calibrated levels computed from the most recent 20 returns.

Algorithm::

    # 1. Realised volatility from last 20 log-returns
    if len(returns) >= 20:
        vol = stdev(returns[-20:])
    else:
        vol = default_vol          # config fallback

    # 2. Volatility floor (prevent infinitesimally tight levels)
    vol = max(vol, 0.01)

    # 3. TP / SL fractions — clamped to configured bounds
    tp_pct = clamp(tp_vol_multiplier × vol,  tp_min,  tp_max)   # default: clamp(2*vol, 0.02, 0.15)
    sl_pct = clamp(sl_vol_multiplier × vol,  sl_min,  sl_max)   # default: clamp(1*vol, 0.01, 0.10)

    # 4. Price levels from entry
    tp_price = entry_price × (1 + tp_pct)
    sl_price = entry_price × (1 − sl_pct)

Design notes:
    - No interface change vs Phase 6: callers that used (tp_pct, sl_pct) from
      config.yaml simply call compute_levels() instead and get the same shape.
    - Deterministic: given identical returns and entry_price → identical output.
    - Extreme volatility spike: alpha_buffer in execution already accounts for
      this; here we additionally cap tp/sl at tp_max/sl_max to prevent
      positions with unreachable profit targets or excessively wide stops.
    - Empty returns list: falls back to default_vol gracefully.
    - Single-element returns list: statistics.stdev requires >= 2 samples;
      falls back to default_vol.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Optional

import structlog

log = structlog.get_logger()


def _clamp(value: float, lo: float, hi: float) -> float:
    """Clamp a float to the closed interval [lo, hi]."""
    return max(lo, min(hi, value))


@dataclass
class ExitLevels:
    """Computed adaptive TP / SL levels for one position."""

    tp_price: float           # take-profit absolute price
    sl_price: float           # stop-loss absolute price
    tp_pct: float             # TP fraction of entry_price
    sl_pct: float             # SL fraction of entry_price
    realised_vol: float       # volatility used (after floor)
    raw_vol: float            # volatility before floor
    vol_source: str           # "computed" | "default_vol"
    entry_price: float
    correlation_id: str


class ExitEnginePatch:
    """Computes volatility-calibrated TP / SL exit levels.

    Stateless: all state is passed in per call.  Safe for concurrent asyncio use.
    """

    def __init__(
        self,
        default_vol: float = 0.02,
        tp_vol_multiplier: float = 2.0,
        sl_vol_multiplier: float = 1.0,
        tp_min: float = 0.02,
        tp_max: float = 0.15,
        sl_min: float = 0.01,
        sl_max: float = 0.10,
        vol_lookback: int = 20,
    ) -> None:
        """Initialise exit engine parameters.

        Args:
            default_vol: Fallback volatility when insufficient return history.
            tp_vol_multiplier: tp_pct = clamp(tp_vol_multiplier × vol, tp_min, tp_max).
            sl_vol_multiplier: sl_pct = clamp(sl_vol_multiplier × vol, sl_min, sl_max).
            tp_min: Minimum TP fraction (prevent over-tight profit targets).
            tp_max: Maximum TP fraction (prevent unreachable targets in high vol).
            sl_min: Minimum SL fraction (always some downside protection).
            sl_max: Maximum SL fraction (cap stop width in high vol).
            vol_lookback: Number of most-recent returns to use (default 20).
        """
        if default_vol <= 0:
            raise ValueError(f"default_vol must be > 0, got {default_vol}")
        if not (0 < sl_min <= sl_max <= 1):
            raise ValueError(f"Invalid SL bounds: [{sl_min}, {sl_max}]")
        if not (0 < tp_min <= tp_max <= 1):
            raise ValueError(f"Invalid TP bounds: [{tp_min}, {tp_max}]")

        self._default_vol = default_vol
        self._tp_mult = tp_vol_multiplier
        self._sl_mult = sl_vol_multiplier
        self._tp_min = tp_min
        self._tp_max = tp_max
        self._sl_min = sl_min
        self._sl_max = sl_max
        self._lookback = vol_lookback

    # ── Volatility estimation ─────────────────────────────────────────────────

    def estimate_volatility(self, returns: list[float]) -> tuple[float, str]:
        """Estimate realised volatility from recent log-returns.

        Uses the last `vol_lookback` returns.  Falls back to default_vol
        if fewer than 2 returns are available or stdev is undefined.

        Args:
            returns: List of log-returns (newest last).

        Returns:
            (raw_vol, source) where source is "computed" or "default_vol".
        """
        window = returns[-self._lookback:] if len(returns) >= self._lookback else returns

        if len(window) < 2:
            return self._default_vol, "default_vol"

        try:
            raw_vol = statistics.stdev(window)
        except statistics.StatisticsError:
            return self._default_vol, "default_vol"

        if not math.isfinite(raw_vol) or raw_vol < 0:
            return self._default_vol, "default_vol"

        return raw_vol, "computed"

    # ── Core API ──────────────────────────────────────────────────────────────

    def compute_levels(
        self,
        entry_price: float,
        returns: list[float],
        correlation_id: str,
        market_id: Optional[str] = None,
    ) -> ExitLevels:
        """Compute adaptive TP / SL levels for an open position.

        Interface:
            Input:  entry_price (float), returns (list[float])
            Output: ExitLevels dataclass with tp_price, sl_price, tp_pct, sl_pct

        This is a drop-in replacement for reading position.tp_pct / sl_pct
        from the static config.

        Args:
            entry_price: Position entry price. Must be > 0.
            returns: Log-returns for this market (newest last).
                     Fewer than 2 → uses default_vol.
            correlation_id: Request ID for structured log.
            market_id: Optional market ID for log context.

        Returns:
            ExitLevels with all computed values.
        """
        if entry_price <= 0:
            raise ValueError(f"entry_price must be > 0, got {entry_price}")

        # ── Step 1: Realised volatility ───────────────────────────────────────
        raw_vol, vol_source = self.estimate_volatility(returns)

        # ── Step 2: Volatility floor ──────────────────────────────────────────
        vol = max(raw_vol, 0.01)

        # ── Step 3: TP / SL fractions ─────────────────────────────────────────
        tp_pct = round(_clamp(self._tp_mult * vol, self._tp_min, self._tp_max), 6)
        sl_pct = round(_clamp(self._sl_mult * vol, self._sl_min, self._sl_max), 6)

        # ── Step 4: Absolute price levels ─────────────────────────────────────
        tp_price = round(entry_price * (1.0 + tp_pct), 6)
        sl_price = round(entry_price * (1.0 - sl_pct), 6)
        # Clamp to valid probability range [0.01, 0.99] for prediction markets
        tp_price = _clamp(tp_price, 0.01, 0.99)
        sl_price = _clamp(sl_price, 0.01, 0.99)

        result = ExitLevels(
            tp_price=tp_price,
            sl_price=sl_price,
            tp_pct=tp_pct,
            sl_pct=sl_pct,
            realised_vol=round(vol, 6),
            raw_vol=round(raw_vol, 6),
            vol_source=vol_source,
            entry_price=entry_price,
            correlation_id=correlation_id,
        )

        log.info(
            "adaptive_exit_levels",
            correlation_id=correlation_id,
            market_id=market_id,
            entry_price=entry_price,
            tp_price=tp_price,
            sl_price=sl_price,
            tp_pct=tp_pct,
            sl_pct=sl_pct,
            vol=round(vol, 6),
            raw_vol=round(raw_vol, 6),
            vol_source=vol_source,
            returns_used=min(len(returns), self._lookback),
        )

        return result

    def should_exit(
        self,
        current_price: float,
        levels: ExitLevels,
        elapsed_minutes: float,
        timeout_minutes: float,
    ) -> Optional[str]:
        """Evaluate whether a position should be exited.

        Args:
            current_price: Latest market price.
            levels: ExitLevels from compute_levels().
            elapsed_minutes: Time since trade opened.
            timeout_minutes: Maximum holding period (from config).

        Returns:
            Exit reason string ("TP" | "SL" | "TIMEOUT") or None if no exit.
        """
        if current_price >= levels.tp_price:
            return "TP"
        if current_price <= levels.sl_price:
            return "SL"
        if elapsed_minutes >= timeout_minutes:
            return "TIMEOUT"
        return None

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_config(cls, cfg: dict) -> "ExitEnginePatch":
        """Build from top-level config dict (reads 'position' block).

        Args:
            cfg: Top-level config dict loaded from config.yaml.
        """
        p = cfg.get("position", {})
        return cls(
            default_vol=float(p.get("default_vol", 0.02)),
            tp_vol_multiplier=float(p.get("tp_vol_multiplier", 2.0)),
            sl_vol_multiplier=float(p.get("sl_vol_multiplier", 1.0)),
            tp_min=float(p.get("tp_min", 0.02)),
            tp_max=float(p.get("tp_max", 0.15)),
            sl_min=float(p.get("sl_min", 0.01)),
            sl_max=float(p.get("sl_max", 0.10)),
        )
