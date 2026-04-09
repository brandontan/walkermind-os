from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import statistics
from typing import Any
import uuid

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
    implied_prob: float
    volatility: float


class ExecutionEngine:
    """Paper-only execution engine with sizing, PnL tracking, and performance analytics."""

    def __init__(self, starting_equity: float = 10_000.0) -> None:
        self._lock = asyncio.Lock()
        self._positions: dict[str, Position] = {}
        self._cash: float = float(starting_equity)
        self._equity: float = float(starting_equity)
        self._realized_pnl: float = 0.0
        self._unrealized_pnl: float = 0.0
        self._implied_prob: float = 0.50
        self._volatility: float = 0.10
        self.max_position_size_ratio: float = 0.10
        self.max_total_exposure_ratio: float = 0.30
        self._analytics = PerformanceTracker()
        self._trace_engine = TradeTraceEngine()
        self._closed_trades: list[dict[str, Any]] = {}
        self._position_context: dict[str, dict[str, Any]] = {}

    async def open_position(
        self,
        market: str,
        market_title: str,
        side: str,
        price: float,
        size: float,
        position_id: str | None = None,
        position_context: dict[str, Any] | None = None,
    ) -> Position | None:
        """Create position object and update paper portfolio if risk allows."""
        async with self._lock:
            log.warning("execution_engine_direct_call_blocked", action="open_position")
            raise RuntimeError("Direct execution engine access is blocked. Use ExecutionGateway.submit_execution_request instead.")

    async def close_position(
        self,
        position: Position,
        price: float,
        close_context: dict[str, Any] | None = None,
    ) -> float:
        """Close position, realize PnL, and update portfolio."""
        async with self._lock:
            log.warning("execution_engine_direct_call_blocked", action="close_position")
            raise RuntimeError("Direct execution engine access is blocked. Use ExecutionGateway.close_position instead.")

    async def update_mark_to_market(self, market_prices: dict[str, float]) -> float:
        """Update all open positions unrealized PnL from market prices."""
        async with self._lock:
            normalized_prices: list[float] = []
            for market_id, position in self._positions.items():
                maybe_price = market_prices.get(market_id)
                if maybe_price is None:
                    continue
                normalized = max(0.01, min(0.99, float(maybe_price)))
                normalized_prices.append(normalized)
                position.update_price(normalized)
            if normalized_prices:
                self._implied_prob = max(0.01, min(0.99, float(sum(normalized_prices) / len(normalized_prices))))
                self._volatility = max(0.01, float(statistics.pstdev(normalized_prices)) if len(normalized_prices) > 1 else 0.10)
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
                implied_prob=self._implied_prob,
                volatility=self._volatility,
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