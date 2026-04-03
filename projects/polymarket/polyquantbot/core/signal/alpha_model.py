"""core.signal.alpha_model — Structured probabilistic alpha model.

Computes p_model from real market microstructure signals:

  1. **Price deviation** — distance of the current market price from its
     rolling mean.  A price above its recent mean implies short-term
     upward bias; below implies downward bias.

  2. **Momentum** — exponential-weighted mean signed price change over the
     last N ticks.  Recent ticks carry more weight than older ones.
     Positive momentum projects a continuing upward move; negative implies
     a continuing downward move.

  3. **Liquidity weighting** — scales the momentum contribution by the
     fraction of a reference liquidity level observed in the market.
     Thin books produce noisier price discovery and should carry less
     weight in the model estimate.

  4. **Volatility breakout** — a standardised z-score breakout signal.
     When the current price sits more than ``_BREAKOUT_Z_THRESHOLD``
     standard deviations from the rolling mean the breakout direction is
     amplified, reflecting continuation bias in short-term price moves.
     The contribution is clamped at ``_BREAKOUT_Z_MAX`` sigma to prevent
     runaway sizing in extreme moves.

The model is stateful: it maintains an in-memory per-market rolling price
buffer.  ``record_tick`` must be called before ``compute_p_model`` to
accumulate history; the model returns a sensible (low-conviction) estimate
even when the buffer is empty or sparse.

Early-tick dampening is applied when fewer than ``_MIN_HISTORY_TICKS``
prices have been observed so that an unstable seed does not generate
over-confident edges.

Usage::

    alpha = ProbabilisticAlphaModel(window=20)
    alpha.record_tick("0xabc", price=0.42)
    p_model, volatility = alpha.compute_p_model(
        market_id="0xabc",
        p_market=0.42,
        liquidity_usd=50_000.0,
    )
    edge = p_model - p_market
    confidence = edge / volatility
"""
from __future__ import annotations

import math
import random
from collections import deque
from typing import Optional

import structlog

log = structlog.get_logger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

_DEFAULT_WINDOW: int = 20
_DEFAULT_DEVIATION_WEIGHT: float = 0.8    # weight on mean-reversion deviation (increased from 0.5)
_DEFAULT_MOMENTUM_SCALE: float = 1.5      # amplifier for momentum signal (increased from 1.0)
_DEFAULT_BREAKOUT_WEIGHT: float = 0.04    # additional weight for z-score breakout signal
_BREAKOUT_Z_THRESHOLD: float = 0.5        # minimum z-score to activate breakout contribution
_BREAKOUT_Z_MAX: float = 2.0             # z-score cap to avoid runaway amplification
_MIN_HISTORY_TICKS: int = 5              # minimum ticks for stable signal (early-tick guard)
_MOMENTUM_EW_ALPHA: float = 0.3          # exponential weight for recent vs older momentum
_REF_LIQUIDITY_USD: float = 100_000.0     # normalisation reference (100 k)
_MIN_VOLATILITY: float = 1e-4             # floor to avoid zero-division
_FORCE_MODE_DEVIATION_MIN: float = 0.02   # minimum random deviation injected in force mode
_FORCE_MODE_DEVIATION_MAX: float = 0.05   # maximum random deviation injected in force mode


# ── ProbabilisticAlphaModel ────────────────────────────────────────────────────


