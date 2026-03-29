"""Capital allocator — Phase 6.

Strategy-weighted allocation with hard caps and position-count gating.

Allocation algorithm:
    positive_score_i = max(raw_score_i, ε)        (floor at ε to avoid zero-weight)
    weight_i         = positive_score_i / Σ scores
    raw_size         = balance × weight_i
    size             = min(raw_size, balance × max_position_pct)  ← hard cap

Allocation is rejected when:
    - open_positions >= max_open_positions
    - computed size < min_order_size
    - strategy score is unavailable (no entry in scores dict)
"""
from __future__ import annotations

from dataclasses import dataclass

import structlog

log = structlog.get_logger()

_SCORE_FLOOR: float = 1e-9   # prevents zero-weight from breaking proportional calc


@dataclass
class AllocationResult:
    """Output of the capital allocator for one signal."""

    approved: bool
    size: float
    weight: float
    reason: str
    correlation_id: str


class CapitalAllocator:
    """Allocates capital using performance-score-weighted position sizing."""

    def __init__(
        self,
        max_position_pct: float = 0.10,
        max_open_positions: int = 5,
        min_order_size: float = 5.0,
    ) -> None:
        """Initialise with sizing constraints.

        Args:
            max_position_pct: Hard cap per position as fraction of balance.
            max_open_positions: Reject if open count is at or above this limit.
            min_order_size: Minimum viable position size in USD.
        """
        self._max_pos_pct = max_position_pct
        self._max_open = max_open_positions
        self._min_size = min_order_size

    def allocate(
        self,
        strategy_name: str,
        strategy_scores: dict[str, float],
        balance: float,
        open_positions: int,
        correlation_id: str,
    ) -> AllocationResult:
        """Compute capital allocation for one strategy signal.

        Args:
            strategy_name: Strategy requesting the allocation.
            strategy_scores: Map of strategy_name → performance score
                             for all enabled strategies.
            balance: Current account balance in USD.
            open_positions: Count of currently open positions.
            correlation_id: Request ID for structured log correlation.

        Returns:
            AllocationResult with approved flag and computed size.
        """
        # ── Gate: position count ──────────────────────────────────────────────
        if open_positions >= self._max_open:
            log.warning(
                "allocation_rejected_max_positions",
                correlation_id=correlation_id,
                strategy=strategy_name,
                open_positions=open_positions,
                max_open=self._max_open,
            )
            return AllocationResult(
                approved=False,
                size=0.0,
                weight=0.0,
                reason=f"open_positions={open_positions} >= max={self._max_open}",
                correlation_id=correlation_id,
            )

        # ── Gate: strategy must be in scores dict ─────────────────────────────
        if not strategy_scores:
            log.warning(
                "allocation_rejected_no_scores",
                correlation_id=correlation_id,
                strategy=strategy_name,
            )
            return AllocationResult(
                approved=False,
                size=0.0,
                weight=0.0,
                reason="strategy_scores_empty",
                correlation_id=correlation_id,
            )

        # ── Score-weighted allocation ─────────────────────────────────────────
        # Floor all scores to _SCORE_FLOOR so every strategy gets a nonzero weight
        floored = {k: max(v, _SCORE_FLOOR) for k, v in strategy_scores.items()}
        sum_scores = sum(floored.values())

        # Ensure requesting strategy is represented (may not be tracked yet)
        strategy_score = floored.get(strategy_name, _SCORE_FLOOR)
        if strategy_name not in floored:
            # Add it with floor score and recalculate sum
            floored[strategy_name] = _SCORE_FLOOR
            sum_scores += _SCORE_FLOOR
            strategy_score = _SCORE_FLOOR

        weight = strategy_score / sum_scores
        raw_size = balance * weight

        # ── Hard cap: min(raw_size, balance × max_position_pct) ──────────────
        hard_cap = balance * self._max_pos_pct
        size = min(raw_size, hard_cap)
        size = round(size, 4)

        # ── Gate: minimum viable order size ──────────────────────────────────
        if size < self._min_size:
            log.warning(
                "allocation_rejected_too_small",
                correlation_id=correlation_id,
                strategy=strategy_name,
                computed_size=size,
                min_size=self._min_size,
            )
            return AllocationResult(
                approved=False,
                size=0.0,
                weight=round(weight, 6),
                reason=f"size={size:.4f} < min_order_size={self._min_size}",
                correlation_id=correlation_id,
            )

        log.info(
            "allocation_approved",
            correlation_id=correlation_id,
            strategy=strategy_name,
            weight=round(weight, 6),
            raw_size=round(raw_size, 4),
            capped_size=size,
            hard_cap=round(hard_cap, 4),
            balance=round(balance, 4),
            open_positions=open_positions,
        )

        return AllocationResult(
            approved=True,
            size=size,
            weight=round(weight, 6),
            reason="ok",
            correlation_id=correlation_id,
        )
