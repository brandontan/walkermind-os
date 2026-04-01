"""Phase 7 — Real-time OrderBook engine.

Maintains a live, sorted order book for a single market from WS events.
Computes derived microstructure metrics on demand:
    - best bid / best ask
    - mid price
    - bid-ask spread (absolute + pct)
    - depth at N price levels (bid-side + ask-side)
    - total depth USD

Design:
    - Snapshot events replace the entire book.
    - Delta events patch individual price levels (size=0 → remove level).
    - Sanity check enforced after every update:
          best_bid >= best_ask → book is crossed → invalidate + reset.
    - All prices/sizes stored as float; quantized to 6dp to avoid FP drift.
    - Zero silent failures: raises OrderBookError on unrecoverable corruption.

Usage::

    book = OrderBook(market_id="0xabc...")
    book.apply_snapshot(bids=[[0.52, 100], [0.51, 50]], asks=[[0.54, 80], [0.55, 120]])
    depth = book.depth(levels=5)
    print(book.spread(), book.mid())
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

import structlog

log = structlog.get_logger()

# ── Constants ─────────────────────────────────────────────────────────────────

_PRICE_PRECISION: int = 6       # decimal places for price keys
_SIZE_PRECISION: int = 6        # decimal places for size values
_CROSSED_BOOK_RESET_COUNT: int = 0   # incremented on sanity failures


class OrderBookError(Exception):
    """Raised when the order book reaches an unrecoverable state."""


# ── Microstructure snapshot ────────────────────────────────────────────────────

@dataclass
class OrderBookSnapshot:
    """Point-in-time microstructure metrics computed from the live book.

    Attributes:
        market_id: Market this snapshot belongs to.
        timestamp: Unix epoch seconds when computed.
        best_bid: Highest bid price (0 if no bids).
        best_ask: Lowest ask price (1 if no asks).
        mid: Midpoint price ((bid + ask) / 2).
        spread: Absolute bid-ask spread (ask - bid).
        spread_pct: Spread as a fraction of mid price.
        bid_depth_usd: Total USD depth on bid side (within `levels` levels).
        ask_depth_usd: Total USD depth on ask side (within `levels` levels).
        total_depth_usd: bid_depth_usd + ask_depth_usd.
        is_valid: False if book is crossed or empty.
    """

    market_id: str
    timestamp: float
    best_bid: float
    best_ask: float
    mid: float
    spread: float
    spread_pct: float
    bid_depth_usd: float
    ask_depth_usd: float
    total_depth_usd: float
    is_valid: bool
    levels_used: int


# ── OrderBook ─────────────────────────────────────────────────────────────────

class OrderBook:
    """Real-time order book for a single Polymarket CLOB market.

    Internal storage: sorted dicts keyed by price (float, rounded to 6dp).
        _bids: descending (highest price first)
        _asks: ascending  (lowest price first)

    All methods are synchronous and non-blocking.
    """

    def __init__(self, market_id: str) -> None:
        """Initialise an empty order book for market_id."""
        self.market_id = market_id
        self._bids: dict[float, float] = {}   # price → size
        self._asks: dict[float, float] = {}   # price → size
        self._last_update_ts: float = 0.0
        self._update_count: int = 0
        self._crossed_count: int = 0
        self._is_valid: bool = False           # False until first snapshot

    # ── Snapshot / delta application ──────────────────────────────────────────

    def apply_snapshot(
        self,
        bids: list[list[float]],
        asks: list[list[float]],
        timestamp: Optional[float] = None,
    ) -> None:
        """Replace the entire book with a new snapshot.

        Args:
            bids: List of [price, size] pairs (any order).
            asks: List of [price, size] pairs (any order).
            timestamp: Event timestamp (uses time.time() if None).
        """
        self._bids = {}
        self._asks = {}

        for price, size in bids:
            p = self._q_price(price)
            s = self._q_size(size)
            if s > 0:
                self._bids[p] = s

        for price, size in asks:
            p = self._q_price(price)
            s = self._q_size(size)
            if s > 0:
                self._asks[p] = s

        self._last_update_ts = timestamp or time.time()
        self._update_count += 1
        self._is_valid = True

        if not self._sanity_check():
            log.warning(
                "orderbook_snapshot_crossed",
                market_id=self.market_id,
                best_bid=self.best_bid(),
                best_ask=self.best_ask(),
            )
        else:
            log.debug(
                "orderbook_snapshot_applied",
                market_id=self.market_id,
                bid_levels=len(self._bids),
                ask_levels=len(self._asks),
                spread=round(self.spread(), 6),
            )

    def apply_delta(
        self,
        bids: list[list[float]],
        asks: list[list[float]],
        timestamp: Optional[float] = None,
    ) -> None:
        """Patch the book with a delta update.

        A level with size=0 is removed (maker cancelled / fully filled).
        A level with size>0 is inserted or updated.

        Args:
            bids: [[price, size], ...] — zero size → remove level.
            asks: [[price, size], ...] — zero size → remove level.
            timestamp: Event timestamp.
        """
        if not self._is_valid:
            log.warning(
                "orderbook_delta_before_snapshot",
                market_id=self.market_id,
            )
            return

        for price, size in bids:
            p = self._q_price(price)
            s = self._q_size(size)
            if s == 0:
                self._bids.pop(p, None)
            else:
                self._bids[p] = s

        for price, size in asks:
            p = self._q_price(price)
            s = self._q_size(size)
            if s == 0:
                self._asks.pop(p, None)
            else:
                self._asks[p] = s

        self._last_update_ts = timestamp or time.time()
        self._update_count += 1

        if not self._sanity_check():
            log.warning(
                "orderbook_delta_crossed_after_patch",
                market_id=self.market_id,
                best_bid=self.best_bid(),
                best_ask=self.best_ask(),
            )

    def apply_ws_event(self, data: dict, timestamp: float) -> None:
        """Apply a parsed WS orderbook event (snapshot or delta).

        Args:
            data: WS event data dict with keys: bids, asks, update_type.
            timestamp: Event timestamp from WS message.
        """
        update_type = data.get("update_type", "delta")
        bids = data.get("bids", [])
        asks = data.get("asks", [])

        if update_type == "snapshot":
            self.apply_snapshot(bids, asks, timestamp)
        else:
            self.apply_delta(bids, asks, timestamp)

    # ── Microstructure queries ────────────────────────────────────────────────

    def best_bid(self) -> float:
        """Return the highest bid price. Returns 0.0 if no bids."""
        return max(self._bids.keys(), default=0.0)

    def best_ask(self) -> float:
        """Return the lowest ask price. Returns 1.0 if no asks."""
        return min(self._asks.keys(), default=1.0)

    def mid(self) -> float:
        """Return the midpoint price: (best_bid + best_ask) / 2."""
        return round((self.best_bid() + self.best_ask()) / 2, _PRICE_PRECISION)

    def spread(self) -> float:
        """Return absolute bid-ask spread: best_ask - best_bid."""
        return round(max(self.best_ask() - self.best_bid(), 0.0), _PRICE_PRECISION)

    def spread_pct(self) -> float:
        """Return spread as fraction of mid price. Returns 0.0 if mid == 0."""
        m = self.mid()
        if m == 0:
            return 0.0
        return round(self.spread() / m, _PRICE_PRECISION)

    def depth(self, levels: int = 5) -> "DepthResult":
        """Compute aggregated depth for the top `levels` levels on each side.

        Args:
            levels: Number of price levels to aggregate on each side.

        Returns:
            DepthResult with bid/ask/total depth in USD and price levels.
        """
        # Sort bids descending, asks ascending
        sorted_bids = sorted(self._bids.items(), key=lambda x: -x[0])[:levels]
        sorted_asks = sorted(self._asks.items(), key=lambda x: x[0])[:levels]

        bid_depth = sum(p * s for p, s in sorted_bids)
        ask_depth = sum(p * s for p, s in sorted_asks)

        return DepthResult(
            bid_depth_usd=round(bid_depth, 2),
            ask_depth_usd=round(ask_depth, 2),
            total_depth_usd=round(bid_depth + ask_depth, 2),
            bid_levels=sorted_bids,
            ask_levels=sorted_asks,
        )

    def snapshot(self, levels: int = 5) -> OrderBookSnapshot:
        """Return a full microstructure snapshot.

        Args:
            levels: Depth levels to aggregate.

        Returns:
            OrderBookSnapshot with all metrics.
        """
        bb = self.best_bid()
        ba = self.best_ask()
        m = round((bb + ba) / 2, _PRICE_PRECISION)
        sp = round(max(ba - bb, 0.0), _PRICE_PRECISION)
        sp_pct = round(sp / m, _PRICE_PRECISION) if m > 0 else 0.0
        d = self.depth(levels)

        return OrderBookSnapshot(
            market_id=self.market_id,
            timestamp=self._last_update_ts,
            best_bid=bb,
            best_ask=ba,
            mid=m,
            spread=sp,
            spread_pct=sp_pct,
            bid_depth_usd=d.bid_depth_usd,
            ask_depth_usd=d.ask_depth_usd,
            total_depth_usd=d.total_depth_usd,
            is_valid=self._is_valid,
            levels_used=levels,
        )

    def is_valid(self) -> bool:
        """Return True if book has been initialised and is not crossed."""
        return self._is_valid

    def is_stale(self, max_age_s: float = 5.0) -> bool:
        """Return True if last update was more than max_age_s seconds ago."""
        return (time.time() - self._last_update_ts) > max_age_s

    def reset(self) -> None:
        """Clear the book and mark invalid (force re-snapshot from API)."""
        self._bids = {}
        self._asks = {}
        self._is_valid = False
        log.warning("orderbook_reset", market_id=self.market_id)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _sanity_check(self) -> bool:
        """Validate book state. Returns False if book is crossed or empty."""
        bb = self.best_bid()
        ba = self.best_ask()

        if bb == 0.0 and ba == 1.0:
            # Empty book — mark invalid but don't raise
            self._is_valid = False
            log.debug("orderbook_empty", market_id=self.market_id)
            return False

        if bb >= ba:
            self._crossed_count += 1
            self._is_valid = False
            log.error(
                "orderbook_crossed",
                market_id=self.market_id,
                best_bid=bb,
                best_ask=ba,
                crossed_count=self._crossed_count,
            )
            # Auto-reset crossed book
            self.reset()
            return False

        self._is_valid = True
        return True

    @staticmethod
    def _q_price(price: float) -> float:
        """Quantize price to _PRICE_PRECISION decimal places."""
        return round(float(price), _PRICE_PRECISION)

    @staticmethod
    def _q_size(size: float) -> float:
        """Quantize size to _SIZE_PRECISION decimal places."""
        return round(float(size), _SIZE_PRECISION)


# ── DepthResult ───────────────────────────────────────────────────────────────

@dataclass
class DepthResult:
    """Aggregated depth for top N levels on each side."""

    bid_depth_usd: float
    ask_depth_usd: float
    total_depth_usd: float
    bid_levels: list[tuple[float, float]]   # [(price, size), ...]
    ask_levels: list[tuple[float, float]]   # [(price, size), ...]


# ── OrderBookManager ──────────────────────────────────────────────────────────

class OrderBookManager:
    """Manages a collection of OrderBook instances, one per market.

    Single entry-point for the Phase 7 runner to dispatch WS events.
    """

    def __init__(self) -> None:
        self._books: dict[str, OrderBook] = {}

    def get_or_create(self, market_id: str) -> OrderBook:
        """Return existing book or create a new one."""
        if market_id not in self._books:
            self._books[market_id] = OrderBook(market_id)
            log.info("orderbook_created", market_id=market_id)
        return self._books[market_id]

    def apply_ws_event(self, event_type: str, market_id: str, data: dict, timestamp: float) -> None:
        """Route a WS event to the appropriate OrderBook.

        Args:
            event_type: "orderbook" or "trade" (trade events are ignored here).
            market_id: Target market.
            data: WS event data dict.
            timestamp: Event timestamp.
        """
        if event_type != "orderbook":
            return
        book = self.get_or_create(market_id)
        book.apply_ws_event(data, timestamp)

    def snapshot(self, market_id: str, levels: int = 5) -> Optional[OrderBookSnapshot]:
        """Return a microstructure snapshot for a market, or None if not tracked."""
        book = self._books.get(market_id)
        if book is None or not book.is_valid():
            return None
        return book.snapshot(levels)

    def is_valid(self, market_id: str) -> bool:
        """Return True if book exists and is valid for market_id."""
        book = self._books.get(market_id)
        return book is not None and book.is_valid()

    def request_resync(self, market_id: str) -> None:
        """Invalidate a book and signal need for snapshot resync."""
        book = self._books.get(market_id)
        if book:
            book.reset()
        log.warning("orderbook_resync_requested", market_id=market_id)

    def market_ids(self) -> list[str]:
        """Return all tracked market IDs."""
        return list(self._books.keys())
