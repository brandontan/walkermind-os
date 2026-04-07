"""core.portfolio.pnl — PnL tracking for PolyQuantBot paper & live trading.

Maintains realized and unrealized PnL records, stores them to the database,
and exposes a simple read API for monitoring / Telegram reporting.

Interfaces::

    PnLRecord(market_id, realized, unrealized, updated_at)
    PnLTracker.record_realized(market_id, trade_id, pnl_usd)
    PnLTracker.record_unrealized(market_id, pnl_usd)
    PnLTracker.get(market_id)  → PnLRecord | None
    PnLTracker.summary()       → dict

Design:
  - Realized PnL is persisted to the database (2 retries on failure).
  - Unrealized PnL is in-memory only (mark-to-market, updated frequently).
  - Zero silent failure: every DB error is logged.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import structlog

log = structlog.get_logger()


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class PnLRecord:
    """PnL snapshot for a single market.

    Attributes:
        market_id:   Polymarket condition ID.
        realized:    Cumulative realized PnL in USD for this market.
        unrealized:  Current unrealized PnL in USD (mark-to-market).
        updated_at:  UNIX timestamp of last update.
    """

    market_id: str
    realized: float = 0.0
    unrealized: float = 0.0
    updated_at: float = field(default_factory=time.time)


# ── Tracker ───────────────────────────────────────────────────────────────────

class PnLTracker:
    """PnL state machine for all tracked markets.

    Accepts an optional *db* (a :class:`~infra.db.DatabaseClient` or any object
    with a compatible ``update_trade_status`` coroutine) for persistence of
    realized PnL.  When *db* is ``None``, the tracker operates in memory-only
    mode without crashing.
    """

    def __init__(self, db: Optional[Any] = None) -> None:
        """Initialise the tracker.

        Args:
            db: Optional database client for persisting realized PnL.
        """
        self._db = db
        self._records: Dict[str, PnLRecord] = {}

    # ── Writes ────────────────────────────────────────────────────────────────

    def record_realized(
        self,
        market_id: str,
        pnl_usd: float,
        trade_id: str = "",
    ) -> PnLRecord:
        """Record realized PnL for a closed position.

        Adds *pnl_usd* to the cumulative realized PnL for *market_id* and
        schedules a DB write when a database client is configured.

        Args:
            market_id: Polymarket condition ID.
            pnl_usd:   Realized PnL in USD (positive = profit, negative = loss).
            trade_id:  Trade identifier for DB persistence (optional).

        Returns:
            Updated :class:`PnLRecord` for *market_id*.
        """
        rec = self._get_or_create(market_id)
        rec.realized = round(rec.realized + pnl_usd, 4)
        rec.updated_at = time.time()

        log.info(
            "pnl_realized",
            market_id=market_id,
            trade_id=trade_id or "n/a",
            pnl_usd=round(pnl_usd, 4),
            cumulative_realized=rec.realized,
        )

        if self._db is not None and trade_id:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(
                        self._persist_realized(trade_id, pnl_usd)
                    )
            except RuntimeError:
                log.warning(
                    "pnl_persist_skipped_no_event_loop",
                    trade_id=trade_id,
                    pnl_usd=round(pnl_usd, 4),
                )

        return rec

    def record_unrealized(
        self,
        market_id: str,
        pnl_usd: float,
    ) -> PnLRecord:
        """Update unrealized (mark-to-market) PnL for an open position.

        Args:
            market_id: Polymarket condition ID.
            pnl_usd:   Current unrealized PnL in USD.

        Returns:
            Updated :class:`PnLRecord` for *market_id*.
        """
        rec = self._get_or_create(market_id)
        rec.unrealized = round(pnl_usd, 4)
        rec.updated_at = time.time()

        log.info(
            "pnl_unrealized",
            market_id=market_id,
            unrealized_pnl_usd=round(pnl_usd, 4),
        )
        return rec

    # ── Reads ─────────────────────────────────────────────────────────────────

    def get(self, market_id: str) -> Optional[PnLRecord]:
        """Return the PnL record for *market_id*, or ``None``."""
        return self._records.get(market_id)

    def summary(self) -> dict:
        """Return aggregated PnL summary across all tracked markets.

        Returns:
            Dict with keys: ``total_realized``, ``total_unrealized``,
            ``total_pnl``, ``market_count``.
        """
        total_realized = round(sum(r.realized for r in self._records.values()), 4)
        total_unrealized = round(sum(r.unrealized for r in self._records.values()), 4)
        return {
            "total_realized": total_realized,
            "total_unrealized": total_unrealized,
            "total_pnl": round(total_realized + total_unrealized, 4),
            "market_count": len(self._records),
        }

    def reset(self) -> None:
        """Clear all PnL records (for testing only)."""
        self._records.clear()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _get_or_create(self, market_id: str) -> PnLRecord:
        if market_id not in self._records:
            self._records[market_id] = PnLRecord(market_id=market_id)
        return self._records[market_id]

    async def _persist_realized(self, trade_id: str, pnl_usd: float) -> None:
        """Attempt to persist realized PnL to the database (2 retries)."""
        import asyncio

        for attempt in range(2):
            try:
                await self._db.update_trade_status(
                    trade_id,
                    status="closed",
                    pnl=pnl_usd,
                )
                log.info(
                    "pnl_persisted",
                    trade_id=trade_id,
                    pnl_usd=round(pnl_usd, 4),
                )
                return
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "pnl_persist_failed",
                    trade_id=trade_id,
                    attempt=attempt + 1,
                    error=str(exc),
                )
                if attempt == 0:
                    await asyncio.sleep(0.5)

        log.error(
            "pnl_persist_error",
            trade_id=trade_id,
            pnl_usd=round(pnl_usd, 4),
            message="DB write failed after 2 attempts — PnL lost from DB",
        )
