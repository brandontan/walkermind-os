"""Liquidity Edge Strategy — trades the better-quoted side of a wide spread.

Strategy logic:
  - Detects markets with anomalously wide bid-ask spreads.
  - Infers directional edge from the relative depth of each side of the book:
    · If YES depth >> NO depth: market is more liquid on YES → trade YES.
    · If NO depth >> YES depth: market is more liquid on NO → trade NO.
  - Edge is estimated from the spread relative to a baseline spread EWMA.

Risk controls:
  - α = 0.25 Kelly fraction applied to position sizing.
  - Minimum absolute spread filter (ignores already-tight spreads).
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
_DEFAULT_MIN_SPREAD: float = 0.04       # at least 4 cents wide before considering
_DEFAULT_SPREAD_EWMA_ALPHA: float = 0.05
_DEFAULT_SPREAD_MULTIPLIER: float = 1.5  # spread must be 1.5× EWMA baseline
_DEFAULT_DEPTH_RATIO_THRESHOLD: float = 1.5  # one side ≥ 1.5× the other
_DEFAULT_MIN_DEPTH_USD: float = 10_000.0
_WARMUP_TICKS: int = 15


class LiquidityEdgeStrategy(BaseStrategy):
    """Liquidity Edge Strategy.

    Finds markets where the spread has widened significantly above its baseline
    and one side of the book is materially deeper. Trades the deeper (more liquid)
    side, capturing the implied liquidity discount as edge.

    Args:
        min_edge: Minimum estimated edge required to emit a signal.
        min_spread: Minimum absolute spread required (below this, market is too tight).
        spread_ewma_alpha: EWMA smoothing factor for the baseline spread.
        spread_multiplier: Current spread must exceed this multiple of EWMA spread.
        depth_ratio_threshold: One side must be this many times deeper than the other.
        max_position_usd: Hard cap on recommended position size (USDC).
        min_depth_usd: Minimum combined bid+ask depth required.
    """

    def __init__(
        self,
        min_edge: float = 0.02,
        min_spread: float = _DEFAULT_MIN_SPREAD,
        spread_ewma_alpha: float = _DEFAULT_SPREAD_EWMA_ALPHA,
        spread_multiplier: float = _DEFAULT_SPREAD_MULTIPLIER,
        depth_ratio_threshold: float = _DEFAULT_DEPTH_RATIO_THRESHOLD,
        max_position_usd: float = _DEFAULT_MAX_POSITION_USD,
        min_depth_usd: float = _DEFAULT_MIN_DEPTH_USD,
    ) -> None:
        super().__init__(min_edge=min_edge)
        self._min_spread = min_spread
        self._spread_alpha = max(1e-4, min(1.0, spread_ewma_alpha))
        self._spread_multiplier = spread_multiplier
        self._depth_ratio_threshold = depth_ratio_threshold
        self._max_position_usd = max_position_usd
        self._min_depth_usd = min_depth_usd
        self._spread_ewma: Optional[float] = None
        self._tick_count: int = 0

    @property
    def name(self) -> str:
        """Unique strategy identifier."""
        return "liquidity_edge"

    async def is_ready(self) -> bool:
        """Return True once spread EWMA is established."""
        return self._tick_count >= _WARMUP_TICKS

    async def evaluate(
        self,
        market_id: str,
        market_data: Dict[str, Any],
    ) -> Optional[SignalResult]:
        """Evaluate a market tick and return a signal on liquidity-edge opportunity.

        Args:
            market_id: Polymarket condition ID.
            market_data: Dict with keys: bid, ask, mid, depth_yes, depth_no.

        Returns:
            SignalResult if spread dislocation and depth imbalance detected, else None.
        """
        async with self._lock:
            bid: float = float(market_data.get("bid", 0.0))
            ask: float = float(market_data.get("ask", 1.0))
            depth_yes: float = float(market_data.get("depth_yes", 0.0))
            depth_no: float = float(market_data.get("depth_no", 0.0))

            if ask <= bid:
                return None

            spread = ask - bid

            # Liquidity floor filter
            total_depth = depth_yes + depth_no
            if total_depth < self._min_depth_usd:
                return None

            # Absolute spread minimum filter (ignore trivially-wide markets)
            if spread < self._min_spread:
                return None

            # Update spread EWMA
            if self._spread_ewma is None:
                self._spread_ewma = spread
            else:
                self._spread_ewma = (
                    self._spread_alpha * spread
                    + (1.0 - self._spread_alpha) * self._spread_ewma
                )

            self._tick_count += 1

            if not await self.is_ready():
                return None

            spread_ewma = self._spread_ewma
            if spread_ewma <= 0:
                return None

            # Spread must be significantly wider than baseline
            if spread < self._spread_multiplier * spread_ewma:
                return None

            # Depth imbalance check
            depth_ratio = (
                depth_yes / max(depth_no, 1e-6)
                if depth_yes >= depth_no
                else depth_no / max(depth_yes, 1e-6)
            )

            if depth_ratio < self._depth_ratio_threshold:
                log.debug(
                    "liquidity_edge.depth_ratio_insufficient",
                    market_id=market_id,
                    depth_ratio=round(depth_ratio, 2),
                    threshold=self._depth_ratio_threshold,
                )
                return None

            # Trade the deeper (more liquid) side
            side = "YES" if depth_yes >= depth_no else "NO"

            # Estimate edge from relative spread dislocation
            spread_ratio = spread / max(spread_ewma, 1e-6)
            edge = min((spread_ratio - 1.0) * 0.5, 0.30)  # cap at 30%

            log.debug(
                "liquidity_edge.evaluated",
                market_id=market_id,
                spread=round(spread, 4),
                spread_ewma=round(spread_ewma, 4),
                spread_ratio=round(spread_ratio, 2),
                depth_yes=depth_yes,
                depth_no=depth_no,
                side=side,
                edge=round(edge, 4),
            )

            if edge < self._min_edge:
                return None

            # Position sizing: fractional Kelly capped by max_position
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
                confidence=min(1.0, depth_ratio / max(self._depth_ratio_threshold, 1e-6) * 0.5),
                metadata={
                    "strategy": self.name,
                    "spread": round(spread, 4),
                    "spread_ewma": round(spread_ewma, 4),
                    "spread_ratio": round(spread_ratio, 2),
                    "depth_yes": depth_yes,
                    "depth_no": depth_no,
                    "depth_ratio": round(depth_ratio, 2),
                },
            )

    def reset(self) -> None:
        """Reset spread EWMA state (e.g. on reconnect)."""
        self._spread_ewma = None
        self._tick_count = 0
        log.info("liquidity_edge.reset", strategy=self.name)
