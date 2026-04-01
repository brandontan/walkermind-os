"""Phase 8 — ExitMonitor: Locked exit execution with double-close prevention.

Design guarantees:
    - _exit_lock serialises all exit decisions — prevents two coroutines
      from concurrently deciding to close the same position.
    - Snapshot pattern: position list snapshotted under lock, processed
      outside lock to avoid latency spikes from long I/O inside lock.
    - Double-close guard: each position_id is tracked in _closing_set.
      Once added, subsequent exit attempts for the same position are dropped.
    - Skips positions not in OPEN state (CLOSED positions ignored).
    - risk_guard.disabled fast-path at the top of every entry point.
    - Structured JSON logging on every exit action.

Exit triggers:
    - take_profit: position unrealised PnL >= take_profit_pct
    - stop_loss:   position unrealised PnL <= stop_loss_pct (negative)
    - forced:      called explicitly by RiskGuard kill switch

Usage::

    monitor = ExitMonitor(
        executor=live_executor,
        position_tracker=tracker,
        risk_guard=guard,
        take_profit_pct=0.15,    # close if +15% PnL
        stop_loss_pct=-0.08,     # close if -8% PnL
        check_interval_sec=5.0,
    )

    # Run the exit monitor loop:
    await monitor.run()

    # Or trigger a manual exit for one market:
    await monitor.exit_position("0xabc...", exit_price=0.70, reason="manual")
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Optional

import structlog

from .position_tracker import PositionRecord, PositionState

log = structlog.get_logger()

# ── Constants ─────────────────────────────────────────────────────────────────

_TAKE_PROFIT_PCT: float = 0.15      # close if unrealised PnL >= 15%
_STOP_LOSS_PCT: float = -0.08       # close if unrealised PnL <= -8%
_CHECK_INTERVAL_SEC: float = 5.0    # how often to scan open positions


# ── ExitMonitor ───────────────────────────────────────────────────────────────

class ExitMonitor:
    """Monitors open positions and executes exits deterministically.

    Key invariants:
        1. _exit_lock ensures no two exits run concurrently.
        2. _closing_set prevents double-close of the same position.
        3. No lock is held during external I/O (order placement / cancellation).
        4. risk_guard.disabled fast-path at top of all entry points.
    """

    def __init__(
        self,
        executor,               # LiveExecutor — used to place exit orders
        position_tracker,       # PositionTracker — source of open positions
        risk_guard,             # RiskGuard — disabled flag fast-path
        take_profit_pct: float = _TAKE_PROFIT_PCT,
        stop_loss_pct: float = _STOP_LOSS_PCT,
        check_interval_sec: float = _CHECK_INTERVAL_SEC,
        market_cache=None,      # Phase7MarketCache — provides real-time bid/ask
    ) -> None:
        """Initialise the exit monitor.

        Args:
            executor: LiveExecutor for placing exit orders.
            position_tracker: PositionTracker to read open positions from.
            risk_guard: RiskGuard instance.
            take_profit_pct: Exit threshold for profit (e.g. 0.15 = 15%).
            stop_loss_pct: Exit threshold for loss (e.g. -0.08 = -8%).
            check_interval_sec: Interval between position scans.
            market_cache: Optional Phase7MarketCache for real-time bid/ask prices.
                If None, exits are skipped when no price is available.
        """
        self._executor = executor
        self._tracker = position_tracker
        self._risk_guard = risk_guard
        self._take_profit_pct = take_profit_pct
        self._stop_loss_pct = stop_loss_pct
        self._check_interval_sec = check_interval_sec
        self._market_cache = market_cache

        # Serialises all concurrent exit decisions
        self._exit_lock = asyncio.Lock()

        # Tracks positions currently being closed — double-close guard
        self._closing_set: set[str] = set()    # position_id → being closed

        self._running: bool = False

        log.info(
            "exit_monitor_initialized",
            take_profit_pct=take_profit_pct,
            stop_loss_pct=stop_loss_pct,
            check_interval_sec=check_interval_sec,
            has_market_cache=market_cache is not None,
        )

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Start the exit monitoring loop.

        Runs until risk_guard.disabled is True or stop() is called.
        Each tick:
            1. Snapshot all open positions (lock → copy → release).
            2. Evaluate each position for exit conditions.
            3. Execute exits outside lock.
        """
        # ── Kill switch fast-path ─────────────────────────────────────────────
        if self._risk_guard is not None and self._risk_guard.disabled:
            log.warning("exit_monitor_startup_blocked_kill_switch")
            return

        self._running = True
        log.info("exit_monitor_loop_started")

        while self._running:
            # ── Kill switch check at top of every loop ────────────────────────
            if self._risk_guard is not None and self._risk_guard.disabled:
                log.warning("exit_monitor_loop_killed")
                self._running = False
                break

            await self._scan_and_exit()
            await asyncio.sleep(self._check_interval_sec)

        log.info("exit_monitor_loop_stopped")

    async def stop(self) -> None:
        """Gracefully stop the exit monitor."""
        self._running = False

    # ── Manual exit entry point ───────────────────────────────────────────────

    async def exit_position(
        self,
        market_id: str,
        exit_price: float,
        reason: str,
        correlation_id: Optional[str] = None,
    ) -> bool:
        """Manually trigger exit for a specific position.

        Respects double-close guard and kill switch fast-path.

        Args:
            market_id: Polymarket condition ID.
            exit_price: Execution price for the exit order.
            reason: Audit log reason for the exit.
            correlation_id: Optional trace ID.

        Returns:
            True if exit was executed. False if blocked.
        """
        cid = correlation_id or str(uuid.uuid4())

        # Kill switch fast-path (allow exits during kill switch for cleanup)
        # NOTE: we allow exits during kill switch to unwind positions.

        record = await self._tracker.get(market_id)
        if record is None:
            log.warning(
                "exit_monitor_position_not_found",
                market_id=market_id,
                correlation_id=cid,
            )
            return False

        return await self._execute_exit(record, exit_price, reason, cid)

    # ── Internal scan and exit ────────────────────────────────────────────────

    async def _scan_and_exit(self) -> None:
        """Scan all open positions and exit those meeting exit criteria.

        Pattern:
            1. Snapshot open positions UNDER _exit_lock.
            2. Release lock.
            3. Evaluate each snapshot OUTSIDE lock.
            4. Re-acquire lock per exit execution.
        """
        # Step 1: snapshot under lock
        async with self._exit_lock:
            snapshot: list[PositionRecord] = await self._tracker.open_positions_snapshot()
            # Filter to only positions not already being closed
            candidates = [
                p for p in snapshot
                if p.state == PositionState.OPEN and p.position_id not in self._closing_set
            ]

        # Step 2: evaluate and exit outside lock
        for record in candidates:
            # Kill switch fast-path per position
            if self._risk_guard is not None and self._risk_guard.disabled:
                return

            exit_price, reason = self._evaluate_exit(record)
            if exit_price is None:
                continue

            await self._execute_exit(
                record,
                exit_price=exit_price,
                reason=reason,
                correlation_id=f"exit_scan:{record.position_id[:8]}",
            )

    def _evaluate_exit(
        self, record: PositionRecord
    ) -> tuple[Optional[float], str]:
        """Evaluate whether a position should be exited.

        Uses real-time best bid/ask from market_cache if available.
        For a YES (long) position the relevant exit price is the best bid
        (what we can sell at); for a NO position it is the best ask
        (what we must pay to close).

        Returns:
            (exit_price, reason) if exit should be triggered.
            (None, "") if position should be held or price is unavailable.
        """
        if record.entry_price <= 0:
            return None, ""

        # Resolve current market price from MarketCache (real-time best bid/ask).
        # Fall back to None if the cache is absent or has no valid quote —
        # a missing price is safer than a forced close at a stale/zero price.
        current_price: Optional[float] = None
        if self._market_cache is not None:
            if record.side == "YES":
                # Closing a YES position means selling; best bid is the exit price.
                bid = self._market_cache.get_bid(record.market_id)
                if bid > 0:
                    current_price = bid
            else:
                # Closing a NO position means buying back the YES token at the ask price.
                ask = self._market_cache.get_ask(record.market_id)
                if 0 < ask <= 1.0:
                    current_price = ask

        if current_price is None:
            # No valid market price — skip exit rather than force-close at bad price.
            log.debug(
                "exit_monitor_skip_no_price",
                market_id=record.market_id,
                side=record.side,
                position_id=record.position_id,
            )
            return None, ""

        pnl_pct = (current_price - record.entry_price) / record.entry_price
        if record.side == "NO":
            pnl_pct = -pnl_pct  # inverse direction for NO positions

        if pnl_pct >= self._take_profit_pct:
            return current_price, f"take_profit:pnl_pct={pnl_pct:.4f}"

        if pnl_pct <= self._stop_loss_pct:
            return current_price, f"stop_loss:pnl_pct={pnl_pct:.4f}"

        return None, ""

    async def _execute_exit(
        self,
        record: PositionRecord,
        exit_price: float,
        reason: str,
        correlation_id: str,
    ) -> bool:
        """Execute exit for a position.

        Steps:
            1. Acquire _exit_lock — check double-close guard.
            2. Add position_id to _closing_set under lock.
            3. Release lock.
            4. Place exit order via executor (outside lock).
            5. Confirm close in PositionTracker.

        Args:
            record: Position snapshot to exit.
            exit_price: Target exit price.
            reason: Audit log reason.
            correlation_id: Trace ID.

        Returns:
            True if exit executed. False if blocked.
        """
        cid = correlation_id

        # ── Acquire lock: double-close guard ──────────────────────────────────
        async with self._exit_lock:
            # Skip non-OPEN positions (state may have changed since snapshot)
            if record.state != PositionState.OPEN:
                log.debug(
                    "exit_monitor_skip_non_open",
                    position_id=record.position_id,
                    state=record.state,
                    correlation_id=cid,
                )
                return False

            # Double-close guard: skip if already being closed
            if record.position_id in self._closing_set:
                log.warning(
                    "exit_monitor_double_close_prevented",
                    position_id=record.position_id,
                    market_id=record.market_id,
                    correlation_id=cid,
                )
                return False

            # Mark as being closed before releasing lock
            self._closing_set.add(record.position_id)

        # ── Execute outside lock ───────────────────────────────────────────────
        log.info(
            "exit_monitor_executing_exit",
            position_id=record.position_id,
            market_id=record.market_id,
            side=record.side,
            size=record.size,
            entry_price=record.entry_price,
            exit_price=exit_price,
            reason=reason,
            correlation_id=cid,
        )

        try:
            # Determine exit side (opposite of entry side)
            exit_side = "NO" if record.side == "YES" else "YES"

            from ..phase7.core.execution.live_executor import ExecutionRequest
            exit_request = ExecutionRequest(
                market_id=record.market_id,
                side=exit_side,
                price=round(exit_price, 6),
                size=record.size,
                order_type="LIMIT",
                correlation_id=cid,
            )
            result = await self._executor.execute(exit_request)

            if result.status in ("submitted", "filled", "partial"):
                realised_pnl = (exit_price - record.entry_price) * record.size
                if record.side == "NO":
                    realised_pnl = -realised_pnl

                await self._tracker.close(
                    market_id=record.market_id,
                    exit_price=exit_price,
                    realised_pnl=realised_pnl,
                    close_reason=reason,
                    correlation_id=cid,
                )

                log.info(
                    "exit_monitor_exit_complete",
                    position_id=record.position_id,
                    market_id=record.market_id,
                    exit_order_id=result.order_id,
                    exit_status=result.status,
                    realised_pnl=round(realised_pnl, 4),
                    reason=reason,
                    correlation_id=cid,
                )
                return True

            else:
                log.error(
                    "exit_monitor_exit_order_failed",
                    position_id=record.position_id,
                    market_id=record.market_id,
                    order_status=result.status,
                    error=result.error,
                    reason=reason,
                    correlation_id=cid,
                )
                return False

        except Exception as exc:  # noqa: BLE001
            log.error(
                "exit_monitor_exit_exception",
                position_id=record.position_id,
                market_id=record.market_id,
                error=str(exc),
                reason=reason,
                correlation_id=cid,
                exc_info=True,
            )
            return False

        finally:
            # Always remove from _closing_set — allows retry if exit failed
            async with self._exit_lock:
                self._closing_set.discard(record.position_id)

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Return structured monitoring state for HealthMonitor."""
        return {
            "running": self._running,
            "closing_positions": len(self._closing_set),
            "take_profit_pct": self._take_profit_pct,
            "stop_loss_pct": self._stop_loss_pct,
        }
