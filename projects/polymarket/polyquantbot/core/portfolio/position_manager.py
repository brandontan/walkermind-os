"""core.portfolio.position_manager — Open position tracker for PolyQuantBot.

Tracks open positions per market, computes weighted average entry price, and
supports multiple partial fills on the same market.

Interfaces::

    Position(market_id, side, avg_price, size, trade_ids)
    PositionManager.open(market_id, side, fill_price, fill_size, trade_id)
    PositionManager.close(market_id, close_price)   → realized_pnl
    PositionManager.get(market_id)                   → Position | None
    PositionManager.all_positions()                  → list[Position]

Design:
  - Thread-safety: single asyncio event loop only.
  - Idempotent: opening the same trade_id twice is a no-op.
  - Zero silent failure: every operation is logged.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import structlog

log = structlog.get_logger()


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class Position:
    """A single open position on a Polymarket market.

    Attributes:
        market_id:   Polymarket condition ID.
        side:        "YES" or "NO".
        avg_price:   Weighted average entry price.
        size:        Total position size in USD.
        opened_at:   UNIX timestamp of first fill.
        trade_ids:   All trade IDs that contributed to this position.
    """

    market_id: str
    side: str
    avg_price: float
    size: float
    opened_at: float = field(default_factory=time.time)
    trade_ids: List[str] = field(default_factory=list)


# ── Manager ───────────────────────────────────────────────────────────────────

class PositionManager:
    """In-memory open position tracker.

    Supports multiple partial fills per market and computes a running weighted
    average entry price.  Each market can have at most one open position (a new
    fill on the same market/side *adds* to the existing position; a fill on the
    opposite side raises ``ValueError``).
    """

    def __init__(self) -> None:
        # market_id → Position
        self._positions: Dict[str, Position] = {}
        # dedup: trade_ids that have already been recorded
        self._seen_trades: set = set()

    # ── Writes ────────────────────────────────────────────────────────────────

    def open(
        self,
        market_id: str,
        side: str,
        fill_price: float,
        fill_size: float,
        trade_id: str = "",
    ) -> Position:
        """Record a fill, creating or updating the position for *market_id*.

        Args:
            market_id:  Polymarket condition ID.
            side:       "YES" or "NO".
            fill_price: Execution price for this fill.
            fill_size:  USD size filled.
            trade_id:   Unique trade identifier (used for dedup).

        Returns:
            Updated or newly created :class:`Position`.

        Raises:
            ValueError: When *side* conflicts with the existing position's side.
        """
        if trade_id and trade_id in self._seen_trades:
            log.info(
                "position_open_duplicate",
                trade_id=trade_id,
                market_id=market_id,
            )
            return self._positions[market_id]

        if fill_size <= 0:
            log.warning(
                "position_open_zero_size",
                market_id=market_id,
                side=side,
                fill_price=fill_price,
                fill_size=fill_size,
            )
            return self._positions.get(market_id) or Position(
                market_id=market_id,
                side=side,
                avg_price=fill_price,
                size=0.0,
            )

        existing = self._positions.get(market_id)
        if existing is not None:
            # existing.side is always stored as uppercase (see below), so this
            # comparison is symmetric.
            if existing.side != side.upper():
                raise ValueError(
                    f"Cannot add {side} fill to existing {existing.side} position "
                    f"for market {market_id!r}. Close the position first."
                )
            # Update weighted avg price
            total_size = existing.size + fill_size
            new_avg = (existing.avg_price * existing.size + fill_price * fill_size) / total_size
            existing.avg_price = round(new_avg, 6)
            existing.size = round(total_size, 4)
            if trade_id:
                existing.trade_ids.append(trade_id)
            pos = existing
        else:
            pos = Position(
                market_id=market_id,
                side=side.upper(),
                avg_price=round(fill_price, 6),
                size=round(fill_size, 4),
                opened_at=time.time(),
                trade_ids=[trade_id] if trade_id else [],
            )
            self._positions[market_id] = pos

        if trade_id:
            self._seen_trades.add(trade_id)

        log.info(
            "position_opened",
            market_id=market_id,
            side=pos.side,
            avg_price=pos.avg_price,
            size=pos.size,
            trade_id=trade_id or "n/a",
        )
        return pos

    def close(
        self,
        market_id: str,
        close_price: float,
    ) -> Tuple[Optional[Position], float]:
        """Close an open position and return the realized PnL.

        Args:
            market_id:   Polymarket condition ID.
            close_price: Price at which the position is closed.

        Returns:
            ``(closed_position, realized_pnl_usd)`` tuple.
            If no position is open, returns ``(None, 0.0)``.
        """
        pos = self._positions.pop(market_id, None)
        if pos is None:
            log.warning(
                "position_close_not_found",
                market_id=market_id,
                close_price=close_price,
            )
            return None, 0.0

        # For YES: pnl = (close_price - avg_price) * size
        # For NO:  pnl = (avg_price - close_price) * size  (inverted payoff)
        if pos.side == "YES":
            realized_pnl = (close_price - pos.avg_price) * pos.size
        else:
            realized_pnl = (pos.avg_price - close_price) * pos.size

        realized_pnl = round(realized_pnl, 4)

        log.info(
            "position_closed",
            market_id=market_id,
            side=pos.side,
            avg_price=pos.avg_price,
            close_price=close_price,
            size=pos.size,
            realized_pnl=realized_pnl,
        )
        return pos, realized_pnl

    # ── Reads ─────────────────────────────────────────────────────────────────

    def get(self, market_id: str) -> Optional[Position]:
        """Return the open position for *market_id*, or ``None``."""
        return self._positions.get(market_id)

    def all_positions(self) -> List[Position]:
        """Return all currently open positions."""
        return list(self._positions.values())

    def count(self) -> int:
        """Return number of open positions."""
        return len(self._positions)

    def unrealized_pnl(self, market_id: str, mark_price: float) -> float:
        """Compute unrealized PnL for a market at *mark_price*.

        Args:
            market_id:  Polymarket condition ID.
            mark_price: Current mid price for mark-to-market.

        Returns:
            Unrealized PnL in USD, or 0.0 if no position is open.
        """
        pos = self._positions.get(market_id)
        if pos is None:
            return 0.0
        if pos.side == "YES":
            return round((mark_price - pos.avg_price) * pos.size, 4)
        return round((pos.avg_price - mark_price) * pos.size, 4)

    def reset(self) -> None:
        """Clear all positions (for testing only)."""
        self._positions.clear()
        self._seen_trades.clear()
