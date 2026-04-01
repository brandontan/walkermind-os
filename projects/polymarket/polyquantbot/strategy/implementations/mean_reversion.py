"""Mean Reversion Strategy — trades when price deviates from its EWMA.

Strategy logic:
  - Maintains an exponentially weighted moving average (EWMA) of mid prices.
  - Computes normalised deviation: (mid - ewma) / ewma.
  - Emits a NO signal when deviation is significantly positive (price above EWMA → revert down).
  - Emits a YES signal when deviation is significantly negative (price below EWMA → revert up).

Risk controls:
  - α = 0.25 Kelly fraction applied to position sizing.
  - Minimum liquidity depth filter.
  - Max position cap enforced via size_usdc.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

import structlog

from ..base.base_strategy import BaseStrategy, SignalResult

log = structlog.get_logger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_KELLY_FRACTION: float = 0.25
_DEFAULT_MAX_POSITION_USD: float = 100.0
_DEFAULT_EWMA_ALPHA: float = 0.1        # smoothing factor (0 < α ≤ 1)
_DEFAULT_DEVIATION_THRESHOLD: float = 0.05  # 5% deviation triggers signal
_DEFAULT_MIN_DEPTH_USD: float = 10_000.0
_WARMUP_TICKS: int = 10                 # minimum ticks before first signal


class MeanReversionStrategy(BaseStrategy):
    """Mean Reversion Strategy.

    Detects over-extension of the current price relative to its EWMA and trades
    the expected reversion back to the mean.

    Args:
        min_edge: Minimum normalised-deviation edge required to emit a signal.
        ewma_alpha: EWMA smoothing factor (higher = faster response).
        deviation_threshold: Minimum |normalised deviation| to act on.
        max_position_usd: Hard cap on recommended position size (USDC).
        min_depth_usd: Minimum combined bid+ask depth required.
    """

    def __init__(
        self,
        min_edge: float = 0.02,
        ewma_alpha: float = _DEFAULT_EWMA_ALPHA,
        deviation_threshold: float = _DEFAULT_DEVIATION_THRESHOLD,
        max_position_usd: float = _DEFAULT_MAX_POSITION_USD,
        min_depth_usd: float = _DEFAULT_MIN_DEPTH_USD,
    ) -> None:
        super().__init__(min_edge=min_edge)
        self._alpha = max(1e-4, min(1.0, ewma_alpha))
        self._deviation_threshold = deviation_threshold
        self._max_position_usd = max_position_usd
        self._min_depth_usd = min_depth_usd
        self._ewma: Optional[float] = None
        self._tick_count: int = 0

    @property
    def name(self) -> str:
        """Unique strategy identifier."""
        return "mean_reversion"

    async def is_ready(self) -> bool:
        """Return True once enough ticks have been seen to establish the EWMA."""
        return self._tick_count >= _WARMUP_TICKS

    async def evaluate(
        self,
        market_id: str,
        market_data: Dict[str, Any],
    ) -> Optional[SignalResult]:
        """Evaluate a market tick and return a signal on mean-reversion opportunity.

        Args:
            market_id: Polymarket condition ID.
            market_data: Dict with keys: bid, ask, mid, depth_yes, depth_no.

        Returns:
            SignalResult if normalised deviation passes threshold, else None.
        """
        async with self._lock:
            bid: float = float(market_data.get("bid", 0.0))
            ask: float = float(market_data.get("ask", 1.0))
            mid: float = float(market_data.get("mid", (bid + ask) / 2.0))
            depth_yes: float = float(market_data.get("depth_yes", 0.0))
            depth_no: float = float(market_data.get("depth_no", 0.0))

            # Liquidity filter
            if (depth_yes + depth_no) < self._min_depth_usd:
                return None

            # Update EWMA
            if self._ewma is None:
                self._ewma = mid
            else:
                self._ewma = self._alpha * mid + (1.0 - self._alpha) * self._ewma

            self._tick_count += 1

            if not await self.is_ready():
                return None

            ewma = self._ewma
            if ewma <= 0:
                return None

            # Normalised deviation: positive → price above mean (bearish)
            deviation = (mid - ewma) / ewma

            log.debug(
                "mean_reversion.evaluated",
                market_id=market_id,
                mid=round(mid, 4),
                ewma=round(ewma, 4),
                deviation=round(deviation, 4),
                threshold=self._deviation_threshold,
            )

            if abs(deviation) < self._deviation_threshold:
                return None

            # Price above EWMA → expect reversion downward → trade NO
            # Price below EWMA → expect reversion upward → trade YES
            side = "NO" if deviation > 0 else "YES"
            edge = abs(deviation)

            if edge < self._min_edge:
                return None

            # Position sizing: fractional Kelly
            price = ask if side == "YES" else bid
            price = max(0.01, min(0.99, price))
            raw_size = edge * _KELLY_FRACTION * self._max_position_usd
            size_usdc = min(raw_size, self._max_position_usd)
            size_usdc = max(1.0, round(size_usdc, 2))

            return SignalResult(
                market_id=market_id,
                side=side,
                edge=round(edge, 4),
                size_usdc=size_usdc,
                confidence=min(1.0, edge / max(self._deviation_threshold, 1e-6)),
                metadata={
                    "strategy": self.name,
                    "ewma": round(ewma, 4),
                    "mid": round(mid, 4),
                    "deviation": round(deviation, 4),
                    "tick_count": self._tick_count,
                },
            )

    def reset(self) -> None:
        """Reset EWMA state (e.g. on reconnect or market restart)."""
        self._ewma = None
        self._tick_count = 0
        log.info("mean_reversion.reset", strategy=self.name)
