"""Phase 7 — MarketCache patch with live microstructure.

Extends the Phase 6.6 MarketCache to store and serve:
    - Real-time bid/ask/spread from OrderBook
    - Market depth (USD) from OrderBook
    - Trade flow (buy/sell imbalance) from trade stream
    - API round-trip latency per execution
    - Timestamp of last WS update

All data is updated by the Phase 7 runner when WS events arrive.
The Phase 6.6 decision engine reads from this cache for fill probability,
routing decisions, and sizing — no logic changes in Phase 6.6 required.

Backward compatibility:
    Phase7MarketCache is a drop-in replacement for Phase 6.6 MarketCache.
    All existing get_volatility(), get_latency_ms(), get_returns() methods preserved.
    New methods are additive only.
"""
from __future__ import annotations

import math
import statistics
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import structlog

from .orderbook import OrderBookSnapshot

log = structlog.get_logger()

# ── Constants ─────────────────────────────────────────────────────────────────

_PRICE_FLOOR: float = 1e-9
_DEFAULT_LATENCY_MS: float = 50.0
_DEFAULT_VOL: float = 0.02
_TRADE_FLOW_WINDOW: int = 100       # number of trades to keep for flow calc
_VOL_LOOKBACK: int = 20             # log-return window for volatility
_PRICE_WINDOW: int = 52             # max rolling prices (Phase 6.6 compat)


# ── Microstructure snapshot ────────────────────────────────────────────────────

@dataclass
class MicrostructureState:
    """Live microstructure state for a single market.

    Updated from WS events by Phase7MarketCache.
    """

    market_id: str

    # From OrderBook
    best_bid: float = 0.0
    best_ask: float = 1.0
    mid: float = 0.5
    spread: float = 0.02
    spread_pct: float = 0.04
    bid_depth_usd: float = 0.0
    ask_depth_usd: float = 0.0
    total_depth_usd: float = 0.0
    orderbook_valid: bool = False
    last_orderbook_ts: float = 0.0

    # From trade stream
    trade_flow_imbalance: float = 0.0   # normalized ∈ [-1, 1]; positive = buy pressure
    last_trade_price: float = 0.0
    last_trade_size: float = 0.0
    last_trade_side: str = "UNKNOWN"    # "BUY" | "SELL"
    last_trade_ts: float = 0.0

    # Execution latency (updated by LiveExecutor)
    last_exec_latency_ms: float = _DEFAULT_LATENCY_MS

    # Last WS update timestamp
    last_ws_update_ts: float = 0.0


# ── Phase7MarketCache ─────────────────────────────────────────────────────────

