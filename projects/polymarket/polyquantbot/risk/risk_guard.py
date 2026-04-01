"""Phase 8 — RiskGuard: Kill switch authority with global override.

Design:
    - self.disabled is the master override flag.
    - trigger_kill_switch() sets disabled=True as its FIRST action —
      before cancelling orders or closing positions — so all concurrent
      coroutines see the flag and exit immediately via fast-path check.
    - All modules must check `if risk_guard.disabled: return` at the top
      of every control loop and action path.
    - Force-close and cancel operations run OUTSIDE the lock to prevent
      latency spikes; the disabled flag itself needs no lock (asyncio is
      single-threaded — the write is atomic within the event loop).

Kill switch triggers:
    - Manual call: trigger_kill_switch(reason)
    - Daily loss limit breached
    - Max drawdown exceeded
    - Exposure anomaly detected by HealthMonitor
    - Unhandled critical exception propagated from any control module

Usage::

    guard = RiskGuard(
        daily_loss_limit=-2000.0,
        max_drawdown_pct=0.08,
        executor=live_executor,
        position_tracker=tracker,
    )

    # In every control loop:
    if guard.disabled:
        return

    # Risk checks:
    await guard.check_daily_loss(current_pnl)
    await guard.check_drawdown(peak_balance, current_balance)
"""
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Optional

import structlog

if TYPE_CHECKING:
    pass  # avoid circular imports — executor/tracker injected at runtime

log = structlog.get_logger()

# ── Constants ──────────────────────────────────────────────────────────────────

_DAILY_LOSS_LIMIT_USD: float = -2000.0   # USD — pause if hit
_MAX_DRAWDOWN_PCT: float = 0.08          # 8% → block all trades
_CANCEL_ALL_TIMEOUT_S: float = 15.0      # max time to cancel all orders


# ── RiskGuard ─────────────────────────────────────────────────────────────────

