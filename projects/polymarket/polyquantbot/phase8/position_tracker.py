"""Phase 8 — PositionTracker: Locked position state, no duplicate market_id.

Design guarantees:
    - asyncio.Lock serialises ALL state mutations.
    - Lock is NEVER held during long I/O (snapshot-then-process pattern).
    - Duplicate market_id opens are rejected with an explicit error log.
    - State transitions are enforced: OPEN → CLOSED only.
    - All snapshots are shallow copies — callers cannot mutate internal state.
    - force_close_all() is called by RiskGuard on kill switch; it returns
      a count so callers can verify all positions were processed.

State machine per position:
    open()  → PositionState.OPEN
    close() → PositionState.CLOSED  (idempotent: skips if already CLOSED)

Usage::

    tracker = PositionTracker(risk_guard=guard)

    # Open a position:
    ok = await tracker.open("0xabc...", side="YES", size=50.0, entry_price=0.62)

    # Close a position:
    ok = await tracker.close("0xabc...", exit_price=0.70, realised_pnl=4.0)

    # Snapshot all open positions (no lock held during iteration):
    for pos in await tracker.open_positions_snapshot():
        print(pos.market_id, pos.size)
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


# ── State enum ────────────────────────────────────────────────────────────────

class PositionState(str, Enum):
    """Lifecycle states for a tracked position."""
    OPEN = "OPEN"
    CLOSED = "CLOSED"


# ── PositionRecord ─────────────────────────────────────────────────────────────

@dataclass
class PositionRecord:
    """Immutable snapshot of a single position.

    All numeric fields are rounded to 6 decimal places on creation to
    prevent floating-point precision mismatches in comparisons.

    Attributes:
        position_id: Unique internal ID.
        market_id: Polymarket condition ID.
        side: "YES" | "NO".
        size: Position size in USD.
        entry_price: Price at which position was opened.
        state: Current lifecycle state.
        opened_at: Unix timestamp when position was opened.
        closed_at: Unix timestamp when position was closed (None if still open).
        exit_price: Fill price at close (None if still open).
        realised_pnl: Realised profit/loss in USD at close (None if still open).
        close_reason: Why the position was closed (None if still open).
    """

    position_id: str
    market_id: str
    side: str
    size: float
    entry_price: float
    state: PositionState = PositionState.OPEN
    opened_at: float = field(default_factory=time.time)
    closed_at: Optional[float] = None
    exit_price: Optional[float] = None
    realised_pnl: Optional[float] = None
    close_reason: Optional[str] = None

    def __post_init__(self) -> None:
        """Round floats to prevent precision drift."""
        self.size = round(self.size, 6)
        self.entry_price = round(self.entry_price, 6)
        if self.exit_price is not None:
            self.exit_price = round(self.exit_price, 6)
        if self.realised_pnl is not None:
            self.realised_pnl = round(self.realised_pnl, 6)

    def is_open(self) -> bool:
        """Return True if position is in OPEN state."""
        return self.state == PositionState.OPEN

    def copy(self) -> "PositionRecord":
        """Return a shallow copy — callers cannot mutate internal state."""
        return PositionRecord(
            position_id=self.position_id,
            market_id=self.market_id,
            side=self.side,
            size=self.size,
            entry_price=self.entry_price,
            state=self.state,
            opened_at=self.opened_at,
            closed_at=self.closed_at,
            exit_price=self.exit_price,
            realised_pnl=self.realised_pnl,
            close_reason=self.close_reason,
        )


# ── PositionTracker ───────────────────────────────────────────────────────────

class PositionTracker:
    """Thread-safe (asyncio) position state store for Phase 8.

    Key invariants:
        1. Only one OPEN position per market_id at any time.
        2. All mutations (open, close, update) are performed under _lock.
        3. The lock is NEVER held during external I/O — use snapshot pattern.
        4. Snapshots returned to callers are copies, not references.
        5. risk_guard.disabled fast-path exits all entry points.
    """

    def __init__(self, risk_guard=None) -> None:
        """Initialise the tracker.

        Args:
            risk_guard: RiskGuard instance. If provided, disabled flag is
                checked at every entry point.
        """
        self._lock = asyncio.Lock()
        self._positions: dict[str, PositionRecord] = {}  # market_id → record
        self._closed_positions: list[PositionRecord] = []
        self._risk_guard = risk_guard

        log.info("position_tracker_initialized")

    # ── Public API ────────────────────────────────────────────────────────────

    async def open(
        self,
        market_id: str,
        side: str,
        size: float,
        entry_price: float,
        correlation_id: Optional[str] = None,
    ) -> bool:
        """Open a new position for market_id.

        Rejects if:
            - risk_guard.disabled is True (kill switch fast-path).
            - A position for market_id is already OPEN (duplicate guard).
            - size <= 0 or entry_price <= 0.

        Args:
            market_id: Polymarket condition ID.
            side: "YES" | "NO".
            size: Position size in USD.
            entry_price: Limit price at which order was filled.
            correlation_id: Optional request ID for log tracing.

        Returns:
            True if position was opened. False if rejected.
        """
        cid = correlation_id or str(uuid.uuid4())

        # ── Kill switch fast-path ─────────────────────────────────────────────
        if self._risk_guard is not None and self._risk_guard.disabled:
            log.warning(
                "position_open_blocked_kill_switch",
                market_id=market_id,
                correlation_id=cid,
            )
            return False

        # ── Input validation (outside lock — no mutation) ─────────────────────
        if size <= 0 or entry_price <= 0:
            log.error(
                "position_open_invalid_params",
                market_id=market_id,
                size=size,
                entry_price=entry_price,
                correlation_id=cid,
            )
            return False
        if side not in ("YES", "NO"):
            log.error(
                "position_open_invalid_side",
                market_id=market_id,
                side=side,
                correlation_id=cid,
            )
            return False

        # ── Critical section: duplicate check + insert ────────────────────────
        async with self._lock:
            existing = self._positions.get(market_id)
            if existing is not None and existing.state == PositionState.OPEN:
                log.error(
                    "position_open_duplicate_rejected",
                    market_id=market_id,
                    existing_position_id=existing.position_id,
                    existing_size=existing.size,
                    correlation_id=cid,
                )
                return False

            record = PositionRecord(
                position_id=str(uuid.uuid4()),
                market_id=market_id,
                side=side,
                size=size,
                entry_price=entry_price,
            )
            self._positions[market_id] = record

        log.info(
            "position_opened",
            position_id=record.position_id,
            market_id=market_id,
            side=side,
            size=record.size,
            entry_price=record.entry_price,
            correlation_id=cid,
        )
        return True

    async def close(
        self,
        market_id: str,
        exit_price: float,
        realised_pnl: float,
        close_reason: str = "normal",
        correlation_id: Optional[str] = None,
    ) -> bool:
        """Close an OPEN position for market_id.

        Idempotent: if position is already CLOSED, logs a warning and returns False.
        Skips with a warning if market_id has no tracked position.

        Args:
            market_id: Polymarket condition ID.
            exit_price: Execution price at close.
            realised_pnl: Profit/loss realised at close (USD).
            close_reason: Descriptive close reason for audit log.
            correlation_id: Optional request ID for log tracing.

        Returns:
            True if position was closed. False if skipped.
        """
        cid = correlation_id or str(uuid.uuid4())

        # ── Kill switch fast-path (allow close even when disabled for cleanup) ─
        # NOTE: we intentionally do NOT block closes on kill switch — the kill
        # switch cleanup path calls close() to unwind positions.

        # ── Critical section: state check + update ────────────────────────────
        async with self._lock:
            record = self._positions.get(market_id)

            if record is None:
                log.warning(
                    "position_close_not_found",
                    market_id=market_id,
                    correlation_id=cid,
                )
                return False

            if record.state == PositionState.CLOSED:
                log.warning(
                    "position_close_already_closed",
                    market_id=market_id,
                    position_id=record.position_id,
                    correlation_id=cid,
                )
                return False

            # Mutate under lock — snapshot the record AFTER mutation
            record.state = PositionState.CLOSED
            record.closed_at = time.time()
            record.exit_price = round(exit_price, 6)
            record.realised_pnl = round(realised_pnl, 6)
            record.close_reason = close_reason

            closed_copy = record.copy()
            # Move to history — remove from active positions map
            del self._positions[market_id]
            self._closed_positions.append(closed_copy)

        log.info(
            "position_closed",
            position_id=closed_copy.position_id,
            market_id=market_id,
            close_reason=close_reason,
            exit_price=closed_copy.exit_price,
            realised_pnl=closed_copy.realised_pnl,
            correlation_id=cid,
        )
        return True

    async def get(self, market_id: str) -> Optional[PositionRecord]:
        """Return a copy of the current record for market_id, or None.

        Returns a snapshot copy — callers cannot mutate tracked state.
        """
        async with self._lock:
            record = self._positions.get(market_id)
            return record.copy() if record is not None else None

    async def open_positions_snapshot(self) -> list[PositionRecord]:
        """Return a snapshot list of all currently OPEN positions.

        Lock is held only for the copy step — NOT during any processing.
        The returned list contains independent copies.
        """
        async with self._lock:
            snapshot = [r.copy() for r in self._positions.values() if r.state == PositionState.OPEN]
        return snapshot

    async def total_exposure(self) -> float:
        """Return total USD size across all OPEN positions.

        Lock held only for summation of the snapshot.
        """
        async with self._lock:
            return sum(r.size for r in self._positions.values() if r.state == PositionState.OPEN)

    async def force_close_all(self, reason: str) -> int:
        """Force-close all OPEN positions. Called by RiskGuard on kill switch.

        Uses snapshot pattern:
            1. Snapshot market_ids under lock.
            2. Release lock.
            3. Call close() for each — close() re-acquires lock per call.

        Args:
            reason: Audit log reason for all closes.

        Returns:
            Number of positions closed.
        """
        # Step 1: snapshot under lock
        async with self._lock:
            open_market_ids = [
                mid for mid, r in self._positions.items()
                if r.state == PositionState.OPEN
            ]

        # Step 2: close each outside lock
        closed_count = 0
        for market_id in open_market_ids:
            ok = await self.close(
                market_id=market_id,
                exit_price=0.0,   # price not known — emergency close
                realised_pnl=0.0,
                close_reason=reason,
                correlation_id=f"force_close:{reason}",
            )
            if ok:
                closed_count += 1

        log.warning(
            "force_close_all_complete",
            closed_count=closed_count,
            total_open_found=len(open_market_ids),
            reason=reason,
        )
        return closed_count

    # ── Diagnostics ───────────────────────────────────────────────────────────

    async def summary(self) -> dict:
        """Return a structured summary for health monitoring."""
        async with self._lock:
            open_count = sum(1 for r in self._positions.values() if r.state == PositionState.OPEN)
            total_size = sum(r.size for r in self._positions.values() if r.state == PositionState.OPEN)

        return {
            "open_positions": open_count,
            "total_exposure_usd": round(total_size, 2),
            "closed_positions_history": len(self._closed_positions),
        }
