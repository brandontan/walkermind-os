"""Volatility regime filter — Phase 6.6.

Applies a simple size haircut in high-volatility regimes to reduce
exposure when markets are stressed.

Rule::

    if volatility > high_vol_threshold:
        adjusted_size = size × reduction_factor    # default: × 0.5
    else:
        adjusted_size = size                        # no change

The filter is deliberately simple and linear.  It acts as a last gate
before order sizing is finalized, after CapitalAllocator and SizingPatch.

Design notes:
    - Threshold and reduction_factor are config-driven; no hardcoded values.
    - The filter is idempotent: applying it twice with the same volatility
      and threshold produces size × factor², which is intentionally not
      prevented here (callers should apply it once per cycle).
    - Zero-size input → returns zero with approved=False.
    - Negative size → raises ValueError (caller bug).
    - Result is always >= 0; never negative due to reduction_factor ∈ (0, 1].
    - If adjusted_size < min_order_size after reduction → approved=False.

Structured logging:
    Every call logs "volatility_filter_applied" at DEBUG level with
    regime ("high" | "normal"), original_size, adjusted_size, volatility,
    and threshold.
"""
from __future__ import annotations

from dataclasses import dataclass

import structlog

log = structlog.get_logger()


@dataclass
class VolatilityFilterResult:
    """Output of VolatilityFilter.apply()."""

    approved: bool
    adjusted_size: float
    original_size: float
    regime: str             # "high" | "normal"
    volatility: float
    threshold: float
    reduction_applied: bool
    correlation_id: str


class VolatilityFilter:
    """Reduces position size in high-volatility regimes.

    Stateless — all inputs are passed per call.
    """

    def __init__(
        self,
        high_vol_threshold: float = 0.03,
        reduction_factor: float = 0.5,
        min_order_size: float = 5.0,
    ) -> None:
        """Initialise the volatility filter.

        Args:
            high_vol_threshold: Realised volatility above which the reduction
                                is triggered.  Measured as stdev of log-returns.
                                Default 0.03 (3%) matches execution config.
            reduction_factor: Multiplicative size reduction in high-vol regime.
                              0.5 = halve the size.  Must be ∈ (0, 1].
            min_order_size: Minimum viable order size (USD).  Orders that fall
                            below this after reduction are rejected.
        """
        if not 0.0 < reduction_factor <= 1.0:
            raise ValueError(f"reduction_factor must be in (0, 1], got {reduction_factor}")
        if high_vol_threshold <= 0:
            raise ValueError(f"high_vol_threshold must be > 0, got {high_vol_threshold}")

        self._threshold = high_vol_threshold
        self._factor = reduction_factor
        self._min_size = min_order_size

    def apply(
        self,
        size: float,
        volatility: float,
        correlation_id: str,
        market_id: str = "",
    ) -> VolatilityFilterResult:
        """Apply volatility regime filter to a proposed order size.

        Args:
            size: Proposed size after CapitalAllocator + SizingPatch (USD).
            volatility: Current realised volatility for this market.
            correlation_id: Request ID for structured log.
            market_id: Optional market context for log clarity.

        Returns:
            VolatilityFilterResult with adjusted_size and regime.
        """
        if size < 0:
            raise ValueError(f"size must be >= 0, got {size}")

        if size == 0.0:
            return VolatilityFilterResult(
                approved=False,
                adjusted_size=0.0,
                original_size=size,
                regime="normal",
                volatility=volatility,
                threshold=self._threshold,
                reduction_applied=False,
                correlation_id=correlation_id,
            )

        is_high_vol = volatility > self._threshold
        regime = "high" if is_high_vol else "normal"
        adjusted_size = round(size * self._factor, 4) if is_high_vol else size
        reduction_applied = is_high_vol

        approved = adjusted_size >= self._min_size

        log.debug(
            "volatility_filter_applied",
            correlation_id=correlation_id,
            market_id=market_id,
            regime=regime,
            volatility=round(volatility, 6),
            threshold=self._threshold,
            original_size=round(size, 4),
            adjusted_size=adjusted_size,
            reduction_applied=reduction_applied,
            reduction_factor=self._factor if reduction_applied else 1.0,
            approved=approved,
        )

        if not approved:
            log.warning(
                "volatility_filter_rejected_size",
                correlation_id=correlation_id,
                market_id=market_id,
                adjusted_size=adjusted_size,
                min_order_size=self._min_size,
                regime=regime,
            )

        return VolatilityFilterResult(
            approved=approved,
            adjusted_size=adjusted_size if approved else 0.0,
            original_size=size,
            regime=regime,
            volatility=volatility,
            threshold=self._threshold,
            reduction_applied=reduction_applied,
            correlation_id=correlation_id,
        )

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_config(cls, cfg: dict) -> "VolatilityFilter":
        """Build from top-level config dict.

        Reads 'execution.high_vol_threshold' and 'capital_allocator.min_order_size'.

        Args:
            cfg: Top-level config dict loaded from config.yaml.
        """
        e = cfg.get("execution", {})
        ca = cfg.get("capital_allocator", {})
        return cls(
            high_vol_threshold=float(e.get("high_vol_threshold", 0.03)),
            reduction_factor=float(e.get("vol_reduction_factor", 0.5)),
            min_order_size=float(ca.get("min_order_size", 5.0)),
        )
