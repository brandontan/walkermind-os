"""EV Momentum Strategy — trades when model probability diverges from market price.

Strategy logic:
  - Maintains a short rolling window of mid prices to estimate price momentum.
  - Computes a model probability by projecting current momentum forward.
  - Emits a YES signal when p_model > p_market + min_edge.
  - Emits a NO signal when p_model < p_market - min_edge.

Risk controls:
  - α = 0.25 Kelly fraction applied to position sizing.
  - Minimum liquidity check (depth threshold).
  - Max position cap enforced via size_usdc.
"""
from __future__ import annotations

import asyncio
from collections import deque
from typing import Any, Deque, Dict, Optional

import structlog

from ..base.base_strategy import BaseStrategy, SignalResult

log = structlog.get_logger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_KELLY_FRACTION: float = 0.25          # always fractional Kelly
_DEFAULT_MAX_POSITION_USD: float = 100.0
_DEFAULT_WINDOW: int = 20              # rolling window for momentum
_DEFAULT_MOMENTUM_SCALE: float = 2.0   # multiplier for momentum → edge projection
_DEFAULT_MIN_DEPTH_USD: float = 10_000.0


class EVMomentumStrategy(BaseStrategy):
    """EV Momentum Strategy.

    Estimates a short-term probability model from recent price momentum and
    trades when the estimated edge exceeds ``min_edge``.

    Args:
        min_edge: Minimum model-vs-market edge required to emit a signal.
        window: Number of recent mid-price ticks used to compute momentum.
        momentum_scale: Multiplier applied to raw momentum when projecting p_model.
        max_position_usd: Hard cap on recommended position size (USDC).
        min_depth_usd: Minimum combined bid+ask depth required (liquidity filter).
    """

    def __init__(
        self,
        min_edge: float = 0.02,
        window: int = _DEFAULT_WINDOW,
        momentum_scale: float = _DEFAULT_MOMENTUM_SCALE,
        max_position_usd: float = _DEFAULT_MAX_POSITION_USD,
        min_depth_usd: float = _DEFAULT_MIN_DEPTH_USD,
    ) -> None:
        super().__init__(min_edge=min_edge)
        self._window = max(2, window)
        self._momentum_scale = momentum_scale
        self._max_position_usd = max_position_usd
        self._min_depth_usd = min_depth_usd
        self._prices: Deque[float] = deque(maxlen=self._window)

    @property
    def name(self) -> str:
        """Unique strategy identifier."""
        return "ev_momentum"

    async def is_ready(self) -> bool:
        """Return True once the rolling window is fully populated."""
        return len(self._prices) >= self._window

    async def evaluate(
        self,
        market_id: str,
        market_data: Dict[str, Any],
    ) -> Optional[SignalResult]:
        """Evaluate a market tick and return a signal if edge is sufficient.

        Args:
            market_id: Polymarket condition ID.
            market_data: Dict with keys: bid, ask, mid, depth_yes, depth_no, volume.

        Returns:
            SignalResult if model edge passes threshold, else None.
        """
        async with self._lock:
            bid: float = float(market_data.get("bid", 0.0))
            ask: float = float(market_data.get("ask", 1.0))
            mid: float = float(market_data.get("mid", (bid + ask) / 2.0))
            depth_yes: float = float(market_data.get("depth_yes", 0.0))
            depth_no: float = float(market_data.get("depth_no", 0.0))

            # Liquidity filter
            total_depth = depth_yes + depth_no
            if total_depth < self._min_depth_usd:
                log.debug(
                    "ev_momentum.liquidity_filter",
                    market_id=market_id,
                    total_depth=total_depth,
                    threshold=self._min_depth_usd,
                )
                return None

            # Track price history
            self._prices.append(mid)

            if not await self.is_ready():
                return None

            # Compute momentum as mean price change per tick
            prices = list(self._prices)
            deltas = [prices[i + 1] - prices[i] for i in range(len(prices) - 1)]
            momentum = sum(deltas) / len(deltas) if deltas else 0.0

            # Project model probability using momentum
            p_model = float(mid + self._momentum_scale * momentum)
            p_model = max(0.01, min(0.99, p_model))   # clamp to valid range
            p_market = float(mid)
            edge = p_model - p_market

            log.debug(
                "ev_momentum.evaluated",
                market_id=market_id,
                p_model=round(p_model, 4),
                p_market=round(p_market, 4),
                edge=round(edge, 4),
                threshold=self._min_edge,
            )

            if abs(edge) < self._min_edge:
                return None

            # Determine trade direction
            side = "YES" if edge > 0 else "NO"
            # Fractional Kelly sizing: edge / (1 / p_model) × KELLY_FRACTION
            price = ask if side == "YES" else bid
            price = max(0.01, min(0.99, price))
            kelly_edge = abs(edge)
            raw_size = (kelly_edge / (1.0 / max(price, 1e-6))) * _KELLY_FRACTION if price > 0 else 0.0
            size_usdc = min(raw_size, self._max_position_usd)
            size_usdc = max(1.0, round(size_usdc, 2))

            return SignalResult(
                market_id=market_id,
                side=side,
                edge=abs(edge),
                size_usdc=size_usdc,
                confidence=1.0,
                metadata={
                    "strategy": self.name,
                    "p_model": round(p_model, 4),
                    "p_market": round(p_market, 4),
                    "momentum": round(momentum, 6),
                    "window": self._window,
                },
            )
