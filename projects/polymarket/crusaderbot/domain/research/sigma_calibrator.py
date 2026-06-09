"""Adaptive online sigma calibration (WARP-70) — SHADOW-FIRST, no capital path.

Per-``(asset, timeframe)`` EWMA of realized variance-per-second, derived from the
full candle-observation stream (settled ``factor_vectors`` rows — EVERY candle,
traded or not), NOT the positions table. Keeping the training source decoupled
from the trade/gate decision is the non-negotiable design constraint: a learner
fed only the bot's own executed candles is selection-biased (gate tightens ->
sample skews -> sigma drifts -> self-poisoning spiral). factor_vectors records a
row per observed candle independent of execution, so it is the clean source.

The oracle fair-value model (``oracle/fair_value.py``) prices candles with a PER
ASSET ``sigma`` per sqrt-second: ``fair_up = Phi(delta / (sigma * sqrt(t_left)))``.
A static sigma goes stale as realized vol shifts regime. This calibrator tracks
realized vol online so a later lane can swap static -> adaptive with ZERO
gate-logic change (only the sigma source changes). It does NOT gate today — it
observes, bounds, smooths, and exposes an adaptive-vs-static comparison for
validation.

Estimator
---------
A candle's open->close return ``r`` over ``T`` seconds is, under a zero-drift
diffusion, ``Var(r) = sigma^2 * T`` so ``r^2 / T`` is a one-candle unbiased
estimate of the per-second variance ``sigma^2``. The calibrator EWMA-smooths
those per-second variance samples; ``sigma_adaptive = sqrt(EWMA)``.

Safety invariants (baked in, not optional)
------------------------------------------
* **Bounded** — adaptive sigma is clamped to ``[LOW * prior, HIGH * prior]`` per
  asset, so no single regime/outlier can swing it to an extreme.
* **Smoothed** — EWMA with a slow ``alpha``; one candle cannot jump it.
* **Cold-start** — until ``>= min_samples`` per cell, ``sigma()`` returns the
  static per-asset prior (advisory until converged).
* **Observable** — every ``observe()`` returns the driving sample + before/after
  sigma + sample count so any later gate decision is auditable.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..strategy.oracle.fair_value import DEFAULT_SIGMA_PER_SQRT_SEC

# Adaptive sigma may only live within this multiplicative band around the static
# per-asset prior. A wide-but-finite band: regime vol genuinely moves several-fold,
# but a single corrupt candle still cannot push the gate to a nonsense sigma.
_SIGMA_BAND_LOW: float = 0.33
_SIGMA_BAND_HIGH: float = 3.0

# Default EWMA smoothing factor and convergence threshold. alpha small = slow
# (a single candle moves the estimate by ~alpha of the gap). min_samples is the
# cold-start gate: below it the static prior is authoritative.
_DEFAULT_ALPHA: float = 0.05
_DEFAULT_MIN_SAMPLES: int = 30


def prior_sigma_for_asset(asset: str) -> float:
    """Static per-asset prior (per sqrt-second), case-insensitive.

    Falls back to the BTC prior for an unknown symbol rather than raising — the
    calibrator is shadow/advisory, so an unknown asset must degrade gracefully to
    a sane prior, never crash the observation stream.
    """
    key = (asset or "").strip().lower()
    return float(DEFAULT_SIGMA_PER_SQRT_SEC.get(key, DEFAULT_SIGMA_PER_SQRT_SEC["btc"]))


def variance_per_second(realized_delta: float, duration_sec: float) -> float | None:
    """One-candle per-second variance estimate ``r^2 / T``.

    Returns ``None`` for a non-finite / non-positive duration or a non-finite
    return — a degenerate candle is skipped, never folded into the EWMA as 0/NaN.
    """
    if not math.isfinite(realized_delta):
        return None
    if not math.isfinite(duration_sec) or duration_sec <= 0.0:
        return None
    return (realized_delta * realized_delta) / duration_sec


def gaussian_nll(realized_delta: float, duration_sec: float, sigma: float) -> float | None:
    """Per-candle Gaussian negative log-likelihood of ``realized_delta`` under
    ``N(0, (sigma*sqrt(T))^2)`` — the calibration metric.

    Lower NLL = the sigma better explains the realized return spread. Comparing
    avg NLL of the static prior vs the adaptive sigma over the candle stream is
    the shadow acceptance test (adaptive should be <= static once converged).
    Returns ``None`` for a degenerate input (so it is skipped, not counted).
    """
    if not math.isfinite(realized_delta):
        return None
    if not math.isfinite(duration_sec) or duration_sec <= 0.0:
        return None
    if not math.isfinite(sigma) or sigma <= 0.0:
        return None
    variance = sigma * sigma * duration_sec
    if variance <= 0.0:
        return None
    return 0.5 * (math.log(2.0 * math.pi * variance) + (realized_delta * realized_delta) / variance)


@dataclass
class SigmaUpdate:
    """Observable record of a single ``observe()`` — the audit trail."""

    asset: str
    timeframe: str
    sample_variance_per_sec: float
    sample_sigma: float
    sigma_before: float
    sigma_after: float
    n_samples: int
    using_prior: bool


@dataclass
class _CellState:
    ewma_variance: float = 0.0
    n: int = 0


@dataclass
class SigmaCalibrator:
    """Online per-``(asset, timeframe)`` adaptive sigma estimator (shadow-only).

    Stateless w.r.t. I/O — feed it observed candles via :meth:`observe`; read the
    current (cold-start-aware, bounded) value via :meth:`sigma`. Holds no DB / no
    network; a caller (the shadow runner) supplies the candle stream.
    """

    alpha: float = _DEFAULT_ALPHA
    min_samples: int = _DEFAULT_MIN_SAMPLES
    band_low: float = _SIGMA_BAND_LOW
    band_high: float = _SIGMA_BAND_HIGH
    _cells: dict[tuple[str, str], _CellState] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not (0.0 < self.alpha <= 1.0):
            raise ValueError(f"alpha must be in (0, 1], got {self.alpha!r}")
        if self.min_samples < 1:
            raise ValueError(f"min_samples must be >= 1, got {self.min_samples!r}")
        if not (0.0 < self.band_low < 1.0 < self.band_high):
            raise ValueError(
                f"require 0 < band_low < 1 < band_high, got "
                f"{self.band_low!r}/{self.band_high!r}"
            )

    @staticmethod
    def _key(asset: str, timeframe: str) -> tuple[str, str]:
        return ((asset or "").strip().lower(), (timeframe or "").strip().lower())

    def _clamp(self, asset: str, sigma: float) -> float:
        prior = prior_sigma_for_asset(asset)
        return max(prior * self.band_low, min(sigma, prior * self.band_high))

    def sigma(self, asset: str, timeframe: str) -> float:
        """Current sigma for the cell: the static prior until the cell has
        converged (``n >= min_samples``), then the bounded EWMA estimate."""
        st = self._cells.get(self._key(asset, timeframe))
        prior = prior_sigma_for_asset(asset)
        if st is None or st.n < self.min_samples or st.ewma_variance <= 0.0:
            return prior
        return self._clamp(asset, math.sqrt(st.ewma_variance))

    def observe(
        self, asset: str, timeframe: str, realized_delta: float, duration_sec: float
    ) -> SigmaUpdate | None:
        """Fold one settled candle's realized return into the cell's EWMA.

        Returns the :class:`SigmaUpdate` audit record, or ``None`` when the candle
        is degenerate (non-finite / non-positive duration) and skipped.
        """
        sample = variance_per_second(realized_delta, duration_sec)
        if sample is None:
            return None

        key = self._key(asset, timeframe)
        st = self._cells.get(key)
        if st is None:
            st = _CellState()
            self._cells[key] = st

        sigma_before = self.sigma(asset, timeframe)
        # Seed the EWMA on the first sample so it starts at the observed variance
        # rather than crawling up from zero.
        st.ewma_variance = (
            sample if st.n == 0
            else self.alpha * sample + (1.0 - self.alpha) * st.ewma_variance
        )
        st.n += 1
        sigma_after = self.sigma(asset, timeframe)

        return SigmaUpdate(
            asset=key[0],
            timeframe=key[1],
            sample_variance_per_sec=sample,
            sample_sigma=math.sqrt(sample),
            sigma_before=sigma_before,
            sigma_after=sigma_after,
            n_samples=st.n,
            using_prior=st.n < self.min_samples,
        )


__all__ = [
    "SigmaCalibrator",
    "SigmaUpdate",
    "prior_sigma_for_asset",
    "variance_per_second",
    "gaussian_nll",
]
