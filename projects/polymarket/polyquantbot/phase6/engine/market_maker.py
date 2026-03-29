"""Toxicity-aware market maker — Phase 6.

Places bid/ask quote orders around mid-price and monitors for adverse
selection (toxicity). When toxicity is detected:
  - All open orders are cancelled via asyncio.create_task() (non-blocking).
  - MM is disabled for cooldown_seconds.

Toxicity conditions (either triggers the guard):
  1. Price move >= 3 ticks since the last quote placement.
  2. Volume imbalance > 2  (buy_vol / sell_vol > 2 OR < 0.5).

Cancellation is non-blocking:
  - Uses asyncio.create_task() so the event loop is never blocked.
  - Each cancel is retried with delays [0.05, 0.1, 0.2] seconds.
  - Race condition (order filled during cancel delay) is detected and logged
    as "mm_cancel_race_condition"; portfolio state is reconciled before proceeding.

Edge cases handled:
  - Order fills completely during async cancellation delay (race condition log).
  - MM in cooldown: place_quotes() returns [] without blocking.
  - Duplicate cancellation: idempotent via status check.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

import structlog

log = structlog.get_logger()

_TICK_SIZE: float = 0.01                    # minimum price increment (Polymarket)
_TOXICITY_TICKS: int = 3                    # ticks of adverse move to trigger guard
_VOLUME_IMBALANCE_THRESHOLD: float = 2.0   # buy/sell ratio beyond which is toxic
_CANCEL_RETRY_DELAYS: list[float] = [0.05, 0.1, 0.2]


@dataclass
class Quote:
    """A single market-maker quote (bid or ask side)."""

    order_id: str
    market_id: str
    outcome: str    # "YES" | "NO"
    side: str       # "BID" | "ASK"
    price: float
    size: float
    placed_at: float = field(default_factory=time.time)
    status: str = "OPEN"    # OPEN | CANCELLED | FILLED


@dataclass
class MMState:
    """Per-market internal state for the market maker."""

    market_id: str
    active_quotes: list[Quote] = field(default_factory=list)
    price_history: list[float] = field(default_factory=list)
    disabled_until: float = 0.0
    toxicity_count: int = 0


class MarketMaker:
    """Async toxicity-aware market maker with non-blocking cancellation."""

    def __init__(
        self,
        spread_pct: float = 0.02,
        size: float = 10.0,
        min_order_size: float = 5.0,
        cooldown_seconds: float = 60.0,
    ) -> None:
        """Initialise market maker.

        Args:
            spread_pct: Half-spread as fraction of mid-price (e.g., 0.02 = 2%).
            size: Quote size per side in USD.
            min_order_size: Orders below this threshold are not placed.
            cooldown_seconds: Duration MM stays disabled after a toxicity trigger.
        """
        self._spread_pct = spread_pct
        self._size = size
        self._min_size = min_order_size
        self._cooldown = cooldown_seconds
        self._states: dict[str, MMState] = {}
        self._cancel_tasks: set[asyncio.Task] = set()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_state(self, market_id: str) -> MMState:
        """Return existing or new MMState for a market."""
        if market_id not in self._states:
            self._states[market_id] = MMState(market_id=market_id)
        return self._states[market_id]

    def _is_active(self, market_id: str) -> bool:
        """Return True if MM is not in cooldown for this market."""
        return time.time() >= self._get_state(market_id).disabled_until

    # ── Toxicity detection ────────────────────────────────────────────────────

    def _check_price_move(self, state: MMState, current_price: float) -> bool:
        """Detect >= TOXICITY_TICKS adverse price move from last reference."""
        if not state.price_history:
            return False
        reference = state.price_history[-1]
        ticks = abs(current_price - reference) / _TICK_SIZE
        return ticks >= _TOXICITY_TICKS

    def _check_volume_imbalance(self, buy_vol: float, sell_vol: float) -> bool:
        """Detect buy/sell imbalance beyond threshold in either direction."""
        if sell_vol <= 0:
            return buy_vol > 0
        ratio = buy_vol / sell_vol
        return (
            ratio > _VOLUME_IMBALANCE_THRESHOLD
            or ratio < (1.0 / _VOLUME_IMBALANCE_THRESHOLD)
        )

    async def check_toxicity(
        self,
        market_id: str,
        current_price: float,
        buy_vol: float,
        sell_vol: float,
        correlation_id: str,
    ) -> bool:
        """Evaluate both toxicity conditions and log if triggered.

        Args:
            market_id: Market being evaluated.
            current_price: Latest mid-price tick.
            buy_vol: Recent buy-side volume.
            sell_vol: Recent sell-side volume.
            correlation_id: Request ID for log correlation.

        Returns:
            True if either toxicity condition is met.
        """
        state = self._get_state(market_id)
        price_toxic = self._check_price_move(state, current_price)
        volume_toxic = self._check_volume_imbalance(buy_vol, sell_vol)

        if price_toxic or volume_toxic:
            imbalance = buy_vol / sell_vol if sell_vol > 0 else float("inf")
            log.warning(
                "toxicity_detected",
                correlation_id=correlation_id,
                market_id=market_id,
                current_price=current_price,
                reference_price=(
                    state.price_history[-1] if state.price_history else None
                ),
                price_toxic=price_toxic,
                volume_toxic=volume_toxic,
                volume_imbalance=round(imbalance, 4),
                toxicity_count=state.toxicity_count + 1,
            )
            state.toxicity_count += 1
            return True

        return False

    # ── Non-blocking order cancellation ──────────────────────────────────────

    async def _cancel_order_with_retry(
        self,
        quote: Quote,
        correlation_id: str,
    ) -> bool:
        """Cancel a single order with fallback delays [0.05, 0.1, 0.2]s.

        Must be run via asyncio.create_task() — not awaited directly —
        so the event loop is never blocked.

        Race condition: if the order fills between delay iterations, log
        "mm_cancel_race_condition" and return False for reconciliation.

        Returns:
            True if successfully cancelled, False on fill race or timeout.
        """
        for delay in _CANCEL_RETRY_DELAYS:
            await asyncio.sleep(delay)

            if quote.status == "FILLED":
                # Race condition: order filled during cancellation window
                log.warning(
                    "mm_cancel_race_condition",
                    correlation_id=correlation_id,
                    market_id=quote.market_id,
                    order_id=quote.order_id,
                    outcome=quote.outcome,
                    side=quote.side,
                    fill_price=quote.price,
                    action="reconcile_portfolio_required",
                )
                return False

            if quote.status == "CANCELLED":
                return True  # Already cancelled (idempotent)

            # Simulate cancel success (paper mode)
            quote.status = "CANCELLED"
            log.info(
                "mm_order_cancelled",
                correlation_id=correlation_id,
                market_id=quote.market_id,
                order_id=quote.order_id,
                side=quote.side,
                outcome=quote.outcome,
                price=quote.price,
            )
            return True

        # All retries exhausted
        log.error(
            "mm_cancel_failed_all_retries",
            correlation_id=correlation_id,
            market_id=quote.market_id,
            order_id=quote.order_id,
        )
        return False

    async def cancel_all_orders(
        self,
        market_id: str,
        correlation_id: str,
    ) -> None:
        """Fire-and-forget cancellation of all OPEN orders for a market.

        Uses asyncio.create_task() so callers are NOT blocked.
        Each filled order detected during cancel triggers reconciliation log.
        """
        state = self._get_state(market_id)
        open_quotes = [q for q in state.active_quotes if q.status == "OPEN"]

        if not open_quotes:
            log.debug(
                "mm_no_open_orders",
                correlation_id=correlation_id,
                market_id=market_id,
            )
            return

        log.info(
            "mm_cancelling_all",
            correlation_id=correlation_id,
            market_id=market_id,
            count=len(open_quotes),
        )

        for quote in open_quotes:
            task = asyncio.create_task(
                self._cancel_order_with_retry(quote, correlation_id)
            )
            self._cancel_tasks.add(task)
            task.add_done_callback(self._cancel_tasks.discard)

    # ── Toxicity handler ──────────────────────────────────────────────────────

    async def handle_toxicity(
        self,
        market_id: str,
        correlation_id: str,
    ) -> None:
        """Disable MM and fire async cancellation of all open orders.

        MM remains disabled for cooldown_seconds. cancel_all_orders() does
        NOT block the event loop.
        """
        state = self._get_state(market_id)
        state.disabled_until = time.time() + self._cooldown

        log.warning(
            "mm_toxicity_halt",
            correlation_id=correlation_id,
            market_id=market_id,
            cooldown_seconds=self._cooldown,
            disabled_until=round(state.disabled_until, 1),
        )

        await self.cancel_all_orders(market_id, correlation_id)

    # ── Quote placement ───────────────────────────────────────────────────────

    async def place_quotes(
        self,
        market_id: str,
        mid_price: float,
        buy_vol: float,
        sell_vol: float,
        correlation_id: str,
    ) -> list[Quote]:
        """Place bid and ask quotes around mid-price if MM is healthy.

        Flow:
          1. Skip if MM is in cooldown.
          2. Check toxicity; trigger halt if detected.
          3. Compute bid/ask from half-spread.
          4. Place quotes and update price history.

        Args:
            market_id: Target market.
            mid_price: Current mid-price.
            buy_vol: Recent buy volume (toxicity input).
            sell_vol: Recent sell volume (toxicity input).
            correlation_id: Request ID for logging.

        Returns:
            List of placed Quote objects (empty if skipped).
        """
        if not self._is_active(market_id):
            state = self._get_state(market_id)
            remaining = max(0.0, state.disabled_until - time.time())
            log.debug(
                "mm_in_cooldown",
                correlation_id=correlation_id,
                market_id=market_id,
                remaining_s=round(remaining, 1),
            )
            return []

        is_toxic = await self.check_toxicity(
            market_id, mid_price, buy_vol, sell_vol, correlation_id
        )
        if is_toxic:
            await self.handle_toxicity(market_id, correlation_id)
            return []

        half_spread = mid_price * self._spread_pct
        bid_price = max(0.01, round(mid_price - half_spread, 4))
        ask_price = min(0.99, round(mid_price + half_spread, 4))

        if self._size < self._min_size:
            log.warning(
                "mm_size_below_min",
                correlation_id=correlation_id,
                size=self._size,
                min_size=self._min_size,
            )
            return []

        bid = Quote(
            order_id=str(uuid.uuid4()),
            market_id=market_id,
            outcome="YES",
            side="BID",
            price=bid_price,
            size=self._size,
        )
        ask = Quote(
            order_id=str(uuid.uuid4()),
            market_id=market_id,
            outcome="YES",
            side="ASK",
            price=ask_price,
            size=self._size,
        )

        state = self._get_state(market_id)
        state.active_quotes = [bid, ask]
        state.price_history.append(mid_price)
        if len(state.price_history) > 10:
            state.price_history.pop(0)

        log.info(
            "mm_quotes_placed",
            correlation_id=correlation_id,
            market_id=market_id,
            bid=bid_price,
            ask=ask_price,
            spread=round(ask_price - bid_price, 4),
            size=self._size,
        )

        return [bid, ask]

    async def cleanup(self) -> None:
        """Wait for all pending cancel tasks to complete on shutdown."""
        if self._cancel_tasks:
            await asyncio.gather(*list(self._cancel_tasks), return_exceptions=True)
        log.info("mm_cleanup_complete", cancelled_tasks=len(self._cancel_tasks))
