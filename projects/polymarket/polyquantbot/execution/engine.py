from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import structlog

from .models import Position
from .analytics import PerformanceTracker
from .trade_trace import TradeTraceEngine

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ExecutionSnapshot:
    positions: tuple[Position, ...]
    cash: float
    equity: float
    realized_pnl: float
    unrealized_pnl: float


class ExecutionEngine:
    """Paper-only execution engine with sizing, PnL tracking, and performance analytics."""

    def __init__(self, starting_equity: float = 10_000.0) -> None:
        self._lock = asyncio.Lock()
        self._positions: dict[str, Position] = {}
        self._cash: float = float(starting_equity)
        self._equity: float = float(starting_equity)
        self._realized_pnl: float = 0.0
        self._unrealized_pnl: float = 0.0
        self.max_position_size_ratio: float = 0.10
        self.max_total_exposure_ratio: float = 0.30
        self._analytics = PerformanceTracker()
        self._trace_engine = TradeTraceEngine()

    async def open_position(self, market: str, side: str, price: float, size: float) -> Position | None:
        """Create position object and update paper portfolio if risk allows."""
        async with self._lock:
            size = float(size)
            if size <= 0:
                log.warning("execution_engine_open_rejected", reason="size_non_positive", size=size)
                return None
            equity_base = max(self._equity, 0.0)
            max_position_size = equity_base * self.max_position_size_ratio
            if size > max_position_size:
                log.warning(
                    "execution_engine_open_rejected",
                    reason="max_position_size_exceeded",
                    requested=size,
                    limit=max_position_size,
                    equity=equity_base,
                )
                return None
            if self._current_total_exposure() + size > equity_base * self.max_total_exposure_ratio:
                log.warning(
                    "execution_engine_open_rejected",
                    reason="max_total_exposure_exceeded",
                    requested=size,
                    current_exposure=self._current_total_exposure(),
                    limit=equity_base * self.max_total_exposure_ratio,
                )
                return None
            if self._cash < size:
                log.warning(
                    "execution_engine_open_rejected",
                    reason="insufficient_cash",
                    requested=size,
                    cash=self._cash,
                )
                return None

            position = Position(
                market_id=market,
                side=side.upper(),
                entry_price=float(price),
                current_price=float(price),
                size=size,
                pnl=0.0,
            )
            self._positions[market] = position
            self._cash -= size
            self._recalculate_unrealized()
            self._refresh_equity()
            log.info("execution_engine_position_opened", market=market, side=side, price=price, size=size)
            return position

    async def close_position(self, position: Position, price: float) -> float:
        """Close position, realize PnL, and update portfolio."""
        async with self._lock:
            live_position = self._positions.get(position.market_id)
            if live_position is None:
                log.warning("execution_engine_close_ignored", reason="position_not_found", market=position.market_id)
                return 0.0

            realized_pnl = live_position.update_price(float(price))
            self._realized_pnl += realized_pnl
            self._cash += live_position.size + realized_pnl
            self._analytics.record_trade(live_position)
            del self._positions[live_position.market_id]
            self._recalculate_unrealized()
            self._refresh_equity()
            log.info("execution_engine_position_closed", market=live_position.market_id, close_price=price, pnl=realized_pnl)
            return realized_pnl

    async def update_mark_to_market(self, market_prices: dict[str, float]) -> float:
        """Update all open positions unrealized PnL from market prices."""
        async with self._lock:
            for market_id, position in self._positions.items():
                maybe_price = market_prices.get(market_id)
                if maybe_price is None:
                    continue
                position.update_price(float(maybe_price))
            self._recalculate_unrealized()
            self._refresh_equity()
            return self._unrealized_pnl

    async def snapshot(self) -> ExecutionSnapshot:
        async with self._lock:
            return ExecutionSnapshot(
                positions=tuple(self._positions.values()),
                cash=self._cash,
                equity=self._equity,
                realized_pnl=self._realized_pnl,
                unrealized_pnl=self._unrealized_pnl,
            )

    def _current_total_exposure(self) -> float:
        return sum(pos.exposure() for pos in self._positions.values())

    def _recalculate_unrealized(self) -> None:
        self._unrealized_pnl = sum(pos.pnl for pos in self._positions.values())

    def _refresh_equity(self) -> None:
        locked_notional = self._current_total_exposure()
        self._equity = self._cash + locked_notional + self._unrealized_pnl

    def get_analytics(self) -> PerformanceTracker:
        """Expose analytics for UI integration."""
        return self._analytics


_engine_singleton: ExecutionEngine | None = None


def get_execution_engine() -> ExecutionEngine:
    global _engine_singleton  # noqa: PLW0603
    if _engine_singleton is None:
        _engine_singleton = ExecutionEngine()
    return _engine_singleton


async def export_execution_payload() -> dict[str, Any]:
    snapshot = await get_execution_engine().snapshot()
    return {
        "positions": [
            {
                "market_id": pos.market_id,
                "side": pos.side,
                "entry_price": pos.entry_price,
                "current_price": pos.current_price,
                "size": pos.size,
                "pnl": pos.pnl,
                "unrealized_pnl": pos.pnl,
            }
            for pos in snapshot.positions
        ],
        "cash": snapshot.cash,
        "equity": snapshot.equity,
        "realized": snapshot.realized_pnl,
        "unrealized": snapshot.unrealized_pnl,
    }