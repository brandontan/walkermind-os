"""Bayesian correlation engine — Phase 6.

Uses normalized log-odds (NOT naive multiplication) to update signal
probability when correlated markets are present, preventing probability
vanishing to zero.

Update rule:
    lo_prior     = log(p_model / (1 − p_model))
    for each correlated market j with coefficient corr_ij:
        adjustment_j = corr_ij × (lo_j − lo_prior)
        adjustment_j = clamp(adjustment_j, −max_adj, +max_adj)
    lo_posterior = lo_prior + Σ adjustments / (1 + n_correlations)
    p_posterior  = sigmoid(lo_posterior)

Division by (1 + n) normalizes accumulated adjustments and prevents
overconfidence when many correlated signals are present.

After adjustment, signal.ev is recomputed and "correlation_applied" is logged.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

import structlog

from ..core.signal_model import SignalResult, calculate_ev

log = structlog.get_logger()

# Numerical safety clamps
_MIN_P: float = 1e-6
_MAX_P: float = 1.0 - 1e-6


def _clamp_p(p: float) -> float:
    """Clamp probability to open interval (0, 1) to prevent log(0)."""
    return max(_MIN_P, min(_MAX_P, p))


def _log_odds(p: float) -> float:
    """Convert probability to log-odds. Input is pre-clamped."""
    p = _clamp_p(p)
    return math.log(p / (1.0 - p))


def _sigmoid(lo: float) -> float:
    """Numerically stable sigmoid (log-odds → probability).

    Uses split form to prevent overflow on large |lo|.
    """
    if lo >= 0:
        return 1.0 / (1.0 + math.exp(-lo))
    exp_lo = math.exp(lo)
    return exp_lo / (1.0 + exp_lo)


@dataclass
class CorrelationResult:
    """Diagnostic output of one correlation adjustment."""

    original_p_model: float
    adjusted_p_model: float
    original_ev: float
    adjusted_ev: float
    correlation_applied: bool
    n_correlations: int
    correlation_id: str


class CorrelationEngine:
    """Adjusts signal probabilities using Bayesian log-odds updates.

    The engine is stateless per call: it receives all signals from a single
    market-data cycle plus a correlation matrix, updates each signal's p_model
    independently, and returns adjusted signals.
    """

    def __init__(self, max_corr_adjustment: float = 0.3) -> None:
        """Initialise with maximum per-correlation log-odds shift.

        Args:
            max_corr_adjustment: Hard clamp (absolute) on each adjustment term.
                Prevents a single high-correlation pair from dominating.
        """
        self._max_corr_adj = max_corr_adjustment

    async def adjust_signal(
        self,
        signal: SignalResult,
        correlated_signals: list[SignalResult],
        correlation_matrix: dict[tuple[str, str], float],
        correlation_id: str,
    ) -> tuple[SignalResult, CorrelationResult]:
        """Apply Bayesian log-odds update to a single signal.

        Steps:
            1. Convert signal.p_model to log-odds (lo_prior).
            2. For each other signal j where corr_ij exists in matrix:
               raw_adj  = corr_ij × (lo_j − lo_prior)
               clamped  = clamp(raw_adj, −max_adj, +max_adj)
            3. lo_posterior = lo_prior + Σ clamped / (1 + n_corr)
            4. p_posterior  = sigmoid(lo_posterior)   (clamped to avoid extremes)
            5. Recompute EV with adjusted probability.
            6. Log "correlation_applied" with before/after values.

        If no correlations exist for this signal, return it unchanged.

        Args:
            signal: Primary signal to adjust.
            correlated_signals: All other signals from the same cycle.
            correlation_matrix: (market_id_a, market_id_b) → coefficient [-1, 1].
            correlation_id: Request ID propagated through all log lines.

        Returns:
            (adjusted_signal, CorrelationResult)
        """
        lo_prior = _log_odds(signal.p_model)
        lo_adjustment_sum: float = 0.0
        n_corr: int = 0

        for other in correlated_signals:
            if other.market_id == signal.market_id:
                continue

            # Look up coefficient in both key orderings
            key_ab = (signal.market_id, other.market_id)
            key_ba = (other.market_id, signal.market_id)
            coeff = correlation_matrix.get(key_ab) or correlation_matrix.get(key_ba)
            if coeff is None:
                continue

            lo_j = _log_odds(other.p_model)
            raw_adj = coeff * (lo_j - lo_prior)
            clamped_adj = max(-self._max_corr_adj, min(self._max_corr_adj, raw_adj))
            lo_adjustment_sum += clamped_adj
            n_corr += 1

        # No correlations → return unchanged
        if n_corr == 0:
            return signal, CorrelationResult(
                original_p_model=signal.p_model,
                adjusted_p_model=signal.p_model,
                original_ev=signal.ev,
                adjusted_ev=signal.ev,
                correlation_applied=False,
                n_correlations=0,
                correlation_id=correlation_id,
            )

        # Normalize: divide by (1 + n) to prevent overconfidence
        lo_posterior = lo_prior + lo_adjustment_sum / (1.0 + n_corr)
        p_posterior = _clamp_p(_sigmoid(lo_posterior))
        new_ev = calculate_ev(p_posterior, signal.p_market)

        adjusted_signal = replace(signal, p_model=p_posterior, ev=new_ev)

        log.info(
            "correlation_applied",
            correlation_id=correlation_id,
            market_id=signal.market_id,
            strategy=signal.strategy,
            original_p=round(signal.p_model, 6),
            adjusted_p=round(p_posterior, 6),
            original_ev=round(signal.ev, 6),
            adjusted_ev=round(new_ev, 6),
            n_correlations=n_corr,
            lo_prior=round(lo_prior, 4),
            lo_posterior=round(lo_posterior, 4),
            lo_adjustment=round(lo_adjustment_sum, 4),
        )

        return adjusted_signal, CorrelationResult(
            original_p_model=signal.p_model,
            adjusted_p_model=round(p_posterior, 6),
            original_ev=signal.ev,
            adjusted_ev=round(new_ev, 6),
            correlation_applied=True,
            n_correlations=n_corr,
            correlation_id=correlation_id,
        )

    async def adjust_all(
        self,
        signals: list[SignalResult],
        correlation_matrix: dict[tuple[str, str], float],
        correlation_id: str,
    ) -> list[SignalResult]:
        """Adjust all signals in a cycle concurrently.

        Each signal is adjusted against all others from the same cycle.
        Uses asyncio.gather for concurrency.

        Args:
            signals: All signals from one MARKET_DATA event cycle.
            correlation_matrix: Pairwise correlation coefficients.
            correlation_id: Shared request ID.

        Returns:
            List of adjusted signals (same length and order as input).
        """
        import asyncio

        tasks = [
            self.adjust_signal(
                signal=sig,
                correlated_signals=signals,
                correlation_matrix=correlation_matrix,
                correlation_id=correlation_id,
            )
            for sig in signals
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        adjusted: list[SignalResult] = []
        for i, res in enumerate(results):
            if isinstance(res, Exception):
                log.warning(
                    "correlation_adjust_error",
                    correlation_id=correlation_id,
                    market_id=signals[i].market_id,
                    error=str(res),
                )
                adjusted.append(signals[i])  # fall back to original
            else:
                adjusted.append(res[0])

        return adjusted
