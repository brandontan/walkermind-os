"""Performance tracker — unchanged from Phase 2."""
from __future__ import annotations

from typing import Any

import structlog

log = structlog.get_logger()


class PerformanceTracker:
    """Tracks win/loss metrics in memory."""

    def __init__(self) -> None:
        """Initialise counters."""
        self._total: int = 0
        self._wins: int = 0
        self._total_pnl: float = 0.0
        self._ev_sum: float = 0.0

    def record(self, pnl: float, ev: float) -> None:
        """Record a closed trade result."""
        self._total += 1
        self._total_pnl += pnl
        self._ev_sum += ev
        if pnl > 0:
            self._wins += 1

    def snapshot(self) -> dict[str, Any]:
        """Return current performance stats and log them."""
        win_rate = self._wins / self._total if self._total > 0 else 0.0
        avg_ev = self._ev_sum / self._total if self._total > 0 else 0.0
        stats = {
            "total_trades": self._total,
            "winning_trades": self._wins,
            "total_pnl": round(self._total_pnl, 4),
            "win_rate": round(win_rate, 4),
            "avg_ev": round(avg_ev, 4),
        }
        log.info("performance_snapshot", **stats)
        return stats
