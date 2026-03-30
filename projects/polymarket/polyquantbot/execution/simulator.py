"""Phase 10.2 — ExecutionSimulator: PAPER_LIVE_SIM mode.

Simulates order execution using live orderbook data without risking real
capital.  Two sub-modes are supported:

    PAPER_LIVE_SIM  — Uses the real orderbook snapshot to estimate the fill
                      price and size that would have been achieved.  Orders
                      are NOT sent to the exchange.

    REAL_API        — Actually sends orders to the exchange (pass
                      ``send_real_orders=True``).  Intended for controlled
                      live validation with strict risk limits.

Slippage simulation:
    The simulator walks the orderbook levels to compute the VWAP that a given
    order size would achieve, then records the simulated fill in the
    :class:`~execution.fill_tracker.FillTracker`.

Latency simulation:
    Real network RTT is not simulated; instead the latency recorded in the
    FillRecord is the wall-clock time taken to process the order locally.

Usage::

    sim = ExecutionSimulator(
        fill_tracker=tracker,
        slippage_threshold_bps=50.0,
        send_real_orders=False,
    )
    result = await sim.execute(
        order_id="0xabc",
        market_id="0xdef",
        side="YES",
        expected_price=0.62,
        size_usd=100.0,
        orderbook={"asks": [[0.62, 200.0], [0.63, 100.0]], "bids": []},
    )
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import structlog

from .fill_tracker import FillTracker, FillRecord

log = structlog.get_logger()

# ── Constants ─────────────────────────────────────────────────────────────────

_DEFAULT_SLIPPAGE_THRESHOLD_BPS: float = 50.0
_DEFAULT_LATENCY_THRESHOLD_MS: float = 1_000.0


# ── Result types ──────────────────────────────────────────────────────────────

class SimMode(str, Enum):
    """Simulator execution mode."""
    PAPER_LIVE_SIM = "PAPER_LIVE_SIM"   # simulate using orderbook, no real orders
    REAL_API       = "REAL_API"         # send actual orders (requires executor)


@dataclass
class SimResult:
    """Result of a single simulated execution.

    Attributes:
        order_id: Assigned order ID (generated or exchange-assigned).
        mode: Simulator mode used.
        expected_price: Limit price at submission.
        simulated_price: Estimated fill price from orderbook walk.
        filled_size: USD amount filled (partial if insufficient liquidity).
        slippage_bps: (simulated - expected) / expected * 10 000.
        latency_ms: Wall-clock latency of the simulation step.
        success: True if the order was (simulated as) filled.
        reason: Rejection or partial-fill reason (empty on full fill).
        fill_record: Associated :class:`FillRecord` from FillTracker.
    """
    order_id: str
    mode: SimMode
    expected_price: float
    simulated_price: float
    filled_size: float
    slippage_bps: float
    latency_ms: float
    success: bool
    reason: str
    fill_record: Optional[FillRecord]


# ── ExecutionSimulator ────────────────────────────────────────────────────────

class ExecutionSimulator:
    """Simulates order execution against a live orderbook snapshot.

    The simulator is designed for PAPER_LIVE_SIM validation: orders are
    *never* sent to the exchange unless ``send_real_orders=True`` and an
    ``executor`` is provided.

    Args:
        fill_tracker: :class:`FillTracker` instance to record simulated fills.
        slippage_threshold_bps: Alert if simulated slippage exceeds this.
        latency_threshold_ms: Alert if fill latency exceeds this.
        send_real_orders: When True, forward orders to ``executor``.
        executor: Optional live executor (required when send_real_orders=True).
    """

    def __init__(
        self,
        fill_tracker: FillTracker,
        slippage_threshold_bps: float = _DEFAULT_SLIPPAGE_THRESHOLD_BPS,
        latency_threshold_ms: float = _DEFAULT_LATENCY_THRESHOLD_MS,
        send_real_orders: bool = False,
        executor: Optional[object] = None,
    ) -> None:
        self._fill_tracker = fill_tracker
        self._slippage_threshold = slippage_threshold_bps
        self._latency_threshold = latency_threshold_ms
        self._send_real_orders = send_real_orders
        self._executor = executor

        mode = SimMode.REAL_API if send_real_orders else SimMode.PAPER_LIVE_SIM

        if send_real_orders and executor is None:
            raise ValueError(
                "ExecutionSimulator: executor must be provided when "
                "send_real_orders=True"
            )

        log.info(
            "execution_simulator_initialized",
            mode=mode,
            slippage_threshold_bps=slippage_threshold_bps,
            latency_threshold_ms=latency_threshold_ms,
            send_real_orders=send_real_orders,
        )
        self._mode = mode

    # ── Main entry point ──────────────────────────────────────────────────────

    async def execute(
        self,
        market_id: str,
        side: str,
        expected_price: float,
        size_usd: float,
        orderbook: Optional[dict] = None,
        order_id: Optional[str] = None,
    ) -> SimResult:
        """Simulate or execute an order.

        In PAPER_LIVE_SIM mode:
            - Walks the orderbook to compute simulated fill price and size.
            - Registers the submission and fill in the FillTracker.
            - Never sends anything to the exchange.

        In REAL_API mode:
            - Delegates to the real executor.
            - Records the actual fill in the FillTracker.

        Args:
            market_id: Polymarket condition ID.
            side: "YES" | "NO".
            expected_price: Limit price (0–1).
            size_usd: Order size in USD.
            orderbook: Current orderbook snapshot:
                       ``{"asks": [[price, size_usd], ...],
                          "bids": [[price, size_usd], ...]}``.
                       Required for PAPER_LIVE_SIM mode.
            order_id: Override generated order ID.

        Returns:
            :class:`SimResult` with execution outcome.
        """
        oid = order_id or f"sim-{uuid.uuid4().hex[:12]}"
        t_start = time.time()

        if self._send_real_orders:
            return await self._execute_real(
                order_id=oid,
                market_id=market_id,
                side=side,
                expected_price=expected_price,
                size_usd=size_usd,
                t_start=t_start,
            )

        return self._simulate(
            order_id=oid,
            market_id=market_id,
            side=side,
            expected_price=expected_price,
            size_usd=size_usd,
            orderbook=orderbook,
            t_start=t_start,
        )

    # ── Paper simulation ──────────────────────────────────────────────────────

    def _simulate(
        self,
        order_id: str,
        market_id: str,
        side: str,
        expected_price: float,
        size_usd: float,
        orderbook: Optional[dict],
        t_start: float,
    ) -> SimResult:
        """Walk the orderbook to compute simulated fill price and size."""
        # Register submission
        self._fill_tracker.record_submission(
            order_id=order_id,
            market_id=market_id,
            side=side,
            expected_price=expected_price,
            size_usd=size_usd,
        )

        if not orderbook:
            # No orderbook data — treat as missed fill
            self._fill_tracker.mark_missed(order_id)
            latency_ms = (time.time() - t_start) * 1_000.0
            log.warning(
                "simulator_no_orderbook",
                order_id=order_id,
                market_id=market_id,
            )
            return SimResult(
                order_id=order_id,
                mode=self._mode,
                expected_price=expected_price,
                simulated_price=0.0,
                filled_size=0.0,
                slippage_bps=0.0,
                latency_ms=round(latency_ms, 2),
                success=False,
                reason="no_orderbook_data",
                fill_record=self._fill_tracker.get_record(order_id),
            )

        # Walk the relevant side of the orderbook
        levels = _get_levels(orderbook, side)
        simulated_price, filled_size = _walk_levels(levels, size_usd, expected_price)

        latency_ms = (time.time() - t_start) * 1_000.0
        partial = filled_size < size_usd * 0.999   # allow 0.1% rounding

        if filled_size <= 0:
            self._fill_tracker.mark_missed(order_id)
            log.warning(
                "simulator_zero_fill",
                order_id=order_id,
                market_id=market_id,
                side=side,
                expected_price=expected_price,
            )
            return SimResult(
                order_id=order_id,
                mode=self._mode,
                expected_price=expected_price,
                simulated_price=0.0,
                filled_size=0.0,
                slippage_bps=0.0,
                latency_ms=round(latency_ms, 2),
                success=False,
                reason="insufficient_liquidity",
                fill_record=self._fill_tracker.get_record(order_id),
            )

        fill_record = self._fill_tracker.record_fill(
            order_id=order_id,
            executed_price=simulated_price,
            filled_size=filled_size,
            partial=partial,
        )

        slippage_bps = fill_record.slippage_bps

        reason = "partial_fill" if partial else ""

        log.info(
            "simulator_paper_fill",
            order_id=order_id,
            market_id=market_id,
            side=side,
            expected_price=expected_price,
            simulated_price=round(simulated_price, 6),
            filled_size=round(filled_size, 4),
            slippage_bps=round(slippage_bps, 2),
            latency_ms=round(latency_ms, 2),
            partial=partial,
        )

        return SimResult(
            order_id=order_id,
            mode=self._mode,
            expected_price=expected_price,
            simulated_price=round(simulated_price, 6),
            filled_size=round(filled_size, 4),
            slippage_bps=round(slippage_bps, 2),
            latency_ms=round(latency_ms, 2),
            success=True,
            reason=reason,
            fill_record=fill_record,
        )

    # ── Real execution path ───────────────────────────────────────────────────

    async def _execute_real(
        self,
        order_id: str,
        market_id: str,
        side: str,
        expected_price: float,
        size_usd: float,
        t_start: float,
    ) -> SimResult:
        """Forward the order to the real executor and record the actual fill."""
        from ..phase7.core.execution.live_executor import ExecutionRequest

        self._fill_tracker.record_submission(
            order_id=order_id,
            market_id=market_id,
            side=side,
            expected_price=expected_price,
            size_usd=size_usd,
        )

        try:
            request = ExecutionRequest(
                market_id=market_id,
                side=side,
                price=expected_price,
                size=size_usd,
                correlation_id=order_id,
            )
            result = await self._executor.execute(request)  # type: ignore[union-attr]
        except Exception as exc:
            latency_ms = (time.time() - t_start) * 1_000.0
            self._fill_tracker.mark_missed(order_id)
            log.error(
                "simulator_real_execution_error",
                order_id=order_id,
                error=str(exc),
            )
            return SimResult(
                order_id=order_id,
                mode=self._mode,
                expected_price=expected_price,
                simulated_price=0.0,
                filled_size=0.0,
                slippage_bps=0.0,
                latency_ms=round(latency_ms, 2),
                success=False,
                reason=f"executor_error:{exc}",
                fill_record=self._fill_tracker.get_record(order_id),
            )

        latency_ms = (time.time() - t_start) * 1_000.0
        actual_price = getattr(result, "avg_price", expected_price) or expected_price
        actual_size = getattr(result, "filled_size", size_usd) or size_usd
        partial = actual_size < size_usd * 0.999

        fill_record = self._fill_tracker.record_fill(
            order_id=order_id,
            executed_price=actual_price,
            filled_size=actual_size,
            partial=partial,
        )

        log.info(
            "simulator_real_fill",
            order_id=order_id,
            market_id=market_id,
            side=side,
            expected_price=expected_price,
            actual_price=actual_price,
            actual_size=actual_size,
            latency_ms=round(latency_ms, 2),
        )

        return SimResult(
            order_id=order_id,
            mode=self._mode,
            expected_price=expected_price,
            simulated_price=round(actual_price, 6),
            filled_size=round(actual_size, 4),
            slippage_bps=fill_record.slippage_bps,
            latency_ms=round(latency_ms, 2),
            success=True,
            reason="partial_fill" if partial else "",
            fill_record=fill_record,
        )


# ── Orderbook helpers ─────────────────────────────────────────────────────────

def _get_levels(orderbook: dict, side: str) -> list[list[float]]:
    """Return the relevant orderbook levels for a given order side.

    For a BUY (YES/NO) order we consume ASK levels (offers to sell).
    The orderbook is expected in the form::

        {"asks": [[price, size_usd], ...], "bids": [[price, size_usd], ...]}

    Asks must be sorted ascending by price; bids descending.
    """
    key = "asks"   # buying → walk asks
    levels = orderbook.get(key, [])
    if not isinstance(levels, list):
        return []
    return levels


def _walk_levels(
    levels: list[list[float]],
    size_usd: float,
    limit_price: float,
) -> tuple[float, float]:
    """Walk orderbook levels to compute VWAP fill price and filled size.

    Stops consuming levels when the order is fully filled or the next ask
    price exceeds the limit price.

    Args:
        levels: List of [price, available_size_usd] sorted ascending by price.
        size_usd: Order size to fill in USD.
        limit_price: Maximum price we are willing to pay.

    Returns:
        Tuple of (vwap_price, total_filled_usd).
        vwap_price is 0.0 if nothing was filled.
    """
    remaining = size_usd
    total_cost = 0.0
    total_filled = 0.0

    for level in levels:
        if len(level) < 2:
            continue
        level_price: float = float(level[0])
        level_size: float = float(level[1])

        if level_price > limit_price:
            # Price crosses our limit — stop
            break

        take = min(remaining, level_size)
        total_cost += take * level_price
        total_filled += take
        remaining -= take

        if remaining <= 1e-9:
            break

    if total_filled <= 0:
        return 0.0, 0.0

    vwap = total_cost / total_filled
    return vwap, total_filled