class Phase7MarketCache:
    """Extended MarketCache for Phase 7 live trading.

    Drop-in replacement for Phase 6.6 MarketCache.
    Adds real-time microstructure from OrderBook + trade stream.

    Thread-safety: single asyncio event loop only.
    """

    def __init__(
        self,
        default_vol: float = _DEFAULT_VOL,
        vol_lookback: int = _VOL_LOOKBACK,
    ) -> None:
        """Initialise the cache.

        Args:
            default_vol: Fallback volatility when history is insufficient.
            vol_lookback: Number of log-returns for stdev computation.
        """
        self._default_vol = default_vol
        self._lookback = vol_lookback

        # Phase 6.6-compatible rolling price/return store
        self._prices: dict[str, deque] = {}
        self._returns: dict[str, list[float]] = {}
        self._latency: dict[str, float] = {}

        # Phase 7 microstructure store
        self._micro: dict[str, MicrostructureState] = {}

        # Trade flow ring buffer: market_id → deque of (side, size)
        self._trade_buf: dict[str, deque] = {}

    # ── Phase 6.6 compatible API (unchanged) ─────────────────────────────────

    def on_tick(
        self,
        market_id: str,
        price: float,
        latency_ms: Optional[float] = None,
    ) -> None:
        """Record a new price observation (Phase 6.6 compatible).

        Called by runner on every market data event.
        """
        safe = max(price, _PRICE_FLOOR)

        if market_id not in self._prices:
            self._prices[market_id] = deque(maxlen=_PRICE_WINDOW)
            self._returns[market_id] = []

        self._prices[market_id].append(safe)

        # Recompute log-returns
        pl = list(self._prices[market_id])
        if len(pl) >= 2:
            self._returns[market_id] = [
                math.log(pl[i] / max(pl[i - 1], _PRICE_FLOOR))
                for i in range(1, len(pl))
            ]

        if latency_ms is not None:
            self._latency[market_id] = max(latency_ms, 0.0)

    def get_returns(self, market_id: str) -> list[float]:
        """Return log-returns for a market (newest last)."""
        return list(self._returns.get(market_id, []))

    def get_volatility(self, market_id: str) -> float:
        """Return realised volatility. Returns default_vol if unknown."""
        returns = self._returns.get(market_id, [])
        window = returns[-self._lookback:] if len(returns) >= self._lookback else returns
        if len(window) < 2:
            return self._default_vol
        try:
            vol = statistics.stdev(window)
        except statistics.StatisticsError:
            return self._default_vol
        return vol if math.isfinite(vol) and vol >= 0 else self._default_vol

    def get_latency_ms(self, market_id: str) -> float:
        """Return last observed round-trip latency (ms)."""
        # Prefer execution latency from Phase 7; fall back to data latency
        micro = self._micro.get(market_id)
        if micro and micro.last_exec_latency_ms != _DEFAULT_LATENCY_MS:
            return micro.last_exec_latency_ms
        return self._latency.get(market_id, _DEFAULT_LATENCY_MS)

    def get_prev_price(self, market_id: str) -> Optional[float]:
        """Return second-to-last price for momentum computation."""
        prices = self._prices.get(market_id)
        if prices and len(prices) >= 2:
            pl = list(prices)
            return pl[-2]
        return None

    def get_latest_price(self, market_id: str) -> Optional[float]:
        """Return most recent recorded price."""
        prices = self._prices.get(market_id)
        return prices[-1] if prices else None

    def market_ids(self) -> list[str]:
        """Return all tracked market IDs."""
        return list(self._prices.keys())

    # ── Phase 7 microstructure updates ───────────────────────────────────────

    def on_orderbook_update(self, snap: OrderBookSnapshot) -> None:
        """Update microstructure from a fresh OrderBook snapshot.

        Called by the Phase 7 runner whenever the OrderBook is updated.

        Args:
            snap: OrderBookSnapshot from OrderBook.snapshot().
        """
        m = self._get_or_create_micro(snap.market_id)
        m.best_bid = snap.best_bid
        m.best_ask = snap.best_ask
        m.mid = snap.mid
        m.spread = snap.spread
        m.spread_pct = snap.spread_pct
        m.bid_depth_usd = snap.bid_depth_usd
        m.ask_depth_usd = snap.ask_depth_usd
        m.total_depth_usd = snap.total_depth_usd
        m.orderbook_valid = snap.is_valid
        m.last_orderbook_ts = snap.timestamp
        m.last_ws_update_ts = time.time()

        # Also update rolling mid price for volatility computation
        if snap.is_valid and snap.mid > 0:
            self.on_tick(snap.market_id, snap.mid)

        log.debug(
            "market_cache_orderbook_updated",
            market_id=snap.market_id,
            bid=snap.best_bid,
            ask=snap.best_ask,
            spread=snap.spread,
            depth_usd=snap.total_depth_usd,
        )

    def on_trade(
        self,
        market_id: str,
        price: float,
        size: float,
        side: str,
        timestamp: float,
    ) -> None:
        """Record a trade event and update trade flow imbalance.

        Args:
            market_id: Market where trade occurred.
            price: Trade execution price.
            size: Trade size in USD.
            side: "BUY" or "SELL".
            timestamp: Trade timestamp.
        """
        m = self._get_or_create_micro(market_id)
        m.last_trade_price = price
        m.last_trade_size = size
        m.last_trade_side = side
        m.last_trade_ts = timestamp
        m.last_ws_update_ts = time.time()

        # Append to trade flow ring buffer
        if market_id not in self._trade_buf:
            self._trade_buf[market_id] = deque(maxlen=_TRADE_FLOW_WINDOW)
        self._trade_buf[market_id].append((side.upper(), size))

        # Recompute imbalance
        m.trade_flow_imbalance = self._compute_imbalance(market_id)

        log.debug(
            "market_cache_trade_recorded",
            market_id=market_id,
            price=price,
            size=size,
            side=side,
            flow_imbalance=round(m.trade_flow_imbalance, 4),
        )

    def on_execution_latency(self, market_id: str, latency_ms: float) -> None:
        """Update execution round-trip latency for a market.

        Called by LiveExecutor after each order submission.

        Args:
            market_id: Target market.
            latency_ms: Measured API RTT in milliseconds.
        """
        m = self._get_or_create_micro(market_id)
        m.last_exec_latency_ms = max(latency_ms, 0.0)
        self._latency[market_id] = max(latency_ms, 0.0)

        log.debug(
            "market_cache_latency_updated",
            market_id=market_id,
            latency_ms=round(latency_ms, 2),
        )

    # ── Phase 7 microstructure reads ─────────────────────────────────────────

    def get_spread(self, market_id: str) -> float:
        """Return last known bid-ask spread. Falls back to 0.02 if unknown."""
        micro = self._micro.get(market_id)
        return micro.spread if micro and micro.orderbook_valid else 0.02

    def get_depth(self, market_id: str) -> float:
        """Return total market depth in USD. Returns 0.0 if unknown."""
        micro = self._micro.get(market_id)
        return micro.total_depth_usd if micro and micro.orderbook_valid else 0.0

    def get_bid(self, market_id: str) -> float:
        """Return best bid price. Returns 0.0 if unknown."""
        micro = self._micro.get(market_id)
        return micro.best_bid if micro and micro.orderbook_valid else 0.0

    def get_ask(self, market_id: str) -> float:
        """Return best ask price. Returns 1.0 if unknown."""
        micro = self._micro.get(market_id)
        return micro.best_ask if micro and micro.orderbook_valid else 1.0

    def get_mid(self, market_id: str) -> float:
        """Return mid price. Returns 0.5 if unknown."""
        micro = self._micro.get(market_id)
        return micro.mid if micro and micro.orderbook_valid else 0.5

    def get_trade_flow_imbalance(self, market_id: str) -> float:
        """Return normalized trade flow imbalance ∈ [-1, 1].

        Positive = net buy pressure, Negative = net sell pressure.
        Returns 0.0 if no trades observed.
        """
        micro = self._micro.get(market_id)
        return micro.trade_flow_imbalance if micro else 0.0

    def get_microstructure(self, market_id: str) -> Optional[MicrostructureState]:
        """Return full microstructure state for a market."""
        return self._micro.get(market_id)

    def get_market_context(self, market_id: str) -> dict:
        """Return market context dict compatible with Phase 6.6 ExecutionEnginePatch.

        Keys: bid, ask, spread, depth, volume, mid
        """
        micro = self._micro.get(market_id)
        if micro and micro.orderbook_valid:
            return {
                "bid": micro.best_bid,
                "ask": micro.best_ask,
                "spread": micro.spread,
                "depth": micro.total_depth_usd,
                "volume": micro.total_depth_usd,   # best proxy without historical volume
                "mid": micro.mid,
            }
        # Fallback context (Phase 6.6 safe defaults)
        return {
            "bid": 0.495,
            "ask": 0.505,
            "spread": 0.01,
            "depth": 100.0,
            "volume": 100.0,
            "mid": 0.5,
        }

    def is_orderbook_valid(self, market_id: str) -> bool:
        """Return True if the live orderbook for this market is valid."""
        micro = self._micro.get(market_id)
        return micro is not None and micro.orderbook_valid

    def is_stale(self, market_id: str, max_age_s: float = 5.0) -> bool:
        """Return True if no WS update received within max_age_s."""
        micro = self._micro.get(market_id)
        if micro is None:
            return True
        return (time.time() - micro.last_ws_update_ts) > max_age_s

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _get_or_create_micro(self, market_id: str) -> MicrostructureState:
        if market_id not in self._micro:
            self._micro[market_id] = MicrostructureState(market_id=market_id)
        return self._micro[market_id]

    def _compute_imbalance(self, market_id: str) -> float:
        """Compute normalized buy/sell imbalance from trade buffer.

        Formula:
            buy_vol  = sum of size where side == BUY
            sell_vol = sum of size where side == SELL
            imbalance = (buy_vol - sell_vol) / (buy_vol + sell_vol + ε)

        Returns:
            float ∈ [-1, 1]: positive = buy pressure, negative = sell pressure.
        """
        buf = self._trade_buf.get(market_id)
        if not buf:
            return 0.0

        buy_vol = sum(s for side, s in buf if side == "BUY")
        sell_vol = sum(s for side, s in buf if side == "SELL")
        total = buy_vol + sell_vol

        if total < 1e-9:
            return 0.0

        imbalance = (buy_vol - sell_vol) / total
        return round(max(-1.0, min(1.0, imbalance)), 6)
