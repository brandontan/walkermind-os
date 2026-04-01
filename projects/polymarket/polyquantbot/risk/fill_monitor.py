"""Phase 8 — FillMonitor: Deterministic fill tracking with dedup and retry.

Design guarantees:
    - processed_order_ids: set prevents any order from being processed twice.
    - risk_guard.disabled fast-path exits at the top of the monitoring loop
      AND before every individual order check.
    - Timeout enforcement: orders not filled within order_timeout_sec are
      cancelled and marked failed.
    - Exponential backoff on poll retries: await asyncio.sleep(2 ** retry_count)
    - max_retry limit: after exhaustion the order is marked failed and removed
      from tracking.
    - Partial fills are tracked — only fully-filled orders are marked complete.
    - WS disconnect mid-trade is handled via the polling fallback.
    - Structured JSON logging on every state change.

Usage::

    monitor = FillMonitor(
        executor=live_executor,
        position_tracker=tracker,
        risk_guard=guard,
        order_timeout_sec=30.0,
        max_retry=5,
        poll_interval_sec=2.0,
    )

    # Register an order for monitoring:
    monitor.register(order_id="0xabc...", market_id="0xdef...",
                     side="YES", size=50.0, price=0.62, correlation_id="...")

    # Run the monitor loop (long-running coroutine):
    await monitor.run()
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import structlog

log = structlog.get_logger()

# ── Constants ─────────────────────────────────────────────────────────────────

_ORDER_TIMEOUT_SEC: float = 30.0    # cancel order if not filled within this time
_MAX_RETRY: int = 5                  # max poll attempts per order
_POLL_INTERVAL_SEC: float = 2.0     # base polling interval
_MONITOR_LOOP_INTERVAL_SEC: float = 1.0  # main loop tick


# ── Order state ───────────────────────────────────────────────────────────────

class OrderStatus(str, Enum):
    """Fill tracking lifecycle states."""
    PENDING = "PENDING"      # registered, awaiting fill confirmation
    FILLED = "FILLED"        # fully filled
    PARTIAL = "PARTIAL"      # partially filled (still monitoring)
    CANCELLED = "CANCELLED"  # timeout or kill switch cancel
    FAILED = "FAILED"        # max retries exhausted


@dataclass
class TrackedOrder:
    """Internal state for a single monitored order.

    Attributes:
        order_id: Exchange-assigned order ID.
        market_id: Polymarket condition ID.
        side: "YES" | "NO".
        size: Requested size in USD.
        price: Limit price.
        correlation_id: Request trace ID.
        status: Current fill tracking state.
        registered_at: Unix timestamp when registered.
        retry_count: Number of poll attempts made so far.
        filled_size: USD amount confirmed filled so far.
        avg_fill_price: VWAP of all confirmed fills.
    """

    order_id: str
    market_id: str
    side: str
    size: float
    price: float
    correlation_id: str
    status: OrderStatus = OrderStatus.PENDING
    registered_at: float = field(default_factory=time.time)
    retry_count: int = 0
    filled_size: float = 0.0
    avg_fill_price: float = 0.0
    last_confirmed_fill_size: float = 0.0  # tracks fill size last sent to position_tracker


# ── FillMonitor ───────────────────────────────────────────────────────────────

class FillMonitor:
    """Deterministic fill monitor — tracks orders from submission to completion.

    Thread-safety: designed for single asyncio event loop.
    The processed_order_ids set is an append-only dedup store.
    All mutations to _tracked go through the single event loop (no threads).
    """

    def __init__(
        self,
        executor,              # LiveExecutor — used to cancel and poll orders
        position_tracker,      # PositionTracker — updated on confirmed fill
        risk_guard,            # RiskGuard — kill switch fast-path
        order_timeout_sec: float = _ORDER_TIMEOUT_SEC,
        max_retry: int = _MAX_RETRY,
        poll_interval_sec: float = _POLL_INTERVAL_SEC,
        monitor_loop_interval_sec: float = _MONITOR_LOOP_INTERVAL_SEC,
    ) -> None:
        """Initialise the fill monitor.

        Args:
            executor: LiveExecutor for cancel_order() and get_order_status().
            position_tracker: PositionTracker for open() on confirmed fill.
            risk_guard: RiskGuard instance for disabled flag.
            order_timeout_sec: Cancel order if not filled within this time.
            max_retry: Max poll attempts before marking FAILED.
            poll_interval_sec: Base wait between polls (actual: 2^retry_count).
            monitor_loop_interval_sec: Main loop tick interval.
        """
        self._executor = executor
        self._tracker = position_tracker
        self._risk_guard = risk_guard
        self._timeout_sec = order_timeout_sec
        self._max_retry = max_retry
        self._poll_interval_sec = poll_interval_sec
        self._loop_interval_sec = monitor_loop_interval_sec

        # Dedup: once an order_id enters this set it will never be processed again
        self._processed_order_ids: set[str] = set()

        # Active order tracking (order_id → TrackedOrder)
        self._tracked: dict[str, TrackedOrder] = {}

        self._running: bool = False

        log.info(
            "fill_monitor_initialized",
            order_timeout_sec=order_timeout_sec,
            max_retry=max_retry,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def register(
        self,
        order_id: str,
        market_id: str,
        side: str,
        size: float,
        price: float,
        correlation_id: Optional[str] = None,
    ) -> bool:
        """Register an order for fill monitoring.

        Idempotent: silently skips if order_id is already processed or tracked.

        Args:
            order_id: Exchange-assigned order ID.
            market_id: Polymarket condition ID.
            side: "YES" | "NO".
            size: Order size in USD.
            price: Limit price.
            correlation_id: Optional trace ID.

        Returns:
            True if registered. False if skipped (dedup or already processed).
        """
        cid = correlation_id or str(uuid.uuid4())

        # Fast-path: already processed
        if order_id in self._processed_order_ids:
            log.warning(
                "fill_monitor_register_skipped_already_processed",
                order_id=order_id,
                correlation_id=cid,
            )
            return False

        # Fast-path: already tracked
        if order_id in self._tracked:
            log.warning(
                "fill_monitor_register_skipped_already_tracked",
                order_id=order_id,
                correlation_id=cid,
            )
            return False

        self._tracked[order_id] = TrackedOrder(
            order_id=order_id,
            market_id=market_id,
            side=side,
            size=round(size, 6),
            price=round(price, 6),
            correlation_id=cid,
        )

        log.info(
            "fill_monitor_order_registered",
            order_id=order_id,
            market_id=market_id,
            side=side,
            size=size,
            price=price,
            correlation_id=cid,
        )
        return True

    def on_ws_fill(
        self,
        order_id: str,
        filled_size: float,
        avg_price: float,
        correlation_id: Optional[str] = None,
    ) -> None:
        """Handle a fill event received via WebSocket feed.

        Updates tracked order in-place. If fully filled, marks FILLED and
        schedules position open via the next monitor loop iteration.

        Idempotent: skips if order_id is already in processed_order_ids.

        Args:
            order_id: Exchange order ID.
            filled_size: Cumulative filled size in USD.
            avg_price: Volume-weighted average fill price.
            correlation_id: Optional trace ID.
        """
        cid = correlation_id or str(uuid.uuid4())

        # Dedup guard
        if order_id in self._processed_order_ids:
            log.debug(
                "fill_monitor_ws_fill_skipped_duplicate",
                order_id=order_id,
                correlation_id=cid,
            )
            return

        order = self._tracked.get(order_id)
        if order is None:
            # Not tracked — possibly filled immediately at submission; ignore.
            return

        # Compute incremental fill delta (avoid double counting)
        prev_filled = order.filled_size
        new_filled = round(filled_size, 6)

        if new_filled <= prev_filled + 1e-9:
            # No new fill since last update, skip
            log.debug(
                "fill_monitor_ws_fill_no_delta",
                order_id=order_id,
                prev_filled=prev_filled,
                new_filled=new_filled,
                correlation_id=cid,
            )
            return

        # Compute VWAP for the cumulative fill
        if prev_filled > 0 and order.avg_fill_price > 0:
            delta = new_filled - prev_filled
            order.avg_fill_price = round(
                (prev_filled * order.avg_fill_price + delta * avg_price) / new_filled,
                6,
            )
        else:
            order.avg_fill_price = round(avg_price, 6)

        order.filled_size = new_filled

        if order.filled_size >= order.size * 0.999:
            order.status = OrderStatus.FILLED
            log.info(
                "fill_monitor_ws_fill_complete",
                order_id=order_id,
                market_id=order.market_id,
                filled_size=order.filled_size,
                avg_price=order.avg_fill_price,
                correlation_id=cid,
            )
        else:
            order.status = OrderStatus.PARTIAL
            log.info(
                "fill_monitor_ws_fill_partial",
                order_id=order_id,
                market_id=order.market_id,
                filled_size=order.filled_size,
                requested_size=order.size,
                fill_delta=round(new_filled - prev_filled, 6),
                avg_price=order.avg_fill_price,
                correlation_id=cid,
            )

    # ── Main monitor loop ─────────────────────────────────────────────────────

    async def run(self) -> None:
        """Start the fill monitoring loop.

        Runs until risk_guard.disabled is True or stop() is called.
        Each tick processes all pending orders:
            - Skip already processed (dedup).
            - Check timeout → cancel if exceeded.
            - Poll for fill status with exponential backoff.
            - On fill: open position in PositionTracker.
            - On max_retry exhaustion: mark FAILED and log.
        """
        # ── Kill switch fast-path ─────────────────────────────────────────────
        if self._risk_guard is not None and self._risk_guard.disabled:
            log.warning("fill_monitor_startup_blocked_kill_switch")
            return

        self._running = True
        log.info("fill_monitor_loop_started")

        while self._running:
            # ── Kill switch check at top of every loop ────────────────────────
            if self._risk_guard is not None and self._risk_guard.disabled:
                log.warning("fill_monitor_loop_killed")
                self._running = False
                break

            await self._process_all_tracked()
            await asyncio.sleep(self._loop_interval_sec)

        log.info("fill_monitor_loop_stopped")

    async def stop(self) -> None:
        """Gracefully stop the monitor loop."""
        self._running = False

    # ── Internal processing ───────────────────────────────────────────────────

    async def _process_all_tracked(self) -> None:
        """Process all tracked orders in one loop tick.

        Uses snapshot to avoid mutating the dict during iteration.
        """
        # Snapshot keys — process outside the original dict
        order_ids = list(self._tracked.keys())

        for order_id in order_ids:
            # Kill switch check before each order
            if self._risk_guard is not None and self._risk_guard.disabled:
                return

            # Dedup guard: skip if already processed
            if order_id in self._processed_order_ids:
                self._tracked.pop(order_id, None)
                continue

            order = self._tracked.get(order_id)
            if order is None:
                continue

            await self._process_order(order)

    async def _process_order(self, order: TrackedOrder) -> None:
        """Process a single tracked order through its fill lifecycle.

        Args:
            order: The TrackedOrder to evaluate and advance.
        """
        cid = order.correlation_id

        # Already resolved via WS — confirm and open position
        if order.status == OrderStatus.FILLED:
            await self._confirm_fill(order)
            return

        # Timeout check
        elapsed = time.time() - order.registered_at
        if elapsed >= self._timeout_sec:
            await self._handle_timeout(order)
            return

        # Max retry exhausted — mark failed
        if order.retry_count >= self._max_retry:
            await self._mark_failed(order)
            return

        # Poll for status
        order.retry_count += 1
        backoff = 2 ** (order.retry_count - 1)  # 1s, 2s, 4s, 8s, 16s, ...

        log.debug(
            "fill_monitor_polling_order",
            order_id=order.order_id,
            market_id=order.market_id,
            retry_count=order.retry_count,
            max_retry=self._max_retry,
            backoff_s=backoff,
            correlation_id=cid,
        )

        # Exponential backoff wait — OUTSIDE any lock
        await asyncio.sleep(backoff)

        # Kill switch check after sleep
        if self._risk_guard is not None and self._risk_guard.disabled:
            return

        status_info = await self._executor.get_order_status(order.order_id, cid)
        if status_info is None:
            log.warning(
                "fill_monitor_poll_returned_none",
                order_id=order.order_id,
                retry_count=order.retry_count,
                correlation_id=cid,
            )
            return

        status = status_info.get("status", "")
        filled_size = float(status_info.get("filled_size", 0.0))
        avg_price = float(status_info.get("avg_price", order.price))

        if status == "filled" or round(filled_size, 6) >= order.size * 0.999:
            order.filled_size = round(filled_size, 6)
            order.avg_fill_price = round(avg_price, 6)
            order.status = OrderStatus.FILLED
            await self._confirm_fill(order)

        elif status == "partial":
            order.status = OrderStatus.PARTIAL

            # Compute incremental fill delta (avoid double counting)
            new_filled = round(filled_size, 6)
            prev_filled = order.filled_size

            if new_filled > prev_filled + 1e-9:
                delta = new_filled - prev_filled
                # Update VWAP
                if prev_filled > 0 and order.avg_fill_price > 0:
                    order.avg_fill_price = round(
                        (prev_filled * order.avg_fill_price + delta * avg_price) / new_filled,
                        6,
                    )
                else:
                    order.avg_fill_price = round(avg_price, 6)
                order.filled_size = new_filled

                log.info(
                    "fill_monitor_partial_fill",
                    order_id=order.order_id,
                    filled_size=order.filled_size,
                    fill_delta=round(delta, 6),
                    requested_size=order.size,
                    avg_fill_price=order.avg_fill_price,
                    correlation_id=cid,
                )

        elif status in ("rejected", "cancelled"):
            order.status = OrderStatus.CANCELLED
            self._mark_processed(order.order_id)
            self._tracked.pop(order.order_id, None)
            log.warning(
                "fill_monitor_order_rejected_or_cancelled",
                order_id=order.order_id,
                status=status,
                correlation_id=cid,
            )

    async def _confirm_fill(self, order: TrackedOrder) -> None:
        """Confirm a completed fill and open incremental position in PositionTracker.

        Uses last_confirmed_fill_size to avoid double-counting partial fills
        that were already reported in a previous call.

        Args:
            order: The fully-filled TrackedOrder.
        """
        cid = order.correlation_id

        # Compute incremental fill not yet reported to position_tracker
        fill_delta = round(order.filled_size - order.last_confirmed_fill_size, 6)

        if fill_delta <= 1e-9:
            # Already fully reported — just clean up
            self._mark_processed(order.order_id)
            self._tracked.pop(order.order_id, None)
            return

        # Open/add incremental position in tracker
        await self._tracker.open(
            market_id=order.market_id,
            side=order.side,
            size=fill_delta,
            entry_price=order.avg_fill_price,
            correlation_id=cid,
        )

        order.last_confirmed_fill_size = order.filled_size

        log.info(
            "fill_monitor_fill_confirmed",
            order_id=order.order_id,
            market_id=order.market_id,
            side=order.side,
            fill_delta=fill_delta,
            total_filled=order.filled_size,
            requested_size=order.size,
            avg_fill_price=order.avg_fill_price,
            retry_count=order.retry_count,
            correlation_id=cid,
        )

        self._mark_processed(order.order_id)
        self._tracked.pop(order.order_id, None)

    async def _handle_timeout(self, order: TrackedOrder) -> None:
        """Cancel a timed-out order and mark it CANCELLED.

        Args:
            order: The order that has exceeded order_timeout_sec.
        """
        cid = order.correlation_id
        order.status = OrderStatus.CANCELLED

        log.warning(
            "fill_monitor_order_timeout",
            order_id=order.order_id,
            market_id=order.market_id,
            elapsed_s=round(time.time() - order.registered_at, 2),
            timeout_s=self._timeout_sec,
            correlation_id=cid,
        )

        await self._executor.cancel_order(order.order_id, cid)

        self._mark_processed(order.order_id)
        self._tracked.pop(order.order_id, None)

    async def _mark_failed(self, order: TrackedOrder) -> None:
        """Mark an order FAILED after max_retry exhaustion.

        Args:
            order: The order that has exhausted all retry attempts.
        """
        cid = order.correlation_id
        order.status = OrderStatus.FAILED

        log.error(
            "fill_monitor_max_retry_exhausted",
            order_id=order.order_id,
            market_id=order.market_id,
            retry_count=order.retry_count,
            max_retry=self._max_retry,
            correlation_id=cid,
        )

        # Attempt final cancel to clean up exchange state
        await self._executor.cancel_order(order.order_id, cid)

        self._mark_processed(order.order_id)
        self._tracked.pop(order.order_id, None)

    def _mark_processed(self, order_id: str) -> None:
        """Add order_id to the processed set (permanent dedup record)."""
        self._processed_order_ids.add(order_id)

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Return structured monitoring state for HealthMonitor."""
        return {
            "tracked_orders": len(self._tracked),
            "processed_order_count": len(self._processed_order_ids),
            "running": self._running,
        }
