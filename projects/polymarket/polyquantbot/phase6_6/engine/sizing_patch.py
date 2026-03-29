"""Soft correlation-aware position sizing — Phase 6.6.

Replaces the Phase 6 CapitalAllocator's hard position-count rejection
with a continuous size reduction proportional to portfolio correlation.
Positions are still possible even when correlated — they are simply smaller.

Algorithm::

    # 1. For each open position, look up correlation with the new signal's market
    for pos_market_id in open_position_market_ids:
        corr = correlation_matrix.get(signal_market_id, pos_market_id)  # or dict lookup
        if corr > 0:
            positive_correlations.append(corr)

    # 2. Sum positive correlations, cap at 1.0
    total_corr = min(sum(positive_correlations), 1.0)

    # 3. Reduce size proportionally (max 80% reduction)
    adjusted_size = size × (1 − min(total_corr, 0.8))

    # 4. Reject if size falls below min_order_size
    if adjusted_size < min_order_size:
        return SizingResult(approved=False, ...)

Design notes:
    - Uses ONLY positive correlations.  Negative correlations (hedges) do NOT
      increase size to avoid accidental leverage.
    - Cap at 0.8 (80% reduction max) prevents a full-zero size from rounding
      issues; the remaining 20% is the minimum floor for highly correlated books.
    - cap total_corr at 1.0 prevents the sum of several moderate correlations
      from producing an implausibly large multiplier.
    - Backward compatible: SizingResult exposes approved, adjusted_size, reason,
      and correlation_id — same fields as AllocationResult from Phase 6.

Missing data handling:
    - If correlation is unknown (market pair not in matrix), correlation defaults
      to 0.0 (treat as uncorrelated) — conservative, never inflates reduction.
    - If open_positions is empty, total_corr = 0, no adjustment applied.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import structlog

log = structlog.get_logger()


def _clamp(value: float, lo: float, hi: float) -> float:
    """Clamp a float to [lo, hi]."""
    return max(lo, min(hi, value))


@dataclass
class SizingResult:
    """Output of SizingPatch.apply().

    Compatible field subset with Phase 6 AllocationResult:
        approved, size (→ adjusted_size), reason, correlation_id.
    """

    approved: bool
    adjusted_size: float
    original_size: float
    total_corr: float
    reduction_factor: float     # (1 − min(total_corr, 0.8))
    n_correlated_positions: int
    reason: str
    correlation_id: str


class SizingPatch:
    """Reduces position size based on correlation with the existing portfolio.

    Stateless: all correlation data is passed per call.
    Safe for concurrent asyncio use.
    """

    def __init__(
        self,
        min_order_size: float = 5.0,
        corr_cap: float = 0.8,       # maximum reduction fraction (80%)
        total_corr_cap: float = 1.0,  # cap on summed positive correlations
    ) -> None:
        """Initialise the sizing patch.

        Args:
            min_order_size: Minimum viable order size (USD).  Reject if adjusted
                            size falls below this.
            corr_cap: Maximum fraction of size reduction allowed (0–1).
                      Default 0.8 preserves at least 20% of original size.
            total_corr_cap: Cap on the sum of positive correlations before
                            applying the reduction factor.  Default 1.0.
        """
        if not 0.0 < corr_cap < 1.0:
            raise ValueError(f"corr_cap must be in (0, 1), got {corr_cap}")
        if total_corr_cap <= 0:
            raise ValueError(f"total_corr_cap must be > 0, got {total_corr_cap}")

        self._min_size = min_order_size
        self._corr_cap = corr_cap
        self._total_corr_cap = total_corr_cap

    def apply(
        self,
        signal_market_id: str,
        size: float,
        open_position_market_ids: list[str],
        correlation_matrix: dict[tuple[str, str], float],
        correlation_id: str,
    ) -> SizingResult:
        """Compute correlation-adjusted position size.

        Args:
            signal_market_id: Market ID of the new signal.
            size: Proposed size from CapitalAllocator (USD).
            open_position_market_ids: List of market IDs for currently open positions.
            correlation_matrix: Pairwise correlation dict (from CorrelationMatrix.get_matrix()).
                                 Keys are (market_a, market_b) tuples; values ∈ [-1, 1].
            correlation_id: Request ID for structured log.

        Returns:
            SizingResult with approved flag and adjusted_size.
        """
        if size <= 0:
            return SizingResult(
                approved=False,
                adjusted_size=0.0,
                original_size=size,
                total_corr=0.0,
                reduction_factor=1.0,
                n_correlated_positions=0,
                reason="size_zero_or_negative",
                correlation_id=correlation_id,
            )

        # ── Step 1: Collect positive correlations to open positions ───────────
        positive_corrs: list[float] = []
        for pos_mid in open_position_market_ids:
            if pos_mid == signal_market_id:
                continue  # skip self-correlation
            # Check both orderings in the correlation matrix
            corr = correlation_matrix.get(
                (signal_market_id, pos_mid),
                correlation_matrix.get((pos_mid, signal_market_id), 0.0),
            )
            if corr > 0:
                positive_corrs.append(corr)

        # ── Step 2: Sum positive correlations, cap at total_corr_cap ─────────
        raw_total = sum(positive_corrs)
        total_corr = min(raw_total, self._total_corr_cap)

        # ── Step 3: Compute reduction factor ─────────────────────────────────
        # reduction = min(total_corr, corr_cap) ensures max corr_cap reduction
        reduction = min(total_corr, self._corr_cap)
        factor = round(1.0 - reduction, 6)         # always ∈ [1-corr_cap, 1.0]

        adjusted_size = round(size * factor, 4)

        # ── Step 4: Enforce minimum order size ────────────────────────────────
        if adjusted_size < self._min_size:
            log.warning(
                "sizing_rejected_below_min",
                correlation_id=correlation_id,
                signal_market_id=signal_market_id,
                original_size=round(size, 4),
                adjusted_size=adjusted_size,
                total_corr=round(total_corr, 4),
                reduction_factor=factor,
                min_order_size=self._min_size,
                n_correlated_positions=len(positive_corrs),
            )
            return SizingResult(
                approved=False,
                adjusted_size=0.0,
                original_size=size,
                total_corr=round(total_corr, 4),
                reduction_factor=factor,
                n_correlated_positions=len(positive_corrs),
                reason=f"adjusted_size={adjusted_size:.4f} < min_order_size={self._min_size}",
                correlation_id=correlation_id,
            )

        log.info(
            "sizing_adjustment",
            correlation_id=correlation_id,
            signal_market_id=signal_market_id,
            original_size=round(size, 4),
            adjusted_size=adjusted_size,
            total_corr=round(total_corr, 4),
            raw_total_corr=round(raw_total, 4),
            reduction_factor=factor,
            n_open_positions=len(open_position_market_ids),
            n_correlated_positions=len(positive_corrs),
        )

        return SizingResult(
            approved=True,
            adjusted_size=adjusted_size,
            original_size=size,
            total_corr=round(total_corr, 4),
            reduction_factor=factor,
            n_correlated_positions=len(positive_corrs),
            reason="ok",
            correlation_id=correlation_id,
        )

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_config(cls, cfg: dict) -> "SizingPatch":
        """Build from top-level config dict.

        Reads min_order_size from capital_allocator block.
        Uses hardcoded defaults for corr_cap and total_corr_cap.

        Args:
            cfg: Top-level config dict loaded from config.yaml.
        """
        ca = cfg.get("capital_allocator", {})
        return cls(
            min_order_size=float(ca.get("min_order_size", 5.0)),
        )
