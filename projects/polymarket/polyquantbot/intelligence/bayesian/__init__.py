"""Bayesian confidence updater for PolyQuantBot intelligence layer.

Uses a Beta distribution to model and update the win-rate confidence of a strategy.
Each fill outcome (win/loss) updates the Beta prior, and the resulting posterior
mean is returned as the confidence multiplier for the signal edge.

Usage::

    from projects.polymarket.polyquantbot.intelligence.bayesian import BayesianConfidence

    bc = BayesianConfidence(alpha_prior=2.0, beta_prior=2.0)

    # After a winning trade:
    bc.update(won=True)

    # After a losing trade:
    bc.update(won=False)

    # Get confidence (posterior mean of Beta distribution):
    confidence = bc.confidence   # 0.0–1.0
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

import structlog

log = structlog.get_logger(__name__)


@dataclass
class BayesianState:
    """Snapshot of the Bayesian Beta posterior state."""

    alpha: float
    beta: float
    confidence: float       # posterior mean: alpha / (alpha + beta)
    sample_count: int
    win_count: int


class BayesianConfidence:
    """Beta-distribution Bayesian win-rate confidence estimator.

    Maintains a Beta(α, β) posterior updated with trade outcomes.
    The posterior mean ``α / (α + β)`` serves as a confidence multiplier
    applied to the raw strategy edge before risk sizing.

    Args:
        alpha_prior: Initial α (pseudo-wins). Must be > 0.
        beta_prior:  Initial β (pseudo-losses). Must be > 0.
        min_samples: Minimum trade outcomes before confidence departs from prior.
    """

    def __init__(
        self,
        alpha_prior: float = 2.0,
        beta_prior: float = 2.0,
        min_samples: int = 5,
    ) -> None:
        if alpha_prior <= 0 or beta_prior <= 0:
            raise ValueError("alpha_prior and beta_prior must be > 0")
        self._alpha_prior = float(alpha_prior)
        self._beta_prior = float(beta_prior)
        self._alpha = float(alpha_prior)
        self._beta = float(beta_prior)
        self._min_samples = min_samples
        self._sample_count: int = 0
        self._win_count: int = 0
        self._lock = asyncio.Lock()

    # ── Properties ─────────────────────────────────────────────────────────────

    @property
    def confidence(self) -> float:
        """Posterior mean of the Beta distribution (win probability estimate).

        Returns the prior mean if fewer than ``min_samples`` observations recorded.
        """
        if self._sample_count < self._min_samples:
            return self._alpha_prior / (self._alpha_prior + self._beta_prior)
        return self._alpha / (self._alpha + self._beta)

    @property
    def sample_count(self) -> int:
        """Total number of trade outcomes observed."""
        return self._sample_count

    # ── Core methods ───────────────────────────────────────────────────────────

    async def update(self, won: bool) -> float:
        """Update the posterior with a new trade outcome.

        Args:
            won: True if the trade was profitable, False otherwise.

        Returns:
            Updated confidence value (posterior mean).
        """
        async with self._lock:
            if won:
                self._alpha += 1.0
                self._win_count += 1
            else:
                self._beta += 1.0
            self._sample_count += 1

            conf = self.confidence
            log.debug(
                "bayesian.update",
                won=won,
                alpha=round(self._alpha, 2),
                beta=round(self._beta, 2),
                confidence=round(conf, 4),
                sample_count=self._sample_count,
            )
            return conf

    def snapshot(self) -> BayesianState:
        """Return the current posterior state as a snapshot.

        Returns:
            BayesianState with current α, β, confidence, and counters.
        """
        return BayesianState(
            alpha=round(self._alpha, 4),
            beta=round(self._beta, 4),
            confidence=round(self.confidence, 4),
            sample_count=self._sample_count,
            win_count=self._win_count,
        )

    def reset(self) -> None:
        """Reset to prior (discard all observed outcomes)."""
        self._alpha = self._alpha_prior
        self._beta = self._beta_prior
        self._sample_count = 0
        self._win_count = 0
        log.info("bayesian.reset", alpha_prior=self._alpha_prior, beta_prior=self._beta_prior)

    def to_dict(self) -> dict:
        """Serialise state for logging or persistence."""
        return {
            "alpha": round(self._alpha, 4),
            "beta": round(self._beta, 4),
            "confidence": round(self.confidence, 4),
            "sample_count": self._sample_count,
            "win_count": self._win_count,
            "alpha_prior": self._alpha_prior,
            "beta_prior": self._beta_prior,
        }
