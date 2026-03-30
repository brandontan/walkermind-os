"""Phase 10.2 — Reconciliation: Order ↔ fill reconciliation and ghost-position guard.

Matches every submitted order against the fills received from the exchange.
Detects and logs:
    - partial fills  — order filled for less than the full requested size
    - missed fills   — order submitted but no fill received within timeout
    - duplicate fills — same order_id filled more than once (exchange glitch)

Ghost-position guard:
    After reconciliation, open_position_ids contains only order_ids that are
    confirmed open (submitted but not yet fully filled or cancelled).  Any
    order_id that appears in fills but is *not* in submissions is flagged as a
    ghost (possible API mismatch or replay).

Alerts are triggered (via structlog WARNING) when:
    - slippage > threshold
    - fill mismatch (size discrepancy > mismatch_tolerance_usd)
    - missing fill (MISSED status)
    - latency spike > latency_threshold_ms

Usage::

    recon = Reconciliation(mismatch_tolerance_usd=0.01, fill_timeout_sec=30.0)
    recon.register_order(order_id="0xabc", market_id="0xdef",
                         side="YES", expected_price=0.62, requested_size=100.0)
    recon.record_fill(order_id="0xabc", filled_size=100.0, executed_price=0.625)
    report = recon.reconcile()
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import structlog

log = structlog.get_logger()

# ── Constants ─────────────────────────────────────────────────────────────────

_DEFAULT_MISMATCH_TOLERANCE_USD: float = 0.01   # acceptable fill-size delta
_DEFAULT_FILL_TIMEOUT_SEC: float = 30.0         # time until order is flagged missed
_DEFAULT_LATENCY_THRESHOLD_MS: float = 1_000.0  # alert if fill takes > 1 s
_DEFAULT_SLIPPAGE_THRESHOLD_BPS: float = 50.0   # alert if slippage > 50 bps


# ── Internal state ────────────────────────────────────────────────────────────

class _ReconStatus(str, Enum):
    OPEN      = "open"       # submitted, awaiting fill
    MATCHED   = "matched"    # full fill received within tolerance
    PARTIAL   = "partial"    # partially filled
    MISSED    = "missed"     # timeout — no fill received
    DUPLICATE = "duplicate"  # more than one fill event received


@dataclass
class _OrderEntry:
    """Internal tracking entry for a single submitted order."""
    order_id: str
    market_id: str
    side: str
    expected_price: float
    requested_size: float
    submitted_at: float = field(default_factory=time.time)
    fills: list[dict] = field(default_factory=list)  # each: {size, price, ts}
    status: _ReconStatus = _ReconStatus.OPEN


# ── Public result types ───────────────────────────────────────────────────────

@dataclass
class FillMatch:
    """Result for a single reconciled order.

    Attributes:
        order_id: Exchange order ID.
        market_id: Polymarket condition ID.
        side: "YES" | "NO".
        expected_price: Price at submission.
        executed_price: VWAP of fills received (0.0 if no fill).
        requested_size: USD size requested.
        filled_size: USD size confirmed filled.
        slippage_bps: (executed - expected) / expected * 10 000.
        fill_latency_ms: ms from submission to first fill.
        status: Reconciliation outcome.
        discrepancy_usd: abs(filled_size - requested_size).
        is_ghost: True if fill arrived for an unknown order_id.
    """
    order_id: str
    market_id: str
    side: str
    expected_price: float
    executed_price: float
    requested_size: float
    filled_size: float
    slippage_bps: float
    fill_latency_ms: float
    status: _ReconStatus
    discrepancy_usd: float
    is_ghost: bool = False


@dataclass
class ReconciliationReport:
    """Summary of a full reconciliation pass.

    Attributes:
        total_orders: Total submitted orders in this session.
        matched: Orders fully matched within tolerance.
        partial: Orders partially filled.
        missed: Orders with no fill received within timeout.
        duplicate: Orders with duplicate fill events.
        ghost_fills: Fill events for unknown order_ids.
        has_ghost_positions: True if any ghost fills detected.
        matches: Per-order :class:`FillMatch` list.
    """
    total_orders: int
    matched: int
    partial: int
    missed: int
    duplicate: int
    ghost_fills: int
    has_ghost_positions: bool
    matches: list[FillMatch]


# ── Reconciliation ────────────────────────────────────────────────────────────

class Reconciliation:
    """Matches submitted orders against received fills.

    Thread-safety: single asyncio event loop only.
    All public methods are synchronous (in-memory).

    Args:
        mismatch_tolerance_usd: Maximum acceptable fill-size delta (USD).
        fill_timeout_sec: Seconds after which an unfilled order is MISSED.
        latency_threshold_ms: Alert threshold for fill latency (ms).
        slippage_threshold_bps: Alert threshold for per-trade slippage (bps).
    """

    def __init__(
        self,
        mismatch_tolerance_usd: float = _DEFAULT_MISMATCH_TOLERANCE_USD,
        fill_timeout_sec: float = _DEFAULT_FILL_TIMEOUT_SEC,
        latency_threshold_ms: float = _DEFAULT_LATENCY_THRESHOLD_MS,
        slippage_threshold_bps: float = _DEFAULT_SLIPPAGE_THRESHOLD_BPS,
    ) -> None:
        self._tolerance = mismatch_tolerance_usd
        self._timeout = fill_timeout_sec
        self._latency_threshold = latency_threshold_ms
        self._slippage_threshold = slippage_threshold_bps
        self._orders: dict[str, _OrderEntry] = {}
        self._ghost_fill_ids: list[str] = []

        log.info(
            "reconciliation_initialized",
            mismatch_tolerance_usd=mismatch_tolerance_usd,
            fill_timeout_sec=fill_timeout_sec,
            latency_threshold_ms=latency_threshold_ms,
            slippage_threshold_bps=slippage_threshold_bps,
        )

    # ── Order registration ────────────────────────────────────────────────────

    def register_order(
        self,
        order_id: str,
        market_id: str,
        side: str,
        expected_price: float,
        requested_size: float,
    ) -> None:
        """Register a submitted order for reconciliation tracking.

        Args:
            order_id: Exchange-assigned order ID.
            market_id: Polymarket condition ID.
            side: "YES" | "NO".
            expected_price: Limit price submitted.
            requested_size: Order size in USD.
        """
        if order_id in self._orders:
            log.warning(
                "reconciliation_duplicate_registration",
                order_id=order_id,
            )
            return

        self._orders[order_id] = _OrderEntry(
            order_id=order_id,
            market_id=market_id,
            side=side,
            expected_price=expected_price,
            requested_size=requested_size,
        )
        log.debug(
            "reconciliation_order_registered",
            order_id=order_id,
            market_id=market_id,
            side=side,
            expected_price=expected_price,
            requested_size=requested_size,
        )

    # ── Fill ingestion ────────────────────────────────────────────────────────

    def record_fill(
        self,
        order_id: str,
        filled_size: float,
        executed_price: float,
        fill_timestamp: Optional[float] = None,
    ) -> None:
        """Record a fill event received from the exchange.

        Handles partial fills by accumulating fill events.  A second fill
        for the same order_id after MATCHED status is flagged as DUPLICATE.

        Args:
            order_id: Exchange-assigned order ID.
            filled_size: USD amount filled in this event.
            executed_price: Price at which this fill occurred.
            fill_timestamp: Unix timestamp of fill (defaults to now).
        """
        ts = fill_timestamp or time.time()

        if order_id not in self._orders:
            # Ghost fill — arrived for an order we never submitted
            self._ghost_fill_ids.append(order_id)
            log.error(
                "reconciliation_ghost_fill",
                order_id=order_id,
                filled_size=filled_size,
                executed_price=executed_price,
            )
            return

        entry = self._orders[order_id]

        if entry.status == _ReconStatus.MATCHED:
            entry.status = _ReconStatus.DUPLICATE
            log.error(
                "reconciliation_duplicate_fill",
                order_id=order_id,
                market_id=entry.market_id,
                existing_fills=len(entry.fills),
            )

        entry.fills.append({
            "size": filled_size,
            "price": executed_price,
            "ts": ts,
        })

        log.debug(
            "reconciliation_fill_recorded",
            order_id=order_id,
            market_id=entry.market_id,
            filled_size=filled_size,
            executed_price=executed_price,
            fill_count=len(entry.fills),
        )

    # ── Reconciliation pass ───────────────────────────────────────────────────

    def reconcile(self, now: Optional[float] = None) -> ReconciliationReport:
        """Execute a reconciliation pass over all registered orders.

        Classifies each order as MATCHED / PARTIAL / MISSED / DUPLICATE,
        computes per-order slippage and latency, and fires alerts where needed.

        Args:
            now: Override current time (for testing).

        Returns:
            :class:`ReconciliationReport` with per-order detail.
        """
        current_time = now or time.time()
        matches: list[FillMatch] = []
        count_matched = count_partial = count_missed = count_dup = 0

        for entry in self._orders.values():
            match = self._classify(entry, current_time)
            matches.append(match)
            if match.status == _ReconStatus.MATCHED:
                count_matched += 1
            elif match.status == _ReconStatus.PARTIAL:
                count_partial += 1
            elif match.status == _ReconStatus.MISSED:
                count_missed += 1
            elif match.status == _ReconStatus.DUPLICATE:
                count_dup += 1

        ghost_count = len(self._ghost_fill_ids)

        report = ReconciliationReport(
            total_orders=len(self._orders),
            matched=count_matched,
            partial=count_partial,
            missed=count_missed,
            duplicate=count_dup,
            ghost_fills=ghost_count,
            has_ghost_positions=ghost_count > 0,
            matches=matches,
        )

        log.info(
            "reconciliation_complete",
            total_orders=report.total_orders,
            matched=report.matched,
            partial=report.partial,
            missed=report.missed,
            duplicate=report.duplicate,
            ghost_fills=report.ghost_fills,
            has_ghost_positions=report.has_ghost_positions,
        )

        if report.missed > 0:
            log.warning(
                "reconciliation_missed_fills_alert",
                missed_count=report.missed,
            )
        if report.has_ghost_positions:
            log.error(
                "reconciliation_ghost_positions_alert",
                ghost_count=ghost_count,
                ghost_order_ids=self._ghost_fill_ids,
            )

        return report

    # ── Open positions snapshot ───────────────────────────────────────────────

    def open_order_ids(self) -> list[str]:
        """Return order IDs that are still OPEN (submitted, no fill yet).

        These represent potentially open positions awaiting fill confirmation.
        """
        return [
            oid
            for oid, entry in self._orders.items()
            if entry.status == _ReconStatus.OPEN
        ]

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _classify(self, entry: _OrderEntry, now: float) -> FillMatch:
        """Classify a single order entry and build its :class:`FillMatch`."""
        total_filled = sum(f["size"] for f in entry.fills)
        discrepancy = abs(total_filled - entry.requested_size)

        # VWAP of all fill events
        if total_filled > 0:
            vwap = sum(f["size"] * f["price"] for f in entry.fills) / total_filled
        else:
            vwap = 0.0

        # Latency: submission → first fill
        if entry.fills:
            first_fill_ts = entry.fills[0]["ts"]
            latency_ms = (first_fill_ts - entry.submitted_at) * 1_000.0
        else:
            latency_ms = 0.0

        # Slippage
        if entry.expected_price > 1e-9 and vwap > 0:
            slippage_bps = (
                (vwap - entry.expected_price) / entry.expected_price * 10_000.0
            )
        else:
            slippage_bps = 0.0

        # Determine status
        if entry.status == _ReconStatus.DUPLICATE:
            status = _ReconStatus.DUPLICATE
        elif not entry.fills:
            # No fills received — check timeout
            age = now - entry.submitted_at
            if age >= self._timeout:
                entry.status = _ReconStatus.MISSED
                status = _ReconStatus.MISSED
            else:
                status = _ReconStatus.OPEN
        elif discrepancy <= self._tolerance:
            entry.status = _ReconStatus.MATCHED
            status = _ReconStatus.MATCHED
        else:
            entry.status = _ReconStatus.PARTIAL
            status = _ReconStatus.PARTIAL

        # ── Alerts ───────────────────────────────────────────────────────────
        if status == _ReconStatus.MISSED:
            log.warning(
                "reconciliation_fill_missing",
                order_id=entry.order_id,
                market_id=entry.market_id,
                side=entry.side,
                requested_size=entry.requested_size,
                age_sec=round(now - entry.submitted_at, 1),
            )
        elif status == _ReconStatus.PARTIAL:
            log.warning(
                "reconciliation_fill_partial",
                order_id=entry.order_id,
                market_id=entry.market_id,
                requested_size=entry.requested_size,
                filled_size=round(total_filled, 4),
                discrepancy_usd=round(discrepancy, 4),
            )
        if abs(slippage_bps) > self._slippage_threshold:
            log.warning(
                "reconciliation_slippage_alert",
                order_id=entry.order_id,
                market_id=entry.market_id,
                slippage_bps=round(slippage_bps, 2),
                threshold_bps=self._slippage_threshold,
            )
        if latency_ms > self._latency_threshold and latency_ms > 0:
            log.warning(
                "reconciliation_latency_spike",
                order_id=entry.order_id,
                fill_latency_ms=round(latency_ms, 1),
                threshold_ms=self._latency_threshold,
            )

        return FillMatch(
            order_id=entry.order_id,
            market_id=entry.market_id,
            side=entry.side,
            expected_price=entry.expected_price,
            executed_price=round(vwap, 6),
            requested_size=entry.requested_size,
            filled_size=round(total_filled, 4),
            slippage_bps=round(slippage_bps, 2),
            fill_latency_ms=round(latency_ms, 2),
            status=status,
            discrepancy_usd=round(discrepancy, 4),
            is_ghost=False,
        )
