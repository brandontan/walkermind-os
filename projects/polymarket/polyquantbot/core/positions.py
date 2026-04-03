"""core.positions — Paper trading position lifecycle manager for PolyQuantBot.

Manages open/closed paper positions with weighted average entry price,
unrealized PnL tracking, and partial-fill support.

Interfaces::

    PaperPosition(market_id, side, size, entry_price, current_price,
                  unrealized_pnl, status, opened_at, closed_at)
    PaperPositionManager.open_position(market_id, side, size, entry_price, trade_id)
    PaperPositionManager.update_price(market_id, current_price)
    PaperPositionManager.close_position(market_id, close_price, trade_id)
    PaperPositionManager.partial_fill(market_id, add_size, fill_price, trade_id)
    PaperPositionManager.get_position(market_id)   → PaperPosition | None
    PaperPositionManager.get_all_open()            → list[PaperPosition]

Design:
  - Thread-safety: asyncio event loop only (no threading).
  - Idempotent: duplicate trade_ids are silently skipped.
  - Zero silent failure: every unusual path is logged.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

import structlog

log = structlog.get_logger(__name__)


# ── Enums ─────────────────────────────────────────────────────────────────────


class PositionStatus(str, Enum):
    """Lifecycle status of a paper position."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"


# ── Data model ────────────────────────────────────────────────────────────────


@dataclass
class PaperPosition:
    """A single paper position on a Polymarket market.

    Attributes:
        market_id:       Polymarket condition ID.
        side:            "YES" or "NO".
        size:            Total position size in USD.
        entry_price:     Weighted average entry price.
        current_price:   Latest mark-to-market price.
        unrealized_pnl:  Current unrealized PnL in USD.
        status:          OPEN or CLOSED.
        opened_at:       UNIX timestamp when position was first opened.
        closed_at:       UNIX timestamp when position was closed (or None).
        trade_ids:       All trade IDs that contributed to this position.
    """

    market_id: str
    side: str
    size: float
    entry_price: float
    current_price: float = field(default=0.0)
    unrealized_pnl: float = field(default=0.0)
    status: PositionStatus = field(default=PositionStatus.OPEN)
    opened_at: float = field(default_factory=time.time)
    closed_at: Optional[float] = field(default=None)
    trade_ids: List[str] = field(default_factory=list)


# ── Manager ───────────────────────────────────────────────────────────────────


