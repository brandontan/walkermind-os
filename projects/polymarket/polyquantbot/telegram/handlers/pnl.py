"""PnL handler — returns (text, keyboard) for the PnL summary screen.

PnLTracker is injected at bot startup via :func:`set_pnl_tracker`.

Return type: tuple[str, InlineKeyboard]
"""
from __future__ import annotations

from typing import Optional, TYPE_CHECKING

import structlog

from ..ui.keyboard import build_status_menu
from ..ui.screens import pnl_screen

if TYPE_CHECKING:
    from ...core.portfolio.pnl import PnLTracker

log = structlog.get_logger(__name__)

# Module-level PnLTracker reference — injected at bot startup
_pnl_tracker: Optional["PnLTracker"] = None


def set_pnl_tracker(tracker: "PnLTracker") -> None:
    """Inject the PnLTracker instance."""
    global _pnl_tracker  # noqa: PLW0603
    _pnl_tracker = tracker
    log.info("pnl_handler_pnl_tracker_injected")


async def handle_pnl() -> tuple[str, list]:
    """Return PnL summary screen.

    Shows realized, unrealized, and total PnL aggregated across all markets.

    Returns:
        ``(screen_text, keyboard)`` tuple.
    """
    if _pnl_tracker is None:
        log.warning("pnl_handler_no_tracker")
        return pnl_screen(realized=0.0, unrealized=0.0, total=0.0), build_status_menu()

    try:
        summary = _pnl_tracker.summary()
        realized = summary.get("total_realized", 0.0)
        unrealized = summary.get("total_unrealized", 0.0)
        total = summary.get("total_pnl", 0.0)

        log.info(
            "pnl_handler_response",
            realized=round(realized, 4),
            unrealized=round(unrealized, 4),
            total=round(total, 4),
        )
        return pnl_screen(realized=realized, unrealized=unrealized, total=total), build_status_menu()
    except Exception as exc:
        log.error("pnl_handler_error", error=str(exc))
        return pnl_screen(realized=0.0, unrealized=0.0, total=0.0), build_status_menu()
