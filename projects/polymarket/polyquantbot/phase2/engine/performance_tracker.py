"""
Performance tracker — Phase 2.
Thin wrapper around state_manager stats.
Provides formatted snapshot for logging and Telegram.
"""

import structlog
from engine.state_manager import StateManager

log = structlog.get_logger()


class PerformanceTracker:
    def __init__(self, state: StateManager) -> None:
        """Initialise with a connected StateManager instance."""
        self.state = state

    async def record(self, pnl: float, ev: float) -> None:
        """Record a closed trade result."""
        is_win = pnl > 0
        await self.state.record_performance(pnl=pnl, ev=ev, is_win=is_win)

    async def snapshot(self) -> dict:
        """Return current performance stats and log them."""
        stats = await self.state.get_performance()
        log.info("performance_snapshot", **stats)
        return stats
