"""Per-market inventory tracker (WARP/R00T/inventory-tracker-foundation,
ref Polybot directive §5).

Foundation lane: compute per-(user, market) inventory from the
``positions`` table and expose a simple dataclass for downstream
consumers. Behaviourally read-only — no execution-layer change in this
lane.

Why a foundation lane:
  The directive's full §5 spec (Polybot's ``MarketInventory``) is
  designed to support a dual-leg arbitrage strategy that holds BOTH
  the YES and NO legs of a market simultaneously and rebalances via
  fast top-ups. CrusaderBot's current execution model is single-leg
  per candidate, with `_has_open_position_for_market` blocking any
  second entry on a market for 24h. Building the data structure here
  lets follow-up lanes wire it into:

    1. Safe Close direction override (directive 1.2.1.c) — pick the
       lagging leg when imbalance exceeds threshold.
    2. Flip Hunter Mode A fast top-up (directive 1.5 + 1.3.2) — chase
       the opposite leg immediately after a partial fill.
    3. Cross-strategy exposure aggregation for the directive's
       MAX_TOTAL_FRACTION cap (§6).

  Shipping the foundation alone makes each of those subsequent lanes a
  thin gate insertion rather than a refactor.

What's in scope (this lane):
  - ``MarketInventory`` dataclass.
  - ``compute_market_inventory`` async helper that aggregates
    ``positions`` rows for a given ``(user_id, market_id)``.
  - Helper math: ``imbalance_usdc``, ``imbalance_pct`` properties.
  - Hermetic tests with mocked asyncpg.

What's NOT in scope:
  - No ``positions`` schema change (single-side rows stay single-side).
  - No execution-layer wiring (signal_scan_job continues to build
    candidates without consulting inventory; existing dedup gate at
    step 2 still rejects same-market second entries).
  - No background sync loop / 5s refresh job (Polybot spec §5) — that
    becomes meaningful only once dual-leg execution exists.

Authoritative source:
  ``positions`` table. Only ``open`` + ``pending_settlement`` rows
  contribute to the live inventory; closed rows would double-count
  realized cost basis against the user's current position.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID


_LIVE_POSITION_STATUSES: frozenset[str] = frozenset({"open", "pending_settlement"})


@dataclass(frozen=True)
class MarketInventory:
    """Net open exposure for a ``(user, market)`` pair.

    Sizes are summed cost basis (USDC), NOT shares — CrusaderBot pays
    cost-basis at entry and settles at $1.00 per token at expiry, so
    "shares" and "cost / entry_price" are interchangeable up to the
    fill price. Cost basis is what the existing risk gate caps against
    so it's the natural unit for inventory.

    Counts are the number of OPEN positions per side. Useful for the
    rare case where multiple partial fills land on the same side
    before the dedup gate would normally close the window — gives
    downstream callers visibility without re-querying.
    """
    user_id: str
    market_id: str
    yes_size_usdc: Decimal
    no_size_usdc: Decimal
    yes_count: int
    no_count: int

    @property
    def imbalance_usdc(self) -> Decimal:
        """``yes_size_usdc - no_size_usdc``. Positive = YES-heavy
        exposure, negative = NO-heavy, zero = balanced (or no positions).
        """
        return self.yes_size_usdc - self.no_size_usdc

    @property
    def total_size_usdc(self) -> Decimal:
        """Combined cost basis across both legs."""
        return self.yes_size_usdc + self.no_size_usdc

    @property
    def imbalance_pct(self) -> Optional[Decimal]:
        """Imbalance as a fraction of total cost basis.

        ``Decimal('1')`` means 100% on the YES leg, ``Decimal('-1')``
        means 100% on the NO leg, ``Decimal('0')`` is balanced.
        Returns ``None`` when both legs are empty (no division by
        zero; caller treats absent imbalance as "no position").
        """
        total = self.total_size_usdc
        if total == 0:
            return None
        return self.imbalance_usdc / total

    @property
    def is_empty(self) -> bool:
        """True iff there is no live exposure on either leg."""
        return self.yes_count == 0 and self.no_count == 0


def _empty_inventory(user_id: str, market_id: str) -> MarketInventory:
    return MarketInventory(
        user_id=user_id,
        market_id=market_id,
        yes_size_usdc=Decimal("0"),
        no_size_usdc=Decimal("0"),
        yes_count=0,
        no_count=0,
    )


async def compute_market_inventory(
    conn: Any,
    user_id: UUID | str,
    market_id: str,
) -> MarketInventory:
    """Aggregate live ``positions`` rows for ``(user_id, market_id)``.

    Only ``open`` and ``pending_settlement`` rows are counted; closed
    rows are excluded because their cost basis has already been
    realised against the user's bankroll and including them would
    double-count.

    Returns an empty inventory (zeros) when the user has no live
    positions on the market — callers should treat an empty inventory
    the same as "no inventory data".
    """
    uid = str(user_id)
    rows = await conn.fetch(
        """
        SELECT LOWER(side) AS side,
               COALESCE(SUM(size_usdc), 0) AS total_size,
               COUNT(*) AS n
          FROM positions
         WHERE user_id = $1::uuid
           AND market_id = $2
           AND status = ANY($3::text[])
         GROUP BY LOWER(side)
        """,
        uid,
        market_id,
        list(_LIVE_POSITION_STATUSES),
    )
    yes_size = Decimal("0")
    no_size = Decimal("0")
    yes_count = 0
    no_count = 0
    for r in rows:
        side = str(r["side"] or "").lower()
        size = Decimal(str(r["total_size"] or 0))
        n = int(r["n"] or 0)
        if side == "yes":
            yes_size = size
            yes_count = n
        elif side == "no":
            no_size = size
            no_count = n
        # Unknown side label is ignored — defensive against legacy data
        # but does not crash the scan tick.
    return MarketInventory(
        user_id=uid,
        market_id=market_id,
        yes_size_usdc=yes_size,
        no_size_usdc=no_size,
        yes_count=yes_count,
        no_count=no_count,
    )


__all__ = [
    "MarketInventory",
    "compute_market_inventory",
]
