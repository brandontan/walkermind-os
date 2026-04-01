"""Phase 13 — DynamicCapitalAllocator: Performance-based strategy weighting.

Implements dynamic capital allocation for the multi-strategy system using a
scoring model that rewards high-EV, high-confidence strategies while
penalizing drawdown.

Scoring model (per strategy)::

    score = (ev_capture * bayesian_confidence) / (1 + drawdown)

Weight normalization::

    weight_i = score_i / sum(score_all)

Position sizing::

    position_size_i = weight_i × max_position_limit

Constraints:

    - max_position_per_strategy ≤ 5% of bankroll (DEFAULT_MAX_PER_STRATEGY_PCT)
    - total allocation across all strategies ≤ 10% of bankroll
    - DEFAULT MODE = PAPER — real execution disabled unless MODE=LIVE and
      ENABLE_LIVE_TRADING=true

Auto-control rules:

    - win_rate < win_rate_threshold  → weight set to 0 (strategy suppressed)
    - drawdown > drawdown_threshold  → strategy disabled entirely

Usage::

    allocator = DynamicCapitalAllocator(
        strategy_names=["ev_momentum", "mean_reversion", "liquidity_edge"],
        bankroll=10_000.0,
    )

    # Update metrics each cycle:
    allocator.update_metrics(
        "ev_momentum",
        ev_capture=0.08,
        win_rate=0.72,
        bayesian_confidence=0.85,
        drawdown=0.02,
    )

    # Allocate on signal:
    decision = allocator.allocate("ev_momentum", raw_size_usd=80.0)

    # Telegram report:
    snapshot = allocator.allocation_snapshot()

Thread-safety: single asyncio event loop only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import structlog

from .allocator import AllocationDecision  # re-use for orchestrator compatibility

log = structlog.get_logger(__name__)

# ── Risk constants ────────────────────────────────────────────────────────────

DEFAULT_MAX_PER_STRATEGY_PCT: float = 0.05   # 5% bankroll cap per strategy
DEFAULT_MAX_TOTAL_EXPOSURE_PCT: float = 0.10  # 10% bankroll total exposure cap

# Auto-disable thresholds
DEFAULT_WIN_RATE_THRESHOLD: float = 0.40    # suppress if win_rate < 40%
DEFAULT_DRAWDOWN_THRESHOLD: float = 0.08    # disable if drawdown > 8%

# Prior metrics for strategies with no data yet (neutral bootstrap)
_PRIOR_EV: float = 0.05
_PRIOR_WIN_RATE: float = 0.50
_PRIOR_CONFIDENCE: float = 0.50
_PRIOR_DRAWDOWN: float = 0.0


# ── Data types ────────────────────────────────────────────────────────────────


@dataclass
class StrategyMetricSnapshot:
    """Current performance metrics for a single strategy.

    Attributes:
        ev_capture: Average expected value captured per trade.
        win_rate: Fraction of winning trades ∈ [0, 1].
        bayesian_confidence: Bayesian posterior confidence ∈ (0, 1).
        drawdown: Current drawdown fraction ∈ [0, 1].
    """

    ev_capture: float = _PRIOR_EV
    win_rate: float = _PRIOR_WIN_RATE
    bayesian_confidence: float = _PRIOR_CONFIDENCE
    drawdown: float = _PRIOR_DRAWDOWN

    def score(self) -> float:
        """Compute strategy score: (ev * confidence) / (1 + drawdown)."""
        numerator = self.ev_capture * self.bayesian_confidence
        denominator = 1.0 + self.drawdown
        return max(0.0, numerator / denominator)


@dataclass
class AllocationSnapshot:
    """Portfolio-level snapshot of all strategy allocations.

    Attributes:
        strategy_weights: Mapping of strategy_name → normalized weight.
        position_sizes: Mapping of strategy_name → position size in USD.
        disabled_strategies: Strategies that were auto-disabled this cycle.
        suppressed_strategies: Strategies suppressed (weight=0) due to low win_rate.
        total_allocated_usd: Sum of all active position sizes.
        bankroll: Bankroll used for computation.
    """

    strategy_weights: Dict[str, float] = field(default_factory=dict)
    position_sizes: Dict[str, float] = field(default_factory=dict)
    disabled_strategies: List[str] = field(default_factory=list)
    suppressed_strategies: List[str] = field(default_factory=list)
    total_allocated_usd: float = 0.0
    bankroll: float = 0.0


# ── DynamicCapitalAllocator ───────────────────────────────────────────────────


class DynamicCapitalAllocator:
    """Dynamic capital allocator with performance-based strategy weighting.

    Replaces :class:`~strategy.allocator.StrategyAllocator` with a richer
    model that uses EV capture, win-rate, Bayesian confidence, and drawdown
    to compute per-strategy position weights.  Hard limits from the Walker
    risk framework (5% per strategy, 10% total) are always enforced.

    DEFAULT MODE: PAPER.  Real execution requires separate gating at the
    execution layer (LiveModeController + ENABLE_LIVE_TRADING).

    Args:
        strategy_names: Names of all strategies to manage.
        bankroll: Total available capital in USD.
        max_per_strategy_pct: Maximum fraction of bankroll per strategy position.
        max_total_exposure_pct: Maximum fraction of bankroll in total exposure.
        win_rate_threshold: Win-rate below which a strategy's weight is zeroed.
        drawdown_threshold: Drawdown above which a strategy is auto-disabled.
    """

    def __init__(
        self,
        strategy_names: List[str],
        bankroll: float,
        max_per_strategy_pct: float = DEFAULT_MAX_PER_STRATEGY_PCT,
        max_total_exposure_pct: float = DEFAULT_MAX_TOTAL_EXPOSURE_PCT,
        win_rate_threshold: float = DEFAULT_WIN_RATE_THRESHOLD,
        drawdown_threshold: float = DEFAULT_DRAWDOWN_THRESHOLD,
    ) -> None:
        if bankroll <= 0:
            raise ValueError(f"bankroll must be positive, got {bankroll}")
        if not strategy_names:
            raise ValueError("strategy_names must not be empty")
        if not (0 < max_per_strategy_pct <= 1.0):
            raise ValueError(
                f"max_per_strategy_pct must be in (0, 1], got {max_per_strategy_pct}"
            )
        if not (0 < max_total_exposure_pct <= 1.0):
            raise ValueError(
                f"max_total_exposure_pct must be in (0, 1], got {max_total_exposure_pct}"
            )
        if max_per_strategy_pct > max_total_exposure_pct:
            raise ValueError(
                "max_per_strategy_pct must be <= max_total_exposure_pct"
            )

        self._bankroll = bankroll
        self._max_per_strategy_usd = bankroll * max_per_strategy_pct
        self._max_total_exposure_usd = bankroll * max_total_exposure_pct
        self._win_rate_threshold = win_rate_threshold
        self._drawdown_threshold = drawdown_threshold

        # Per-strategy metrics state
        self._metrics: Dict[str, StrategyMetricSnapshot] = {
            name: StrategyMetricSnapshot() for name in strategy_names
        }
        # Disabled strategies (drawdown > threshold)
        self._disabled: set[str] = set()

        log.info(
            "dynamic_capital_allocator_initialized",
            strategies=strategy_names,
            bankroll=bankroll,
            max_per_strategy_usd=self._max_per_strategy_usd,
            max_total_exposure_usd=self._max_total_exposure_usd,
            win_rate_threshold=win_rate_threshold,
            drawdown_threshold=drawdown_threshold,
        )

    # ── Metrics update ────────────────────────────────────────────────────────

    def update_metrics(
        self,
        strategy_name: str,
        ev_capture: float,
        win_rate: float,
        bayesian_confidence: float,
        drawdown: float,
    ) -> None:
        """Update performance metrics for a strategy and apply auto-control rules.

        Auto-control rules applied:
        - If drawdown > drawdown_threshold → disable the strategy.
        - If win_rate < win_rate_threshold → suppress (weight zeroed) but not
          disabled; the strategy may recover if win_rate improves.

        Args:
            strategy_name: Name of the strategy to update.
            ev_capture: Latest average EV captured per trade.
            win_rate: Latest observed win-rate fraction ∈ [0, 1].
            bayesian_confidence: Latest Bayesian posterior confidence ∈ (0, 1).
            drawdown: Latest drawdown fraction ∈ [0, 1].

        Raises:
            KeyError: If *strategy_name* is not registered.
        """
        if strategy_name not in self._metrics:
            raise KeyError(
                f"Strategy '{strategy_name}' not registered in DynamicCapitalAllocator"
            )

        self._metrics[strategy_name] = StrategyMetricSnapshot(
            ev_capture=max(0.0, ev_capture),
            win_rate=max(0.0, min(1.0, win_rate)),
            bayesian_confidence=max(0.0, min(1.0, bayesian_confidence)),
            drawdown=max(0.0, drawdown),
        )

        # Auto-disable on excessive drawdown
        if drawdown > self._drawdown_threshold:
            if strategy_name not in self._disabled:
                self._disabled.add(strategy_name)
                log.warning(
                    "dynamic_capital_allocator.strategy_auto_disabled",
                    strategy=strategy_name,
                    drawdown=round(drawdown, 4),
                    threshold=self._drawdown_threshold,
                )
        else:
            # Re-enable if drawdown recovers
            if strategy_name in self._disabled:
                self._disabled.discard(strategy_name)
                log.info(
                    "dynamic_capital_allocator.strategy_re_enabled",
                    strategy=strategy_name,
                    drawdown=round(drawdown, 4),
                )

        log.debug(
            "dynamic_capital_allocator.metrics_updated",
            strategy=strategy_name,
            ev_capture=round(ev_capture, 4),
            win_rate=round(win_rate, 4),
            confidence=round(bayesian_confidence, 4),
            drawdown=round(drawdown, 4),
        )

    # ── Allocation ────────────────────────────────────────────────────────────

    def allocate(
        self,
        strategy_name: str,
        raw_size_usd: float,
        current_exposure_usd: float = 0.0,
    ) -> AllocationDecision:
        """Compute weight-based position size for a strategy signal.

        The position size is determined by the strategy's normalized score
        weight multiplied by the per-strategy cap.  The returned
        ``adjusted_size_usd`` is the minimum of the weight-based size and the
        signal's ``raw_size_usd`` request — the signal cannot exceed its own
        suggestion, and the allocator's weight cap further constrains it.

        Risk gates (all enforced, first violation returns rejected=True):
        1. Strategy is auto-disabled (drawdown exceeded threshold).
        2. Total exposure headroom exhausted.
        3. Weight is zero (win_rate below threshold).

        Args:
            strategy_name: Name of the requesting strategy.
            raw_size_usd: Signal's requested position size in USDC.
            current_exposure_usd: Current total open exposure across all
                strategies.

        Returns:
            :class:`AllocationDecision` with the final approved (or rejected) size.
        """
        # ── Gate 1: disabled ──────────────────────────────────────────────────
        if strategy_name in self._disabled:
            log.warning(
                "dynamic_capital_allocator.allocation_blocked_disabled",
                strategy=strategy_name,
            )
            return AllocationDecision(
                strategy_name=strategy_name,
                raw_size_usd=raw_size_usd,
                confidence=0.0,
                adjusted_size_usd=0.0,
                rejected=True,
                rejection_reason=f"strategy_disabled: drawdown > {self._drawdown_threshold}",
            )

        # ── Gate 2: total exposure ────────────────────────────────────────────
        remaining_exposure = self._max_total_exposure_usd - current_exposure_usd
        if remaining_exposure <= 0:
            return AllocationDecision(
                strategy_name=strategy_name,
                raw_size_usd=raw_size_usd,
                confidence=0.0,
                adjusted_size_usd=0.0,
                rejected=True,
                rejection_reason=(
                    f"total_exposure_cap_reached: "
                    f"current={current_exposure_usd:.2f} >= "
                    f"max={self._max_total_exposure_usd:.2f}"
                ),
            )

        # ── Compute weights for all active strategies ─────────────────────────
        weights = self._compute_weights()
        weight = weights.get(strategy_name, 0.0)

        # ── Gate 3: suppressed (win_rate < threshold, not disabled) ──────────
        metrics = self._metrics.get(strategy_name)
        if metrics is not None and metrics.win_rate < self._win_rate_threshold:
            log.warning(
                "dynamic_capital_allocator.allocation_blocked_suppressed",
                strategy=strategy_name,
                win_rate=round(metrics.win_rate, 4),
                threshold=self._win_rate_threshold,
            )
            return AllocationDecision(
                strategy_name=strategy_name,
                raw_size_usd=raw_size_usd,
                confidence=0.0,
                adjusted_size_usd=0.0,
                rejected=True,
                rejection_reason=(
                    f"win_rate_below_threshold: "
                    f"{metrics.win_rate:.4f} < {self._win_rate_threshold}"
                ),
            )

        if weight <= 0.0:
            return AllocationDecision(
                strategy_name=strategy_name,
                raw_size_usd=raw_size_usd,
                confidence=0.0,
                adjusted_size_usd=0.0,
                rejected=True,
                rejection_reason="zero_weight: no eligible strategies have positive score",
            )

        # ── Compute position size from weight ─────────────────────────────────
        # position_size = weight × max_per_strategy_usd
        weight_based_size = weight * self._max_per_strategy_usd

        # Clamp to remaining exposure headroom
        clamped_size = min(weight_based_size, remaining_exposure)

        # Final size: minimum of weight-based cap and signal's own request
        adjusted = round(min(clamped_size, raw_size_usd), 2)

        log.debug(
            "dynamic_capital_allocator.allocated",
            strategy=strategy_name,
            weight=round(weight, 4),
            weight_based_size=round(weight_based_size, 2),
            raw_size_usd=round(raw_size_usd, 2),
            adjusted_size_usd=adjusted,
        )

        return AllocationDecision(
            strategy_name=strategy_name,
            raw_size_usd=raw_size_usd,
            confidence=round(weight, 4),
            adjusted_size_usd=adjusted,
        )

    # ── Outcome recording (Bayesian feedback loop) ────────────────────────────

    def record_outcome(self, strategy_name: str, won: bool) -> None:
        """Record a trade outcome for a strategy.

        The caller is responsible for updating the Bayesian confidence metric
        via :meth:`update_metrics`.  This method exists as a hook for future
        online learning integration.

        Args:
            strategy_name: Name of the strategy whose trade settled.
            won: True if the trade was profitable.

        Raises:
            KeyError: If *strategy_name* is not registered.
        """
        if strategy_name not in self._metrics:
            raise KeyError(
                f"Strategy '{strategy_name}' not registered in DynamicCapitalAllocator"
            )
        log.info(
            "dynamic_capital_allocator.outcome_recorded",
            strategy=strategy_name,
            won=won,
        )

    # ── Snapshot / reporting ──────────────────────────────────────────────────

    def allocation_snapshot(self) -> AllocationSnapshot:
        """Compute a full portfolio-level allocation snapshot.

        Returns:
            :class:`AllocationSnapshot` with current weights, sizes, and
            disabled/suppressed strategy lists.
        """
        weights = self._compute_weights()
        position_sizes: Dict[str, float] = {}
        suppressed: List[str] = []

        for name in self._metrics:
            if name in self._disabled:
                position_sizes[name] = 0.0
                continue
            m = self._metrics[name]
            if m.win_rate < self._win_rate_threshold:
                suppressed.append(name)
                position_sizes[name] = 0.0
                continue
            w = weights.get(name, 0.0)
            position_sizes[name] = round(w * self._max_per_strategy_usd, 2)

        total_allocated = sum(position_sizes.values())

        snapshot = AllocationSnapshot(
            strategy_weights={k: round(v, 4) for k, v in weights.items()},
            position_sizes=position_sizes,
            disabled_strategies=list(self._disabled),
            suppressed_strategies=suppressed,
            total_allocated_usd=round(total_allocated, 2),
            bankroll=self._bankroll,
        )

        log.info(
            "dynamic_capital_allocator.snapshot",
            weights=snapshot.strategy_weights,
            total_allocated_usd=snapshot.total_allocated_usd,
            disabled=snapshot.disabled_strategies,
            suppressed=snapshot.suppressed_strategies,
        )

        return snapshot

    def get_weight(self, strategy_name: str) -> float:
        """Return the current normalized weight for a strategy.

        Args:
            strategy_name: Strategy name.

        Returns:
            Weight ∈ [0, 1].  Returns 0.0 for disabled or unknown strategies.
        """
        if strategy_name in self._disabled:
            return 0.0
        weights = self._compute_weights()
        return weights.get(strategy_name, 0.0)

    def is_disabled(self, strategy_name: str) -> bool:
        """Return True if the strategy is currently auto-disabled.

        Args:
            strategy_name: Strategy name.

        Returns:
            True if disabled, False otherwise.
        """
        return strategy_name in self._disabled

    def enable_strategy(self, strategy_name: str) -> None:
        """Manually re-enable a strategy that was auto-disabled.

        Args:
            strategy_name: Strategy name to re-enable.

        Raises:
            KeyError: If *strategy_name* is not registered.
        """
        if strategy_name not in self._metrics:
            raise KeyError(
                f"Strategy '{strategy_name}' not registered in DynamicCapitalAllocator"
            )
        self._disabled.discard(strategy_name)
        log.info(
            "dynamic_capital_allocator.strategy_manually_re_enabled",
            strategy=strategy_name,
        )

    def disable_strategy(self, strategy_name: str) -> None:
        """Manually disable a strategy (e.g. kill switch).

        Args:
            strategy_name: Strategy name to disable.

        Raises:
            KeyError: If *strategy_name* is not registered.
        """
        if strategy_name not in self._metrics:
            raise KeyError(
                f"Strategy '{strategy_name}' not registered in DynamicCapitalAllocator"
            )
        self._disabled.add(strategy_name)
        log.warning(
            "dynamic_capital_allocator.strategy_manually_disabled",
            strategy=strategy_name,
        )

    @property
    def bankroll(self) -> float:
        """Current bankroll in USD."""
        return self._bankroll

    @property
    def strategy_names(self) -> List[str]:
        """All registered strategy names."""
        return list(self._metrics.keys())

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _compute_weights(self) -> Dict[str, float]:
        """Compute normalized score weights for all eligible strategies.

        Disabled strategies and strategies with win_rate below threshold
        receive weight = 0.  The remaining weights sum to 1.0 (or all zeros
        if every strategy is ineligible).

        Returns:
            Mapping of strategy_name → normalized weight ∈ [0, 1].
        """
        raw_scores: Dict[str, float] = {}

        for name, metrics in self._metrics.items():
            if name in self._disabled:
                raw_scores[name] = 0.0
                continue
            if metrics.win_rate < self._win_rate_threshold:
                raw_scores[name] = 0.0
                continue
            raw_scores[name] = metrics.score()

        total_score = sum(raw_scores.values())

        if total_score <= 0.0:
            # All strategies ineligible — return zero weights
            return {name: 0.0 for name in self._metrics}

        return {name: s / total_score for name, s in raw_scores.items()}
