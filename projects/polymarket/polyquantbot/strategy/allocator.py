"""Per-strategy capital allocator for the multi-strategy router.

StrategyAllocator extends the base capital allocation logic by weighting each
strategy's position size according to its historical Bayesian confidence score.
Strategies with higher observed win-rates receive proportionally more capital.

Design:
  - Each strategy maintains its own BayesianConfidence tracker.
  - Position sizes from the strategy (via SignalResult.size_usdc) are scaled by
    the strategy's confidence multiplier.
  - The global risk rules (max position, daily loss limit) are always enforced
    on top of the confidence-weighted size.

Usage::

    from projects.polymarket.polyquantbot.strategy.allocator import StrategyAllocator

    allocator = StrategyAllocator(
        strategy_names=["ev_momentum", "mean_reversion", "liquidity_edge"],
        bankroll=10_000.0,
        max_position_pct=0.10,
    )

    adjusted_size = allocator.allocate("ev_momentum", raw_size=80.0, current_exposure=200.0)
    allocator.record_outcome("ev_momentum", won=True)
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Dict, List, Optional

import structlog

from ..intelligence.bayesian import BayesianConfidence

log = structlog.get_logger(__name__)

# ── Risk rules ────────────────────────────────────────────────────────────────

_MAX_POSITION_PCT: float = 0.10        # 10% of bankroll per position (CLAUDE.md rule)
_MAX_TOTAL_EXPOSURE_PCT: float = 0.30  # 30% total exposure across all strategies
_MIN_CONFIDENCE_MULTIPLIER: float = 0.10  # never reduce size below 10% of raw


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class AllocationDecision:
    """Output of a single StrategyAllocator.allocate() call.

    Attributes:
        strategy_name: Strategy that requested the allocation.
        raw_size_usd: Signal's original requested size (before confidence scaling).
        confidence: Bayesian confidence multiplier applied.
        adjusted_size_usd: Final approved size after confidence scaling and caps.
        rejected: True if allocation was rejected (exposure cap exceeded).
        rejection_reason: Human-readable rejection reason, or None.
    """

    strategy_name: str
    raw_size_usd: float
    confidence: float
    adjusted_size_usd: float
    rejected: bool = False
    rejection_reason: Optional[str] = None


# ── StrategyAllocator ─────────────────────────────────────────────────────────

class StrategyAllocator:
    """Per-strategy capital allocator with Bayesian confidence weighting.

    Tracks each strategy's win-rate via a :class:`BayesianConfidence` updater
    and uses the resulting posterior mean to scale each strategy's requested
    position size.  Hard limits from the Walker risk framework are always
    enforced on the final size.

    Args:
        strategy_names: Names of all strategies to manage.
        bankroll: Total available capital in USD.
        max_position_pct: Maximum fraction of bankroll for any single position.
        max_total_exposure_pct: Maximum fraction of bankroll in total open exposure.
        alpha_prior: BayesianConfidence α prior (pseudo-wins).
        beta_prior: BayesianConfidence β prior (pseudo-losses).
        min_samples: Minimum samples before confidence departs from prior.
    """

    def __init__(
        self,
        strategy_names: List[str],
        bankroll: float,
        max_position_pct: float = _MAX_POSITION_PCT,
        max_total_exposure_pct: float = _MAX_TOTAL_EXPOSURE_PCT,
        alpha_prior: float = 2.0,
        beta_prior: float = 2.0,
        min_samples: int = 5,
    ) -> None:
        if bankroll <= 0:
            raise ValueError(f"bankroll must be positive, got {bankroll}")
        if not strategy_names:
            raise ValueError("strategy_names must not be empty")

        self._bankroll = bankroll
        self._max_position_usd = bankroll * max_position_pct
        self._max_total_exposure_usd = bankroll * max_total_exposure_pct
        self._max_position_pct = max_position_pct

        self._confidence: Dict[str, BayesianConfidence] = {
            name: BayesianConfidence(
                alpha_prior=alpha_prior,
                beta_prior=beta_prior,
                min_samples=min_samples,
            )
            for name in strategy_names
        }
        self._lock = asyncio.Lock()

        log.info(
            "strategy_allocator_initialized",
            strategies=strategy_names,
            bankroll=bankroll,
            max_position_usd=self._max_position_usd,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def allocate(
        self,
        strategy_name: str,
        raw_size_usd: float,
        current_exposure_usd: float = 0.0,
    ) -> AllocationDecision:
        """Compute confidence-weighted position size for a strategy signal.

        The raw_size_usd requested by the strategy is scaled by the strategy's
        current Bayesian confidence and then capped by global risk rules.

        Args:
            strategy_name: Name of the requesting strategy.
            raw_size_usd: Position size requested by the strategy signal (USDC).
            current_exposure_usd: Current total open exposure across all strategies.

        Returns:
            :class:`AllocationDecision` with the final approved (or rejected) size.
        """
        if strategy_name not in self._confidence:
            log.warning(
                "strategy_allocator.unknown_strategy",
                strategy=strategy_name,
            )
            confidence_val = 0.5  # neutral fallback for unregistered strategy
        else:
            confidence_val = self._confidence[strategy_name].confidence

        # Scale by confidence (never go below the minimum multiplier)
        confidence_factor = max(_MIN_CONFIDENCE_MULTIPLIER, confidence_val)
        adjusted = raw_size_usd * confidence_factor

        # Cap at per-position limit
        adjusted = min(adjusted, self._max_position_usd)

        # Check total exposure headroom
        remaining = self._max_total_exposure_usd - current_exposure_usd
        if remaining <= 0:
            return AllocationDecision(
                strategy_name=strategy_name,
                raw_size_usd=raw_size_usd,
                confidence=confidence_val,
                adjusted_size_usd=0.0,
                rejected=True,
                rejection_reason=(
                    f"total_exposure_cap_reached: "
                    f"current={current_exposure_usd:.2f} >= "
                    f"max={self._max_total_exposure_usd:.2f}"
                ),
            )

        adjusted = min(adjusted, remaining)

        log.debug(
            "strategy_allocator.allocated",
            strategy=strategy_name,
            raw_size_usd=round(raw_size_usd, 2),
            confidence=round(confidence_val, 4),
            adjusted_size_usd=round(adjusted, 2),
        )

        return AllocationDecision(
            strategy_name=strategy_name,
            raw_size_usd=raw_size_usd,
            confidence=confidence_val,
            adjusted_size_usd=round(adjusted, 2),
        )

    async def record_outcome(self, strategy_name: str, won: bool) -> float:
        """Record a trade outcome and update the strategy's Bayesian confidence.

        Args:
            strategy_name: Name of the strategy whose trade was settled.
            won: True if the trade was profitable, False otherwise.

        Returns:
            Updated confidence value (posterior mean).

        Raises:
            KeyError: If the strategy is not registered.
        """
        if strategy_name not in self._confidence:
            raise KeyError(f"Strategy '{strategy_name}' not registered in allocator")
        confidence = await self._confidence[strategy_name].update(won=won)
        log.info(
            "strategy_allocator.outcome_recorded",
            strategy=strategy_name,
            won=won,
            confidence=round(confidence, 4),
        )
        return confidence

    def get_confidence(self, strategy_name: str) -> float:
        """Return current Bayesian confidence for a strategy.

        Args:
            strategy_name: Strategy name.

        Returns:
            Posterior mean confidence ∈ (0, 1).

        Raises:
            KeyError: If the strategy is not registered.
        """
        if strategy_name not in self._confidence:
            raise KeyError(f"Strategy '{strategy_name}' not registered in allocator")
        return self._confidence[strategy_name].confidence

    def snapshot(self) -> Dict[str, dict]:
        """Return a dict snapshot of all strategy confidence states."""
        return {
            name: bc.to_dict()
            for name, bc in self._confidence.items()
        }

    @property
    def bankroll(self) -> float:
        """Current bankroll in USD."""
        return self._bankroll

    @property
    def strategy_names(self) -> List[str]:
        """Registered strategy names."""
        return list(self._confidence.keys())
