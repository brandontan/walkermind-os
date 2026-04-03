"""core.ledger — Trade ledger for PolyQuantBot paper trading.

Records all fills, opens, and closes with idempotency on trade_id.
Acts as the append-only audit log for the paper trading engine.

Interfaces::

    LedgerEntry(trade_id, market_id, action, price, size, fee,
                timestamp, realized_pnl)
    TradeLedger.record(entry)            — idempotent by trade_id
    TradeLedger.get_all()               → list[LedgerEntry]
    TradeLedger.get_by_market(market_id)→ list[LedgerEntry]
    TradeLedger.get_realized_pnl()      → float
    TradeLedger.get_unrealized_pnl(positions) → float

Design:
  - Append-only: entries are never modified after recording.
  - Idempotent: duplicate trade_ids are silently skipped.
  - Zero silent failure: every operation is logged.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from .positions import PaperPosition

log = structlog.get_logger(__name__)


# ── Enums ─────────────────────────────────────────────────────────────────────


class LedgerAction(str, Enum):
    """Ledger entry action type."""

    OPEN = "OPEN"
    CLOSE = "CLOSE"
    PARTIAL = "PARTIAL"


# ── Data model ────────────────────────────────────────────────────────────────


@dataclass
class LedgerEntry:
    """A single immutable record in the trade ledger.

    Attributes:
        trade_id:     Unique identifier for this ledger entry.
        market_id:    Polymarket condition ID.
        action:       OPEN, CLOSE, or PARTIAL.
        price:        Fill or close price.
        size:         USD size of the fill.
        fee:          Fee charged in USD.
        timestamp:    ISO-8601 UTC timestamp string.
        realized_pnl: Realized PnL for CLOSE actions (None otherwise).
    """

    trade_id: str
    market_id: str
    action: LedgerAction
    price: float
    size: float
    fee: float
    timestamp: str
    realized_pnl: Optional[float] = field(default=None)


# ── Ledger ────────────────────────────────────────────────────────────────────


class TradeLedger:
    """Append-only trade ledger — records every fill/open/close event.

    All entries are kept in insertion order.  Recording the same *trade_id*
    twice is a silent no-op (idempotent).
    """

    def __init__(self) -> None:
        self._entries: List[LedgerEntry] = []
        self._seen_trade_ids: Set[str] = set()
        # index: market_id → list of entry indices for fast lookup
        self._market_index: Dict[str, List[int]] = {}

    # ── Writes ────────────────────────────────────────────────────────────────

    def record(self, entry: LedgerEntry) -> None:
        """Append an entry to the ledger.

        Idempotent: if *entry.trade_id* was already recorded, the call is a
        no-op and a debug log is emitted.

        Args:
            entry: The :class:`LedgerEntry` to record.
        """
        if entry.trade_id in self._seen_trade_ids:
            log.info(
                "ledger_record_duplicate",
                trade_id=entry.trade_id,
                market_id=entry.market_id,
                action=entry.action,
            )
            return

        idx = len(self._entries)
        self._entries.append(entry)
        self._seen_trade_ids.add(entry.trade_id)

        # Update market index
        self._market_index.setdefault(entry.market_id, []).append(idx)

        log.info(
            "ledger_entry_recorded",
            trade_id=entry.trade_id,
            market_id=entry.market_id,
            action=entry.action,
            price=entry.price,
            size=entry.size,
            fee=entry.fee,
            realized_pnl=entry.realized_pnl,
        )

    # ── Reads ─────────────────────────────────────────────────────────────────

    def get_all(self) -> List[LedgerEntry]:
        """Return all ledger entries in insertion order."""
        return list(self._entries)

    def get_by_market(self, market_id: str) -> List[LedgerEntry]:
        """Return all entries for a specific market.

        Args:
            market_id: Polymarket condition ID.

        Returns:
            Entries in insertion order for *market_id*.
        """
        indices = self._market_index.get(market_id, [])
        return [self._entries[i] for i in indices]

    def get_realized_pnl(self) -> float:
        """Compute total realized PnL from all CLOSE entries.

        Returns:
            Sum of ``realized_pnl`` for all CLOSE actions in the ledger.
        """
        total = sum(
            e.realized_pnl
            for e in self._entries
            if e.action == LedgerAction.CLOSE and e.realized_pnl is not None
        )
        return round(total, 4)

    def get_unrealized_pnl(self, positions: list[PaperPosition]) -> float:
        """Compute total unrealized PnL from a list of open positions.

        Args:
            positions: List of :class:`~core.positions.PaperPosition` objects.

        Returns:
            Sum of unrealized PnL across all provided positions.
        """
        total = sum(p.unrealized_pnl for p in positions)
        return round(total, 4)

    def count(self) -> int:
        """Return total number of ledger entries."""
        return len(self._entries)

    def reset(self) -> None:
        """Clear all ledger entries (for testing only)."""
        self._entries.clear()
        self._seen_trade_ids.clear()
        self._market_index.clear()

    # ── DB persistence hooks ──────────────────────────────────────────────────

    async def persist_entry(self, entry: LedgerEntry, db: Any) -> None:
        """Persist a single ledger entry to the database.

        Called immediately after :meth:`record` so the DB stays in sync.

        Args:
            entry: The :class:`LedgerEntry` to persist.
            db:    :class:`~infra.db.database.DatabaseClient` instance.
        """
        try:
            await db.insert_ledger_entry({
                "trade_id": entry.trade_id,
                "market_id": entry.market_id,
                "action": entry.action.value,
                "price": entry.price,
                "size": entry.size,
                "fee": entry.fee,
                "realized_pnl": entry.realized_pnl,
                "ledger_ts": entry.timestamp,
            })
            log.info(
                "persistence_write",
                entity="trade_ledger",
                trade_id=entry.trade_id,
                market_id=entry.market_id,
                action=entry.action.value,
            )
        except Exception as exc:
            log.error(
                "ledger_persist_entry_failed",
                trade_id=entry.trade_id,
                error=str(exc),
            )

    async def load_from_db(self, db: Any) -> None:
        """Restore ledger entries from the database.

        Rebuilds in-memory state from all persisted records.  Idempotent.

        Args:
            db: :class:`~infra.db.database.DatabaseClient` instance.
        """
        try:
            rows = await db.load_ledger_entries(limit=5000)
            for row in rows:
                entry = LedgerEntry(
                    trade_id=str(row["trade_id"]),
                    market_id=str(row["market_id"]),
                    action=LedgerAction(str(row["action"]).upper()),
                    price=float(row["price"]),
                    size=float(row["size"]),
                    fee=float(row.get("fee", 0.0)),
                    timestamp=str(row.get("ledger_ts", "")),
                    realized_pnl=row.get("realized_pnl"),
                )
                # Use internal record to avoid duplicate log noise
                if entry.trade_id not in self._seen_trade_ids:
                    idx = len(self._entries)
                    self._entries.append(entry)
                    self._seen_trade_ids.add(entry.trade_id)
                    self._market_index.setdefault(entry.market_id, []).append(idx)

            log.info(
                "ledger_loaded_from_db",
                entries=len(rows),
            )
        except Exception as exc:
            log.warning(
                "ledger_load_from_db_failed",
                error=str(exc),
                hint="Starting with empty ledger",
            )
