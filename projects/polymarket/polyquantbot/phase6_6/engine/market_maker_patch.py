"""Market maker inventory hard stop — Phase 6.6.

Extends Phase 6 MarketMaker with a hard inventory limit that triggers
an immediate, idempotent halt + async order cancellation when the net
position in a market exceeds the configured maximum.

Hard stop formula::

    max_inventory = inventory_limit_pct × max_position × hard_stop_multiplier

Where:
    inventory_limit_pct   — fraction of max_position defining the soft ceiling
                            (default 0.2, i.e. 20%)
    max_position          — absolute dollar cap per position (passed at call time,
                            typically balance × max_position_pct from capital config)
    hard_stop_multiplier  — safety multiplier above the soft ceiling (default 1.5)

    Example: balance=$1000, max_position_pct=0.10, inventory_limit_pct=0.2,
             hard_stop_multiplier=1.5
             max_position = 100
             max_inventory = 0.2 × 100 × 1.5 = 30

Idempotency:
    The stop is idempotent: if the market is already in cooldown
    (disabled_until > now), the method logs at DEBUG level and returns
    immediately without triggering a second cancellation wave.

Async cancellation:
    Uses asyncio.create_task() — the calling coroutine is NOT blocked.
    The cancel wave runs in the background exactly as Phase 6 does.

Event logging:
    Triggers a structured "mm_inventory_hard_stop" WARNING log containing:
        market_id, net_position, max_inventory, cooldown_until, correlation_id

Backward compatibility:
    MarketMakerPatch does NOT inherit from Phase 6 MarketMaker.
    It manages its own per-market inventory state and is wired alongside
    (not replacing) the existing MarketMaker instance via runner_patch.py.

    The cancel_all callback must be provided at construction so the patch
    can trigger cancellations without holding a reference to the full MM.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

import structlog

log = structlog.get_logger()

# Default fallback delays for cancel retries (mirrors Phase 6 constants)
_CANCEL_RETRY_DELAYS: list[float] = [0.05, 0.1, 0.2]


@dataclass
class InventoryState:
    """Per-market inventory tracking state."""

    market_id: str
    net_position: float = 0.0          # sum of fills (positive = long)
    disabled_until: float = 0.0        # epoch seconds
    hard_stop_count: int = 0           # number of times hard stop was triggered
    last_stop_at: Optional[float] = None


@dataclass
class InventoryCheckResult:
    """Result of a check_inventory() call."""

    stopped: bool
    net_position: float
    max_inventory: float
    cooldown_remaining_s: float
    correlation_id: str


class MarketMakerPatch:
    """Inventory hard stop controller for Phase 6.6.

    Maintains per-market net_position counters and enforces a hard stop
    when inventory exceeds the configured limit.

    Typical integration::

        mm_patch = MarketMakerPatch.from_config(cfg, cancel_callback=mm.cancel_all_orders)

        # After each fill update the inventory:
        mm_patch.record_fill(market_id, filled_size, outcome="YES")

        # Before each quote cycle check the hard stop:
        result = await mm_patch.check_inventory(
            market_id, max_position=100.0, correlation_id=cid
        )
        if result.stopped:
            return   # skip quoting this cycle
    """

    def __init__(
        self,
        inventory_limit_pct: float = 0.2,
        hard_stop_multiplier: float = 1.5,
        cooldown_seconds: float = 60.0,
        cancel_callback: Optional[
            Callable[[str, str], Awaitable[None]]
        ] = None,
    ) -> None:
        """Initialise the patch.

        Args:
            inventory_limit_pct: Fraction of max_position forming the inventory
                ceiling before the multiplier is applied.  Typically 0.0–1.0.
            hard_stop_multiplier: Safety multiplier above inventory_limit_pct.
                max_inventory = inventory_limit_pct × max_position × multiplier.
            cooldown_seconds: How long the MM stays halted after a hard stop.
            cancel_callback: Async function(market_id, correlation_id) → None
                that cancels all open orders.  If None, cancellation is skipped
                (useful for testing).
        """
        if inventory_limit_pct <= 0:
            raise ValueError(f"inventory_limit_pct must be > 0, got {inventory_limit_pct}")
        if hard_stop_multiplier <= 0:
            raise ValueError(f"hard_stop_multiplier must be > 0, got {hard_stop_multiplier}")

        self._inv_pct = inventory_limit_pct
        self._multiplier = hard_stop_multiplier
        self._cooldown = cooldown_seconds
        self._cancel_cb = cancel_callback

        self._states: dict[str, InventoryState] = {}
        self._cancel_tasks: set[asyncio.Task] = set()

    # ── State helpers ─────────────────────────────────────────────────────────

    def _get_state(self, market_id: str) -> InventoryState:
        """Return existing or newly created InventoryState for a market."""
        if market_id not in self._states:
            self._states[market_id] = InventoryState(market_id=market_id)
        return self._states[market_id]

    def _is_halted(self, market_id: str) -> bool:
        """Return True if the market is currently in cooldown."""
        return time.time() < self._get_state(market_id).disabled_until

    def _compute_max_inventory(self, max_position: float) -> float:
        """Compute the hard inventory limit.

        max_inventory = inventory_limit_pct × max_position × hard_stop_multiplier
        """
        return self._inv_pct * max_position * self._multiplier

    # ── Inventory recording ───────────────────────────────────────────────────

    def record_fill(
        self,
        market_id: str,
        filled_size: float,
        outcome: str,
        correlation_id: str = "",
    ) -> None:
        """Update net_position after an order fill.

        YES fills increase inventory; NO fills decrease it
        (YES and NO are opposite sides).

        Args:
            market_id: Market that was filled.
            filled_size: Absolute fill size in USD.
            outcome: "YES" (long) or "NO" (short).
            correlation_id: Optional request ID for log tracing.
        """
        state = self._get_state(market_id)
        delta = filled_size if outcome == "YES" else -filled_size
        state.net_position = round(state.net_position + delta, 6)
        log.debug(
            "mm_inventory_updated",
            correlation_id=correlation_id,
            market_id=market_id,
            delta=delta,
            net_position=state.net_position,
        )

    def record_close(
        self,
        market_id: str,
        closed_size: float,
        outcome: str,
        correlation_id: str = "",
    ) -> None:
        """Reduce net_position when a position is closed (exit fill).

        Args:
            market_id: Market being closed.
            closed_size: Absolute closed size in USD.
            outcome: Original trade outcome ("YES" = closing reduces long).
            correlation_id: Optional request ID.
        """
        state = self._get_state(market_id)
        delta = -closed_size if outcome == "YES" else closed_size
        state.net_position = round(state.net_position + delta, 6)
        log.debug(
            "mm_inventory_position_closed",
            correlation_id=correlation_id,
            market_id=market_id,
            delta=delta,
            net_position=state.net_position,
        )

    # ── Hard stop ─────────────────────────────────────────────────────────────

    async def _trigger_hard_stop(
        self,
        state: InventoryState,
        max_inventory: float,
        correlation_id: str,
    ) -> None:
        """Execute the hard stop: disable MM and fire async cancellation.

        This method is idempotent via the disabled_until guard in check_inventory.
        """
        now = time.time()
        state.disabled_until = now + self._cooldown
        state.hard_stop_count += 1
        state.last_stop_at = now

        log.warning(
            "mm_inventory_hard_stop",
            correlation_id=correlation_id,
            market_id=state.market_id,
            net_position=state.net_position,
            max_inventory=round(max_inventory, 4),
            cooldown_seconds=self._cooldown,
            cooldown_until=round(state.disabled_until, 1),
            hard_stop_count=state.hard_stop_count,
        )

        # Non-blocking cancellation via asyncio.create_task
        if self._cancel_cb is not None:
            task = asyncio.create_task(
                self._cancel_cb(state.market_id, correlation_id)
            )
            self._cancel_tasks.add(task)
            task.add_done_callback(self._cancel_tasks.discard)
        else:
            log.debug(
                "mm_hard_stop_no_cancel_callback",
                correlation_id=correlation_id,
                market_id=state.market_id,
            )

    # ── Primary API ───────────────────────────────────────────────────────────

    async def check_inventory(
        self,
        market_id: str,
        max_position: float,
        correlation_id: str,
    ) -> InventoryCheckResult:
        """Check whether net inventory exceeds the hard limit and stop if so.

        Idempotent: if already in cooldown, returns immediately without
        re-triggering cancellations or resetting the cooldown timer.

        Args:
            market_id: Market to check.
            max_position: Absolute max position in USD (from capital config).
                          max_inventory = inventory_limit_pct × max_position
                          × hard_stop_multiplier.
            correlation_id: Request ID for log correlation.

        Returns:
            InventoryCheckResult with stopped=True if a hard stop is active.
        """
        state = self._get_state(market_id)
        max_inventory = self._compute_max_inventory(max_position)
        now = time.time()

        # ── Idempotent guard: already halted ──────────────────────────────────
        if state.disabled_until > now:
            remaining = state.disabled_until - now
            log.debug(
                "mm_inventory_already_halted",
                correlation_id=correlation_id,
                market_id=market_id,
                cooldown_remaining_s=round(remaining, 1),
            )
            return InventoryCheckResult(
                stopped=True,
                net_position=state.net_position,
                max_inventory=max_inventory,
                cooldown_remaining_s=round(remaining, 1),
                correlation_id=correlation_id,
            )

        # ── Breach check ──────────────────────────────────────────────────────
        if abs(state.net_position) > max_inventory:
            await self._trigger_hard_stop(state, max_inventory, correlation_id)
            return InventoryCheckResult(
                stopped=True,
                net_position=state.net_position,
                max_inventory=max_inventory,
                cooldown_remaining_s=self._cooldown,
                correlation_id=correlation_id,
            )

        return InventoryCheckResult(
            stopped=False,
            net_position=state.net_position,
            max_inventory=max_inventory,
            cooldown_remaining_s=0.0,
            correlation_id=correlation_id,
        )

    def get_net_position(self, market_id: str) -> float:
        """Return current net position for a market (0.0 if unknown)."""
        return self._get_state(market_id).net_position

    def reset_inventory(self, market_id: str) -> None:
        """Manually reset inventory for a market (e.g., after reconciliation)."""
        if market_id in self._states:
            self._states[market_id].net_position = 0.0

    async def cleanup(self) -> None:
        """Wait for all pending cancel tasks on shutdown."""
        if self._cancel_tasks:
            await asyncio.gather(*list(self._cancel_tasks), return_exceptions=True)
        log.info(
            "mm_patch_cleanup_complete",
            pending_tasks=len(self._cancel_tasks),
        )

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_config(
        cls,
        cfg: dict,
        cancel_callback: Optional[Callable[[str, str], Awaitable[None]]] = None,
    ) -> "MarketMakerPatch":
        """Build from top-level config dict (reads 'market_maker' block).

        Args:
            cfg: Top-level config dict loaded from config.yaml.
            cancel_callback: Async function(market_id, correlation_id) → None.
                             Pass MarketMaker.cancel_all_orders directly.
        """
        mm = cfg.get("market_maker", {})
        return cls(
            inventory_limit_pct=float(mm.get("inventory_limit_pct", 0.2)),
            hard_stop_multiplier=float(mm.get("hard_stop_multiplier", 1.5)),
            cooldown_seconds=float(mm.get("cooldown_seconds", 60.0)),
            cancel_callback=cancel_callback,
        )