class ProbabilisticAlphaModel:
    """Stateful alpha model: price deviation + momentum + liquidity weighting + volatility breakout.

    Args:
        window: Rolling window size for price history.
        deviation_weight: Coefficient for the mean-reversion deviation term.
        momentum_scale: Amplifier applied to the exponential-weighted per-tick
            momentum before multiplying by the liquidity weight.
        ref_liquidity_usd: Reference liquidity used to normalise the weighting
            to the [0, 1] range.
        breakout_weight: Additional edge contributed when the current price is
            more than ``_BREAKOUT_Z_THRESHOLD`` standard deviations from the
            rolling mean (volatility breakout signal).
    """

    def __init__(
        self,
        window: int = _DEFAULT_WINDOW,
        deviation_weight: float = _DEFAULT_DEVIATION_WEIGHT,
        momentum_scale: float = _DEFAULT_MOMENTUM_SCALE,
        ref_liquidity_usd: float = _REF_LIQUIDITY_USD,
        breakout_weight: float = _DEFAULT_BREAKOUT_WEIGHT,
    ) -> None:
        self._window = max(2, window)
        self._deviation_weight = deviation_weight
        self._momentum_scale = momentum_scale
        self._ref_liquidity = max(ref_liquidity_usd, 1.0)
        self._breakout_weight = breakout_weight
        self._price_history: dict[str, deque[float]] = {}

        log.info(
            "alpha_model_initialized",
            window=self._window,
            deviation_weight=deviation_weight,
            momentum_scale=momentum_scale,
            breakout_weight=breakout_weight,
        )

    # ── State management ──────────────────────────────────────────────────────

    def record_tick(self, market_id: str, price: float) -> None:
        """Append a price observation to the per-market rolling buffer.

        Args:
            market_id: Polymarket condition ID.
            price: Observed market price (e.g. best bid-ask mid).
        """
        if market_id not in self._price_history:
            self._price_history[market_id] = deque(maxlen=self._window)
        self._price_history[market_id].append(float(price))

    def clear(self, market_id: Optional[str] = None) -> None:
        """Clear price history for one market or all markets.

        Args:
            market_id: If given, clears only that market; otherwise clears all.
        """
        if market_id is not None:
            self._price_history.pop(market_id, None)
        else:
            self._price_history.clear()

    # ── Core computation ──────────────────────────────────────────────────────

    def compute_p_model(
        self,
        market_id: str,
        p_market: float,
        liquidity_usd: float,
        force_mode: bool = False,
    ) -> tuple[float, float]:
        """Compute ``(p_model, volatility)`` for the given market.

        If the price buffer for *market_id* is empty, the method uses
        *p_market* as the seed value and returns a low-conviction estimate
        (``p_model ≈ p_market``, ``volatility ≈ MIN_VOLATILITY``).

        Signals computed:
          - Price deviation from rolling mean (direction bias)
          - Exponential-weighted momentum (recent price drift)
          - Liquidity weighting on momentum
          - Volatility breakout (z-score amplification when |z| ≥ threshold)

        Early-tick dampening: all signal contributions are linearly scaled
        toward zero for the first ``_MIN_HISTORY_TICKS`` ticks to avoid
        over-confident edges from an unstable seed.

        Args:
            market_id: Polymarket condition ID.
            p_market: Current market-implied probability (bid-ask mid).
            liquidity_usd: Total USD depth observed in the orderbook.
            force_mode: When True, injects a bounded random deviation
                ``[0.02, 0.05]`` to guarantee ``p_model > p_market`` and a
                non-zero edge even when the price buffer is sparse.

        Returns:
            ``(p_model, volatility)`` where *p_model* is clamped to
            ``[0.01, 0.99]`` and *volatility* is at least ``_MIN_VOLATILITY``.
        """
        prices = list(self._price_history.get(market_id, []))
        n = len(prices)

        # ── Mean and deviation ────────────────────────────────────────────────
        if n > 0:
            mean_price = sum(prices) / n
        else:
            mean_price = p_market
        deviation: float = p_market - mean_price

        # ── Volatility (sample standard deviation of price history) ──────────
        if n >= 2:
            mean_p = sum(prices) / n
            variance = sum((p - mean_p) ** 2 for p in prices) / n
            volatility = math.sqrt(variance)
        else:
            volatility = _MIN_VOLATILITY

        volatility = max(volatility, _MIN_VOLATILITY)

        # ── Exponential-weighted momentum (more weight on recent ticks) ───────
        if n >= 2:
            deltas = [prices[i + 1] - prices[i] for i in range(n - 1)]
            # Exponential weighting: most-recent delta has weight α, older (1-α)^k
            ew_momentum: float = 0.0
            ew_sum: float = 0.0
            for k, d in enumerate(reversed(deltas)):
                w = (1.0 - _MOMENTUM_EW_ALPHA) ** k
                ew_momentum += w * d
                ew_sum += w
            momentum: float = ew_momentum / ew_sum if ew_sum > 0 else 0.0
        else:
            momentum = 0.0

        # ── Liquidity weighting (clamped to [0, 1]) ───────────────────────────
        liq_weight: float = min(liquidity_usd / self._ref_liquidity, 1.0)

        # ── Volatility breakout signal (z-score amplification) ────────────────
        # When price sits > _BREAKOUT_Z_THRESHOLD sigma from mean, amplify in
        # the same direction — reflecting short-term continuation bias.
        z_score: float = deviation / volatility
        if abs(z_score) >= _BREAKOUT_Z_THRESHOLD:
            trend_strength = min(abs(z_score), _BREAKOUT_Z_MAX) / _BREAKOUT_Z_MAX
            breakout_contribution: float = (
                (1.0 if z_score > 0 else -1.0) * self._breakout_weight * trend_strength
            )
        else:
            breakout_contribution = 0.0

        # ── Compose p_model ───────────────────────────────────────────────────
        # p_model = p_market
        #         + deviation_weight × deviation        (mean-price bias)
        #         + momentum_scale   × momentum × liq   (trend, scaled by depth)
        #         + breakout_contribution               (z-score amplification)
        raw_p_model = (
            p_market
            + self._deviation_weight * deviation
            + self._momentum_scale * momentum * liq_weight
            + breakout_contribution
        )

        # ── Early-tick dampening: reduce signal confidence for sparse history ─
        if n < _MIN_HISTORY_TICKS and not force_mode:
            tick_confidence = n / _MIN_HISTORY_TICKS  # 0.0 → 1.0 ramp
            raw_p_model = p_market + (raw_p_model - p_market) * tick_confidence

        p_model = max(0.01, min(0.99, raw_p_model))

        # ── Force mode: inject random deviation to guarantee non-zero edge ────
        if force_mode and p_model <= p_market:
            injected: float = random.uniform(_FORCE_MODE_DEVIATION_MIN, _FORCE_MODE_DEVIATION_MAX)
            p_model = max(0.01, min(0.99, p_market + injected))
            log.info(
                "alpha_injected",
                market_id=market_id,
                deviation=round(injected, 4),
                p_market=round(p_market, 4),
                p_model=round(p_model, 4),
                force_mode=True,
            )

        edge: float = p_model - p_market
        confidence: float = edge / volatility

        log.debug(
            "alpha_model_computed",
            market_id=market_id,
            p_market=round(p_market, 4),
            p_model=round(p_model, 4),
            edge=round(edge, 4),
            deviation=round(deviation, 6),
            momentum=round(momentum, 6),
            z_score=round(z_score, 4),
            breakout=round(breakout_contribution, 6),
            liq_weight=round(liq_weight, 4),
            volatility=round(volatility, 6),
            confidence=round(confidence, 4),
            n_ticks=n,
        )

        return p_model, volatility
