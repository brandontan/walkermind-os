"""Performance tracker — Phase 6. Unchanged from Phase 5."""
from __future__ import annotations

from typing import Any

import structlog

from .state_manager import StateManager

log = structlog.get_logger()


class PerformanceTracker:
    """Tracks execution quality and trade performance metrics."""

    def __init__(self, state: StateManager) -> None:
        """Initialise with state manager for DB persistence."""
        self._state = state
        self._fills_total: int = 0
        self._fills_success: int = 0
        self._slippage_sum: float = 0.0
        self._latency_sum: int = 0
        self._latency_count: int = 0

    async def record(self, pnl: float, ev: float) -> None:
        """Persist a closed trade result to the DB."""
        await self._state.record_performance(pnl=pnl, ev=ev, is_win=pnl > 0)

    def record_execution(
        self,
        ev_expected: float,
        ev_realized: float,
        slippage_pct: float,
        latency_ms: int,
        filled: bool,
    ) -> None:
        """Accumulate execution quality metrics in memory."""
        self._fills_total += 1
        if filled:
            self._fills_success += 1
        self._slippage_sum += slippage_pct
        self._latency_sum += latency_ms
        self._latency_count += 1
        ev_ratio = ev_realized / max(ev_expected, 1e-9)
        log.info(
            "execution_metric",
            ev_expected=round(ev_expected, 4),
            ev_realized=round(ev_realized, 4),
            ev_ratio=round(ev_ratio, 4),
            slippage_pct=round(slippage_pct, 4),
            latency_ms=latency_ms,
            filled=filled,
        )

    async def snapshot(self) -> dict[str, Any]:
        """Return combined trade + execution metrics."""
        stats = await self._state.get_performance()
        fill_rate = self._fills_success / max(self._fills_total, 1)
        avg_slippage = self._slippage_sum / max(self._fills_total, 1)
        avg_latency = self._latency_sum / max(self._latency_count, 1)
        full = {
            **stats,
            "fill_rate": round(fill_rate, 4),
            "avg_slippage_pct": round(avg_slippage, 4),
            "avg_exec_latency_ms": round(avg_latency, 1),
        }
        log.info("performance_snapshot", **full)
        return full
