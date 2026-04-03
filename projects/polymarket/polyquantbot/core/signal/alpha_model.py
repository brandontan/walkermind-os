"""core.signal.alpha_model — Structured probabilistic alpha model.

Computes p_model from real market microstructure signals:

  1. **Price deviation** — distance of the current market price from its
     rolling mean.  A price above its recent mean implies short-term
     upward bias; below implies downward bias.

  2. **Momentum** — mean signed price change over the last N ticks.
     Positive momentum projects a continuing upward move; negative implies
     a continuing downward move.

  3. **Liquidity weighting** — scales the momentum contribution by the
     fraction of a reference liquidity level observed in the market.
     Thin books produce noisier price discovery and should carry less
     weight in the model estimate.

The model is stateful: it maintains an in-memory per-market rolling price
buffer.  ``record_tick`` must be called before ``compute_p_model`` to
accumulate history; the model returns a sensible (low-conviction) estimate
even when the buffer is empty or sparse.

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
from collections import deque
from typing import Optional

import structlog

log = structlog.get_logger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

_DEFAULT_WINDOW: int = 20
_DEFAULT_DEVIATION_WEIGHT: float = 0.5    # weight on mean-reversion deviation
_DEFAULT_MOMENTUM_SCALE: float = 1.0      # amplifier for momentum signal (reduced from 2.0 to lower noise)
_REF_LIQUIDITY_USD: float = 100_000.0     # normalisation reference (100 k)
_MIN_VOLATILITY: float = 1e-4             # floor to avoid zero-division


# ── ProbabilisticAlphaModel ────────────────────────────────────────────────────


class ProbabilisticAlphaModel:
    """Stateful alpha model: price deviation + momentum + liquidity weighting.

    Args:
        window: Rolling window size for price history.
        deviation_weight: Coefficient for the mean-reversion deviation term.
        momentum_scale: Amplifier applied to the raw per-tick momentum before
            multiplying by the liquidity weight.
        ref_liquidity_usd: Reference liquidity used to normalise the weighting
            to the [0, 1] range.
    """

    def __init__(
        self,
        window: int = _DEFAULT_WINDOW,
        deviation_weight: float = _DEFAULT_DEVIATION_WEIGHT,
        momentum_scale: float = _DEFAULT_MOMENTUM_SCALE,
        ref_liquidity_usd: float = _REF_LIQUIDITY_USD,
    ) -> None:
        self._window = max(2, window)
        self._deviation_weight = deviation_weight
        self._momentum_scale = momentum_scale
        self._ref_liquidity = max(ref_liquidity_usd, 1.0)
        self._price_history: dict[str, deque[float]] = {}

        log.info(
            "alpha_model_initialized",
            window=self._window,
            deviation_weight=deviation_weight,
            momentum_scale=momentum_scale,
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
    ) -> tuple[float, float]:
        """Compute ``(p_model, volatility)`` for the given market.

        If the price buffer for *market_id* is empty, the method uses
        *p_market* as the seed value and returns a low-conviction estimate
        (``p_model ≈ p_market``, ``volatility ≈ MIN_VOLATILITY``).

        Args:
            market_id: Polymarket condition ID.
            p_market: Current market-implied probability (bid-ask mid).
            liquidity_usd: Total USD depth observed in the orderbook.

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

        # ── Momentum ──────────────────────────────────────────────────────────
        if n >= 2:
            deltas = [prices[i + 1] - prices[i] for i in range(n - 1)]
            momentum: float = sum(deltas) / len(deltas)
        else:
            momentum = 0.0

        # ── Liquidity weighting (clamped to [0, 1]) ───────────────────────────
        liq_weight: float = min(liquidity_usd / self._ref_liquidity, 1.0)

        # ── Compose p_model ───────────────────────────────────────────────────
        # p_model = p_market
        #         + deviation_weight × deviation        (mean reversion)
        #         + momentum_scale   × momentum × liq   (trend, scaled by depth)
        raw_p_model = (
            p_market
            + self._deviation_weight * deviation
            + self._momentum_scale * momentum * liq_weight
        )
        p_model = max(0.01, min(0.99, raw_p_model))

        # ── Volatility (sample standard deviation of price history) ──────────
        if n >= 2:
            mean_p = sum(prices) / n
            variance = sum((p - mean_p) ** 2 for p in prices) / n
            volatility = math.sqrt(variance)
        else:
            volatility = _MIN_VOLATILITY

        volatility = max(volatility, _MIN_VOLATILITY)

        log.debug(
            "alpha_model_computed",
            market_id=market_id,
            p_market=round(p_market, 4),
            p_model=round(p_model, 4),
            deviation=round(deviation, 6),
            momentum=round(momentum, 6),
            liq_weight=round(liq_weight, 4),
            volatility=round(volatility, 6),
            n_ticks=n,
        )

        return p_model, volatility
