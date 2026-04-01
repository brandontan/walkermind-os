"""Phase 7 — TradeFlowAnalyzer.

Computes normalized buy/sell imbalance (trade flow) from the live trade stream.
Trade flow is a microstructure signal indicating directional pressure:
    - Positive → buyers aggressive (price likely to rise)
    - Negative → sellers aggressive (price likely to fall)

Formula:
    buy_vol  = sum(size for side == BUY, last N trades)
    sell_vol = sum(size for side == SELL, last N trades)
    imbalance = (buy_vol - sell_vol) / (buy_vol + sell_vol + ε)

Output is stored in Phase7MarketCache and passed to the execution engine
as a microstructure feature (additional signal, not a hard gate).

Usage::

    analyzer = TradeFlowAnalyzer()
    analyzer.on_trade("0xabc", price=0.52, size=100.0, side="BUY", timestamp=ts)
    result = analyzer.get_flow("0xabc")
    print(result.imbalance, result.buy_volume, result.sell_volume)
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

import structlog

log = structlog.get_logger()

# ── Constants ─────────────────────────────────────────────────────────────────

_DEFAULT_WINDOW: int = 100      # trades in rolling window
_EPSILON: float = 1e-9          # prevent division by zero
_FLOW_DECAY_HALF_LIFE_S: float = 60.0   # half-life for time-weighted variant


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class TradeSample:
    """Single trade event."""

    price: float
    size: float
    side: str       # "BUY" | "SELL"
    timestamp: float


@dataclass
class TradeFlowResult:
    """Trade flow imbalance result for a market.

    Attributes:
        market_id: Market this result belongs to.
        imbalance: Normalized ∈ [-1, 1]; positive = buy pressure.
        buy_volume: Total buy-side volume in window (USD).
        sell_volume: Total sell-side volume in window (USD).
        total_volume: buy_volume + sell_volume.
        trade_count: Number of trades in window.
        last_trade_side: Side of most recent trade.
        last_trade_price: Price of most recent trade.
        computed_at: Unix timestamp when computed.
    """

    market_id: str
    imbalance: float
    buy_volume: float
    sell_volume: float
    total_volume: float
    trade_count: int
    last_trade_side: str
    last_trade_price: float
    computed_at: float


# ── TradeFlowAnalyzer ─────────────────────────────────────────────────────────

class TradeFlowAnalyzer:
    """Computes real-time normalized buy/sell trade flow imbalance.

    Maintains a rolling window of recent trades per market.
    Thread-safety: single asyncio event loop only.
    """

    def __init__(self, window_size: int = _DEFAULT_WINDOW) -> None:
        """Initialise the analyzer.

        Args:
            window_size: Number of most recent trades to consider per market.
        """
        self._window = window_size
        self._buffers: dict[str, deque] = {}    # market_id → deque[TradeSample]
        self._last_result: dict[str, TradeFlowResult] = {}

    def on_trade(
        self,
        market_id: str,
        price: float,
        size: float,
        side: str,
        timestamp: float,
    ) -> TradeFlowResult:
        """Record a new trade and recompute flow imbalance.

        Args:
            market_id: Market where trade occurred.
            price: Trade execution price.
            size: Trade notional size (USD).
            side: "BUY" or "SELL" (case-insensitive).
            timestamp: Trade timestamp (Unix epoch seconds).

        Returns:
            Updated TradeFlowResult for this market.
        """
        if market_id not in self._buffers:
            self._buffers[market_id] = deque(maxlen=self._window)

        safe_side = side.upper()
        if safe_side not in ("BUY", "SELL"):
            log.warning(
                "trade_flow_unknown_side",
                market_id=market_id,
                side=side,
            )
            safe_side = "UNKNOWN"

        sample = TradeSample(
            price=float(price),
            size=max(float(size), 0.0),
            side=safe_side,
            timestamp=float(timestamp),
        )
        self._buffers[market_id].append(sample)

        result = self._compute(market_id)
        self._last_result[market_id] = result

        log.debug(
            "trade_flow_updated",
            market_id=market_id,
            imbalance=result.imbalance,
            buy_vol=round(result.buy_volume, 2),
            sell_vol=round(result.sell_volume, 2),
            trade_count=result.trade_count,
            last_side=safe_side,
        )

        return result

    def get_flow(self, market_id: str) -> Optional[TradeFlowResult]:
        """Return the most recent flow result for a market.

        Returns None if no trades have been recorded yet.
        """
        return self._last_result.get(market_id)

    def get_imbalance(self, market_id: str) -> float:
        """Return normalized imbalance ∈ [-1, 1], or 0.0 if no data."""
        result = self._last_result.get(market_id)
        return result.imbalance if result else 0.0

    def market_ids(self) -> list[str]:
        """Return all tracked market IDs."""
        return list(self._buffers.keys())

    def recompute_all(self) -> dict[str, TradeFlowResult]:
        """Recompute flow for all tracked markets. Returns updated results."""
        for market_id in list(self._buffers.keys()):
            self._last_result[market_id] = self._compute(market_id)
        return dict(self._last_result)

    def summary(self, market_id: str) -> dict:
        """Return a dict summary suitable for structured logging."""
        r = self._last_result.get(market_id)
        if r is None:
            return {"market_id": market_id, "imbalance": 0.0, "trade_count": 0}
        return {
            "market_id": r.market_id,
            "imbalance": r.imbalance,
            "buy_volume": round(r.buy_volume, 2),
            "sell_volume": round(r.sell_volume, 2),
            "total_volume": round(r.total_volume, 2),
            "trade_count": r.trade_count,
            "last_trade_side": r.last_trade_side,
            "last_trade_price": r.last_trade_price,
        }

    # ── Internal ──────────────────────────────────────────────────────────────

    def _compute(self, market_id: str) -> TradeFlowResult:
        """Recompute normalized imbalance from the rolling buffer."""
        buf = self._buffers.get(market_id, deque())
        samples = list(buf)

        buy_vol = sum(s.size for s in samples if s.side == "BUY")
        sell_vol = sum(s.size for s in samples if s.side == "SELL")
        total = buy_vol + sell_vol

        imbalance = (buy_vol - sell_vol) / (total + _EPSILON)
        imbalance = round(max(-1.0, min(1.0, imbalance)), 6)

        last = samples[-1] if samples else None

        return TradeFlowResult(
            market_id=market_id,
            imbalance=imbalance,
            buy_volume=round(buy_vol, 4),
            sell_volume=round(sell_vol, 4),
            total_volume=round(total, 4),
            trade_count=len(samples),
            last_trade_side=last.side if last else "UNKNOWN",
            last_trade_price=last.price if last else 0.0,
            computed_at=time.time(),
        )
