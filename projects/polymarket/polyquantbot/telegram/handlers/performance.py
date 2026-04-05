"""Performance handler — returns (text, keyboard) for the performance screen.

MultiStrategyMetrics and PnLTracker are injected at bot startup via the
:func:`set_multi_metrics` and :func:`set_pnl_tracker` functions.

Return type: tuple[str, InlineKeyboard]
"""
from __future__ import annotations

from typing import Optional, TYPE_CHECKING

import structlog

from ..ui.keyboard import build_status_menu
from ..ui.screens import performance_screen
from .portfolio_service import get_portfolio_service

if TYPE_CHECKING:
    from ...monitoring.multi_strategy_metrics import MultiStrategyMetrics
    from ...core.portfolio.pnl import PnLTracker

log = structlog.get_logger(__name__)

# Module-level service references — injected at bot startup
_multi_metrics: Optional["MultiStrategyMetrics"] = None
_pnl_tracker: Optional["PnLTracker"] = None


def set_multi_metrics(metrics: "MultiStrategyMetrics") -> None:
    """Inject the MultiStrategyMetrics instance."""
    global _multi_metrics  # noqa: PLW0603
    _multi_metrics = metrics
    log.info("performance_handler_multi_metrics_injected")


def set_pnl_tracker(tracker: "PnLTracker") -> None:
    """Inject the PnLTracker instance."""
    global _pnl_tracker  # noqa: PLW0603
    _pnl_tracker = tracker
    log.info("performance_handler_pnl_tracker_injected")


async def handle_performance(mode: str) -> tuple[str, list]:
    """Return performance metrics screen.

    Combines MultiStrategyMetrics aggregate data with PnLTracker summary
    to produce a comprehensive performance view.

    Args:
        mode: Trading mode string (``"PAPER"`` or ``"LIVE"``).

    Returns:
        ``(screen_text, keyboard)`` tuple.
    """
    portfolio = get_portfolio_service().get_state()
    if portfolio is None:
        return "⚠️ Data unavailable", build_status_menu()

    total_pnl = portfolio.pnl
    win_rate = 0.0
    total_trades = len(portfolio.positions)
    drawdown = 0.0

    if _multi_metrics is not None:
        try:
            perf = _multi_metrics.aggregate_performance()
            total_trades = max(total_trades, perf.get("total_trades", 0))
            win_rate = perf.get("win_rate", 0.0)
            drawdown = perf.get("drawdown", 0.0)
        except Exception as exc:
            log.error("performance_handler_metrics_error", error=str(exc))

    log.info(
        "performance_handler_response",
        mode=mode,
        total_pnl=round(total_pnl, 4),
        win_rate=round(win_rate, 4),
        total_trades=total_trades,
        drawdown=round(drawdown, 4),
    )

    text = performance_screen(
        total_pnl=total_pnl,
        total_trades=total_trades,
        mode=mode,
        win_rate=win_rate,
        drawdown=drawdown,
    )
    return text, build_status_menu()