class PaperPositionManager:
    """Full lifecycle manager for paper trading positions.

    Supports:
    - Opening a new position (idempotent by trade_id).
    - Partial fills (accumulate into an existing position).
    - Price updates for mark-to-market unrealized PnL.
    - Closing a position and returning realized PnL.
    """

    def __init__(self) -> None:
        # market_id → PaperPosition
        self._positions: Dict[str, PaperPosition] = {}
        # Closed positions (for history)
        self._closed: List[PaperPosition] = []
        # Idempotency: trade_ids already applied
        self._seen_trade_ids: Set[str] = set()

    # ── Writes ────────────────────────────────────────────────────────────────

    def open_position(
        self,
        market_id: str,
        side: str,
        size: float,
        entry_price: float,
        trade_id: str,
    ) -> PaperPosition:
        """Open a new position.

        If a position for *market_id* already exists (same side), this
        delegates to :meth:`partial_fill` to accumulate.

        Args:
            market_id:   Polymarket condition ID.
            side:        "YES" or "NO".
            size:        Position size in USD.
            entry_price: Fill price.
            trade_id:    Unique trade ID (idempotency key).

        Returns:
            The created or updated :class:`PaperPosition`.

        Raises:
            ValueError: When a conflicting side already exists for the market.
        """
        if trade_id in self._seen_trade_ids:
            log.info(
                "paper_position_open_duplicate",
                trade_id=trade_id,
                market_id=market_id,
            )
            existing = self._positions.get(market_id)
            if existing is None:
                # Position was closed — return a placeholder closed position
                for pos in self._closed:
                    if pos.market_id == market_id and trade_id in pos.trade_ids:
                        return pos
            return existing or PaperPosition(
                market_id=market_id,
                side=side.upper(),
                size=size,
                entry_price=entry_price,
            )

        existing = self._positions.get(market_id)
        if existing is not None:
            if existing.side != side.upper():
                raise ValueError(
                    f"Cannot open {side} position for market {market_id!r}: "
                    f"existing position is {existing.side}. Close it first."
                )
            # Accumulate into existing
            return self.partial_fill(
                market_id=market_id,
                add_size=size,
                fill_price=entry_price,
                trade_id=trade_id,
            )

        pos = PaperPosition(
            market_id=market_id,
            side=side.upper(),
            size=round(size, 4),
            entry_price=round(entry_price, 6),
            current_price=round(entry_price, 6),
            unrealized_pnl=0.0,
            status=PositionStatus.OPEN,
            opened_at=time.time(),
            trade_ids=[trade_id],
        )
        self._positions[market_id] = pos
        self._seen_trade_ids.add(trade_id)

        log.info(
            "paper_position_opened",
            market_id=market_id,
            side=pos.side,
            size=pos.size,
            entry_price=pos.entry_price,
            trade_id=trade_id,
        )
        return pos

    def update_price(self, market_id: str, current_price: float) -> None:
        """Update mark-to-market price and recompute unrealized PnL.

        Args:
            market_id:     Polymarket condition ID.
            current_price: Latest mid price.
        """
        pos = self._positions.get(market_id)
        if pos is None:
            log.debug("paper_position_update_price_not_found", market_id=market_id)
            return

        pos.current_price = round(current_price, 6)

        if pos.side == "YES":
            pos.unrealized_pnl = round(
                (current_price - pos.entry_price) * pos.size, 4
            )
        else:
            pos.unrealized_pnl = round(
                (pos.entry_price - current_price) * pos.size, 4
            )

        log.debug(
            "paper_position_price_updated",
            market_id=market_id,
            current_price=current_price,
            unrealized_pnl=pos.unrealized_pnl,
        )

    def close_position(
        self,
        market_id: str,
        close_price: float,
        trade_id: str,
    ) -> float:
        """Close an open position and return realized PnL.

        Args:
            market_id:   Polymarket condition ID.
            close_price: Price at close.
            trade_id:    Unique trade ID (idempotency key).

        Returns:
            Realized PnL in USD.  Returns 0.0 if no position found.
        """
        if trade_id in self._seen_trade_ids:
            log.info(
                "paper_position_close_duplicate",
                trade_id=trade_id,
                market_id=market_id,
            )
            return 0.0

        pos = self._positions.get(market_id)
        if pos is None:
            log.warning(
                "paper_position_close_not_found",
                market_id=market_id,
                close_price=close_price,
                trade_id=trade_id,
            )
            return 0.0

        if pos.side == "YES":
            realized_pnl = round((close_price - pos.entry_price) * pos.size, 4)
        else:
            realized_pnl = round((pos.entry_price - close_price) * pos.size, 4)

        pos.status = PositionStatus.CLOSED
        pos.closed_at = time.time()
        pos.current_price = round(close_price, 6)
        pos.unrealized_pnl = 0.0
        pos.trade_ids.append(trade_id)

        # Move to closed history
        self._closed.append(pos)
        del self._positions[market_id]
        self._seen_trade_ids.add(trade_id)

        log.info(
            "paper_position_closed",
            market_id=market_id,
            side=pos.side,
            entry_price=pos.entry_price,
            close_price=close_price,
            size=pos.size,
            realized_pnl=realized_pnl,
            trade_id=trade_id,
        )
        return realized_pnl

    def partial_fill(
        self,
        market_id: str,
        add_size: float,
        fill_price: float,
        trade_id: str,
    ) -> PaperPosition:
        """Add size to an existing open position (weighted avg price update).

        Args:
            market_id:  Polymarket condition ID.
            add_size:   Additional USD to add.
            fill_price: Fill price for this tranche.
            trade_id:   Unique trade ID (idempotency key).

        Returns:
            Updated :class:`PaperPosition`.
        """
        if trade_id in self._seen_trade_ids:
            log.info(
                "paper_position_partial_duplicate",
                trade_id=trade_id,
                market_id=market_id,
            )
            pos = self._positions.get(market_id)
            if pos is not None:
                return pos

        pos = self._positions.get(market_id)
        if pos is None:
            log.error(
                "paper_position_partial_no_base",
                market_id=market_id,
                trade_id=trade_id,
                message="partial_fill called with no existing position — use open_position first",
            )
            raise ValueError(
                f"partial_fill: no open position for market {market_id!r}. "
                "Call open_position() before partial_fill()."
            )

        total_size = pos.size + add_size
        new_avg = (pos.entry_price * pos.size + fill_price * add_size) / total_size
        pos.entry_price = round(new_avg, 6)
        pos.size = round(total_size, 4)
        pos.trade_ids.append(trade_id)
        self._seen_trade_ids.add(trade_id)

        log.info(
            "paper_position_partial_fill",
            market_id=market_id,
            add_size=add_size,
            fill_price=fill_price,
            new_avg_price=pos.entry_price,
            new_size=pos.size,
            trade_id=trade_id,
        )
        return pos

    # ── Reads ─────────────────────────────────────────────────────────────────

    def get_position(self, market_id: str) -> Optional[PaperPosition]:
        """Return the open position for *market_id*, or ``None``."""
        return self._positions.get(market_id)

    def get_all_open(self) -> List[PaperPosition]:
        """Return all currently open positions."""
        return list(self._positions.values())

    def get_closed(self) -> List[PaperPosition]:
        """Return all closed positions."""
        return list(self._closed)

    def reset(self) -> None:
        """Clear all positions (for testing only)."""
        self._positions.clear()
        self._closed.clear()
        self._seen_trade_ids.clear()

    # ── DB persistence hooks ──────────────────────────────────────────────────

    async def save_to_db(self, db: Any) -> None:
        """Persist all open positions to the database.

        Upserts every open position; deleted positions (closed) are removed
        from the ``paper_positions`` table.

        Args:
            db: :class:`~infra.db.database.DatabaseClient` instance.
        """
        try:
            for pos in self._positions.values():
                await db.upsert_paper_position({
                    "market_id": pos.market_id,
                    "side": pos.side,
                    "size": pos.size,
                    "entry_price": pos.entry_price,
                    "current_price": pos.current_price,
                    "unrealized_pnl": pos.unrealized_pnl,
                    "status": pos.status.value,
                    "opened_at": pos.opened_at,
                    "closed_at": pos.closed_at,
                    "trade_ids": pos.trade_ids,
                })
            log.info(
                "persistence_write",
                entity="paper_positions",
                count=len(self._positions),
            )
        except Exception as exc:
            log.error("positions_save_to_db_failed", error=str(exc))

    async def save_closed_to_db(self, db: Any, market_id: str) -> None:
        """Remove a closed position from the ``paper_positions`` table.

        Args:
            db:        :class:`~infra.db.database.DatabaseClient` instance.
            market_id: Polymarket condition ID of the closed position.
        """
        try:
            await db.delete_paper_position(market_id)
            log.info(
                "persistence_write",
                entity="paper_position_deleted",
                market_id=market_id,
            )
        except Exception as exc:
            log.error("positions_delete_from_db_failed", market_id=market_id, error=str(exc))

    async def load_from_db(self, db: Any) -> None:
        """Restore open positions from the database.

        Replaces current in-memory state with DB state.  Idempotent.

        Args:
            db: :class:`~infra.db.database.DatabaseClient` instance.
        """
        try:
            rows = await db.load_open_paper_positions()
            for row in rows:
                pos = PaperPosition(
                    market_id=str(row["market_id"]),
                    side=str(row["side"]).upper(),
                    size=float(row["size"]),
                    entry_price=float(row["entry_price"]),
                    current_price=float(row.get("current_price", 0.0)),
                    unrealized_pnl=float(row.get("unrealized_pnl", 0.0)),
                    status=PositionStatus(str(row.get("status", "OPEN")).upper()),
                    opened_at=float(row.get("opened_at", 0.0)),
                    closed_at=row.get("closed_at"),
                    trade_ids=list(row.get("trade_ids") or []),
                )
                self._positions[pos.market_id] = pos
                # Restore idempotency set from trade_ids
                for tid in pos.trade_ids:
                    self._seen_trade_ids.add(tid)

            log.info(
                "paper_positions_loaded",
                count=len(rows),
            )
        except Exception as exc:
            log.warning(
                "positions_load_from_db_failed",
                error=str(exc),
                hint="Starting with empty positions",
            )