class RiskGuard:
    """Master risk authority — controls the kill switch for all Phase 8 modules.

    Thread-safety: designed for a single asyncio event loop.
    The `disabled` flag is read/written atomically within the event loop.
    No asyncio.Lock is needed for the flag itself.
    """

    def __init__(
        self,
        daily_loss_limit: float = _DAILY_LOSS_LIMIT_USD,
        max_drawdown_pct: float = _MAX_DRAWDOWN_PCT,
        executor=None,           # LiveExecutor — injected to cancel orders
        position_tracker=None,   # PositionTracker — injected to close positions
    ) -> None:
        """Initialise RiskGuard.

        Args:
            daily_loss_limit: PnL threshold (negative USD) below which kill switch fires.
            max_drawdown_pct: Drawdown fraction above which kill switch fires.
            executor: LiveExecutor instance for cancel_all_open().
            position_tracker: PositionTracker instance for force_close_all().
        """
        self.disabled: bool = False          # master override — read by ALL modules
        self._daily_loss_limit = daily_loss_limit
        self._max_drawdown_pct = max_drawdown_pct
        self._executor = executor
        self._position_tracker = position_tracker

        self._kill_switch_reason: Optional[str] = None
        self._kill_switch_time: Optional[float] = None
        self._kill_switch_lock = asyncio.Lock()  # serialise concurrent trigger calls

        log.info(
            "risk_guard_initialized",
            daily_loss_limit=daily_loss_limit,
            max_drawdown_pct=max_drawdown_pct,
        )

    # ── Kill switch ───────────────────────────────────────────────────────────

    async def trigger_kill_switch(self, reason: str) -> None:
        """Activate the global kill switch — instant override of all control flows.

        Step 1: Set disabled=True IMMEDIATELY (first line, no await).
        Step 2: Log the trigger event.
        Step 3: Cancel all open orders via executor.
        Step 4: Force-close all positions via position_tracker.

        Concurrent calls are serialised by _kill_switch_lock so the cancel/
        close sequences do not run more than once. The disabled flag is already
        True before acquiring the lock, so all modules exit via fast-path.

        Args:
            reason: Human-readable trigger reason for audit log.
        """
        # ── STEP 1: Disable immediately — no await, no lock ──────────────────
        self.disabled = True

        # ── STEP 2: Log ───────────────────────────────────────────────────────
        log.error(
            "kill_switch_triggered",
            reason=reason,
            previous_reason=self._kill_switch_reason,
        )

        # ── STEP 3 & 4: Serialised cleanup (only runs once) ──────────────────
        async with self._kill_switch_lock:
            if self._kill_switch_reason is not None:
                # Already processed — disabled flag is already set; nothing more to do.
                log.warning(
                    "kill_switch_already_active",
                    existing_reason=self._kill_switch_reason,
                    new_reason=reason,
                )
                return

            self._kill_switch_reason = reason
            self._kill_switch_time = time.time()

            # Cancel all open orders
            if self._executor is not None:
                try:
                    cancelled = await asyncio.wait_for(
                        self._executor.cancel_all_open(f"kill_switch:{reason}"),
                        timeout=_CANCEL_ALL_TIMEOUT_S,
                    )
                    log.warning(
                        "kill_switch_cancelled_orders",
                        cancelled_count=cancelled,
                        reason=reason,
                    )
                except asyncio.TimeoutError:
                    log.error(
                        "kill_switch_cancel_orders_timeout",
                        timeout_s=_CANCEL_ALL_TIMEOUT_S,
                        reason=reason,
                    )
                except Exception as exc:  # noqa: BLE001
                    log.error(
                        "kill_switch_cancel_orders_error",
                        error=str(exc),
                        reason=reason,
                        exc_info=True,
                    )

            # Force-close all positions
            if self._position_tracker is not None:
                try:
                    closed = await asyncio.wait_for(
                        self._position_tracker.force_close_all(f"kill_switch:{reason}"),
                        timeout=_CANCEL_ALL_TIMEOUT_S,
                    )
                    log.warning(
                        "kill_switch_closed_positions",
                        closed_count=closed,
                        reason=reason,
                    )
                except asyncio.TimeoutError:
                    log.error(
                        "kill_switch_close_positions_timeout",
                        timeout_s=_CANCEL_ALL_TIMEOUT_S,
                        reason=reason,
                    )
                except Exception as exc:  # noqa: BLE001
                    log.error(
                        "kill_switch_close_positions_error",
                        error=str(exc),
                        reason=reason,
                        exc_info=True,
                    )

            log.error(
                "kill_switch_complete",
                reason=reason,
                kill_time=self._kill_switch_time,
            )

    # ── Risk checks ───────────────────────────────────────────────────────────

    async def check_daily_loss(self, current_pnl: float) -> None:
        """Trigger kill switch if daily PnL breaches the loss limit.

        Fast-path exits immediately if already disabled.

        Args:
            current_pnl: Current day's realised PnL in USD (negative = loss).
        """
        if self.disabled:
            return
        if current_pnl <= self._daily_loss_limit:
            await self.trigger_kill_switch(
                f"daily_loss_limit_breached:pnl={current_pnl:.2f}"
                f"_limit={self._daily_loss_limit:.2f}"
            )

    async def check_drawdown(self, peak_balance: float, current_balance: float) -> None:
        """Trigger kill switch if drawdown exceeds max_drawdown_pct.

        Fast-path exits immediately if already disabled.

        Args:
            peak_balance: Highest recorded account balance (USD).
            current_balance: Current account balance (USD).
        """
        if self.disabled:
            return
        if peak_balance <= 0:
            return
        drawdown = (peak_balance - current_balance) / peak_balance
        if drawdown >= self._max_drawdown_pct:
            await self.trigger_kill_switch(
                f"max_drawdown_breached:drawdown={drawdown:.4f}"
                f"_limit={self._max_drawdown_pct:.4f}"
            )

    async def check_exposure(
        self,
        total_exposure: float,
        balance: float,
        threshold_pct: float = 0.45,
    ) -> None:
        """Trigger kill switch if total exposure exceeds threshold_pct of balance.

        Called by HealthMonitor as an anomaly guard.

        Args:
            total_exposure: Sum of all open position sizes in USD.
            balance: Current account balance in USD.
            threshold_pct: Warning threshold (default 0.45 = 45% of balance).
        """
        if self.disabled:
            return
        if balance <= 0:
            return
        ratio = total_exposure / balance
        if ratio > threshold_pct:
            await self.trigger_kill_switch(
                f"exposure_anomaly:exposure={total_exposure:.2f}"
                f"_balance={balance:.2f}_ratio={ratio:.4f}"
                f"_threshold={threshold_pct:.2f}"
            )

    # ── Status ────────────────────────────────────────────────────────────────

    @property
    def kill_switch_reason(self) -> Optional[str]:
        """Return the reason the kill switch was triggered, or None."""
        return self._kill_switch_reason

    @property
    def kill_switch_time(self) -> Optional[float]:
        """Return the Unix timestamp when kill switch fired, or None."""
        return self._kill_switch_time

    def status(self) -> dict:
        """Return a structured snapshot of the current guard state."""
        return {
            "disabled": self.disabled,
            "kill_switch_reason": self._kill_switch_reason,
            "kill_switch_time": self._kill_switch_time,
            "daily_loss_limit": self._daily_loss_limit,
            "max_drawdown_pct": self._max_drawdown_pct,
        }
