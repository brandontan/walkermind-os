"""Phase 8 — OrderGuard: Duplicate order protection with active_orders set.

Design guarantees:
    - order_signature is computed as:
          f"{market_id}:{side}:{round(price,4)}:{round(size,2)}"
      providing tolerance for floating-point precision differences at the
      4th decimal for price and 2nd decimal for size.
    - active_orders: set[str] prevents the same (market, side, price, size)
      combination from being submitted more than once while still live.
    - On order completion (fill, cancel, failure), the signature is removed
      from active_orders so the next trade on the same market can proceed.
    - order_timeout_sec: orders are automatically evicted from active_orders
      after the timeout to prevent the set from growing stale.
    - risk_guard.disabled fast-path at every entry point.
    - Structured JSON logging on every block/allow decision.

Usage::

    guard = OrderGuard(risk_guard=risk_guard, order_timeout_sec=30.0)

    # Before submitting an order:
    sig = guard.compute_signature(market_id, side, price, size)
    if not guard.try_claim(sig, order_id="", correlation_id=cid):
        # Duplicate blocked — do not submit
        return

    try:
        result = await executor.execute(request)
        # On success, update the order_id in the guard
        guard.update_order_id(sig, result.order_id)
    finally:
        if result.status in ("filled", "rejected", "cancelled"):
            guard.release(sig, correlation_id=cid)
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional

import structlog

log = structlog.get_logger()

# ── Constants ─────────────────────────────────────────────────────────────────

_ORDER_TIMEOUT_SEC: float = 30.0     # evict stale signatures after this time


# ── Internal record ───────────────────────────────────────────────────────────

@dataclass
class _ClaimedOrder:
    """Tracks a claimed order signature."""
    signature: str
    order_id: str
    correlation_id: str
    claimed_at: float = field(default_factory=time.time)


# ── OrderGuard ────────────────────────────────────────────────────────────────

class OrderGuard:
    """Execution layer duplicate order protection.

    Maintains an active_orders set of order signatures to prevent duplicate
    submissions. Signatures are released on order completion or timeout.

    Thread-safety: designed for single asyncio event loop.
    asyncio.Lock serialises all mutations to _active.
    """

    def __init__(
        self,
        risk_guard=None,
        order_timeout_sec: float = _ORDER_TIMEOUT_SEC,
    ) -> None:
        """Initialise the order guard.

        Args:
            risk_guard: RiskGuard instance for disabled flag.
            order_timeout_sec: Stale signature eviction timeout in seconds.
        """
        self._risk_guard = risk_guard
        self._timeout_sec = order_timeout_sec

        self._lock = asyncio.Lock()
        self._active: dict[str, _ClaimedOrder] = {}   # signature → claim record

        log.info(
            "order_guard_initialized",
            order_timeout_sec=order_timeout_sec,
        )

    # ── Signature computation ─────────────────────────────────────────────────

    @staticmethod
    def compute_signature(
        market_id: str,
        side: str,
        price: float,
        size: float,
    ) -> str:
        """Compute a stable order signature for dedup.

        Formula:
            f"{market_id}:{side}:{round(price,4)}:{round(size,2)}"

        Price is rounded to 4 decimal places and size to 2 decimal places
        to absorb minor floating-point jitter without losing meaningful
        dedup precision.

        Args:
            market_id: Polymarket condition ID.
            side: "YES" | "NO".
            price: Limit price.
            size: Order size in USD.

        Returns:
            Stable string signature for use as a dedup key.
        """
        return f"{market_id}:{side}:{round(price, 4)}:{round(size, 2)}"

    # ── Claim / release lifecycle ─────────────────────────────────────────────

    async def try_claim(
        self,
        signature: str,
        order_id: str = "",
        correlation_id: str = "",
    ) -> bool:
        """Attempt to claim an order signature for submission.

        Blocks if signature is already active (duplicate guard).
        Evicts stale signatures before checking.

        Args:
            signature: Computed via compute_signature().
            order_id: Exchange order ID (may be empty before placement).
            correlation_id: Request trace ID.

        Returns:
            True if claimed (safe to submit). False if duplicate blocked.
        """
        # Kill switch fast-path
        if self._risk_guard is not None and self._risk_guard.disabled:
            log.warning(
                "order_guard_claim_blocked_kill_switch",
                signature=signature,
                correlation_id=correlation_id,
            )
            return False

        async with self._lock:
            # Evict stale claims before checking
            self._evict_stale()

            if signature in self._active:
                existing = self._active[signature]
                log.warning(
                    "order_guard_duplicate_blocked",
                    signature=signature,
                    existing_order_id=existing.order_id,
                    existing_correlation_id=existing.correlation_id,
                    age_s=round(time.time() - existing.claimed_at, 2),
                    correlation_id=correlation_id,
                )
                return False

            self._active[signature] = _ClaimedOrder(
                signature=signature,
                order_id=order_id,
                correlation_id=correlation_id,
            )

        log.debug(
            "order_guard_claim_granted",
            signature=signature,
            correlation_id=correlation_id,
        )
        return True

    async def update_order_id(self, signature: str, order_id: str) -> None:
        """Update the exchange order_id for a claimed signature.

        Called after the exchange assigns an ID to a submitted order.

        Args:
            signature: The previously claimed signature.
            order_id: Exchange-assigned order ID.
        """
        async with self._lock:
            claim = self._active.get(signature)
            if claim is not None:
                claim.order_id = order_id

    async def release(self, signature: str, correlation_id: str = "") -> None:
        """Release a claimed signature after order completion.

        Called when an order is filled, cancelled, or failed.
        After release, the same (market, side, price, size) combination
        can be submitted again.

        Args:
            signature: The signature to release.
            correlation_id: Request trace ID for logging.
        """
        async with self._lock:
            claim = self._active.pop(signature, None)

        if claim is not None:
            log.debug(
                "order_guard_signature_released",
                signature=signature,
                order_id=claim.order_id,
                held_s=round(time.time() - claim.claimed_at, 2),
                correlation_id=correlation_id or claim.correlation_id,
            )
        else:
            log.debug(
                "order_guard_release_not_found",
                signature=signature,
                correlation_id=correlation_id,
            )

    async def release_by_order_id(self, order_id: str, correlation_id: str = "") -> None:
        """Release a claimed signature by exchange order ID.

        Useful when only the order_id is known at completion time.

        Args:
            order_id: Exchange order ID.
            correlation_id: Request trace ID.
        """
        async with self._lock:
            target_sig = next(
                (sig for sig, c in self._active.items() if c.order_id == order_id),
                None,
            )
            if target_sig is not None:
                del self._active[target_sig]

        if target_sig:
            log.debug(
                "order_guard_released_by_order_id",
                order_id=order_id,
                signature=target_sig,
                correlation_id=correlation_id,
            )

    # ── Stale eviction ────────────────────────────────────────────────────────

    def _evict_stale(self) -> None:
        """Evict signatures that have been active longer than _timeout_sec.

        Must be called under _lock.
        Prevents the active_orders set from accumulating stale entries if
        an order completes without an explicit release() call.
        """
        now = time.time()
        stale = [
            sig for sig, claim in self._active.items()
            if now - claim.claimed_at >= self._timeout_sec
        ]
        for sig in stale:
            claim = self._active.pop(sig)
            log.warning(
                "order_guard_stale_signature_evicted",
                signature=sig,
                order_id=claim.order_id,
                age_s=round(now - claim.claimed_at, 2),
                timeout_s=self._timeout_sec,
            )

    async def evict_stale_now(self) -> int:
        """Manually trigger stale eviction and return count evicted."""
        before = len(self._active)
        async with self._lock:
            self._evict_stale()
        after = len(self._active)
        return before - after

    # ── Diagnostics ───────────────────────────────────────────────────────────

    async def status(self) -> dict:
        """Return structured state for HealthMonitor."""
        async with self._lock:
            active_count = len(self._active)
            active_sigs = list(self._active.keys())
        return {
            "active_orders": active_count,
            "active_signatures": active_sigs,
            "order_timeout_sec": self._timeout_sec,
        }
