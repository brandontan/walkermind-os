"""Positions handler — returns (text, keyboard) for the open positions screen.

PositionManager and MarketMetadataCache are injected at bot startup via
:func:`set_position_manager` and :func:`set_market_cache`.

Return type: tuple[str, InlineKeyboard]
"""
from __future__ import annotations

from typing import Optional, TYPE_CHECKING

import structlog

from ..ui.keyboard import build_status_menu
from ..ui.screens import positions_screen

if TYPE_CHECKING:
    from ...core.portfolio.position_manager import PositionManager
    from ...core.market.market_cache import MarketMetadataCache

log = structlog.get_logger(__name__)

# Module-level service references — injected at bot startup
_position_manager: Optional["PositionManager"] = None
_market_cache: Optional["MarketMetadataCache"] = None
_pnl_tracker: Optional[object] = None  # Optional PnLTracker for unrealized PnL


def set_position_manager(pm: "PositionManager") -> None:
    """Inject the PositionManager instance."""
    global _position_manager  # noqa: PLW0603
    _position_manager = pm
    log.info("positions_handler_position_manager_injected")


def set_market_cache(cache: "MarketMetadataCache") -> None:
    """Inject the MarketMetadataCache instance."""
    global _market_cache  # noqa: PLW0603
    _market_cache = cache
    log.info("positions_handler_market_cache_injected")


def set_pnl_tracker(tracker: object) -> None:
    """Inject the PnLTracker instance for unrealized PnL per market."""
    global _pnl_tracker  # noqa: PLW0603
    _pnl_tracker = tracker
    log.info("positions_handler_pnl_tracker_injected")


async def handle_positions() -> tuple[str, list]:
    """Return open positions screen.

    Lists all open positions with market question, side, avg price, size,
    and unrealized PnL.

    Returns:
        ``(screen_text, keyboard)`` tuple.
    """
    if _position_manager is None:
        log.warning("positions_handler_no_manager")
        return positions_screen(positions=[]), build_status_menu()

    try:
        raw_positions = _position_manager.all_positions()
    except Exception as exc:
        log.error("positions_handler_fetch_error", error=str(exc))
        return positions_screen(positions=[]), build_status_menu()

    if not raw_positions:
        log.info("positions_handler_no_open_positions")
        return positions_screen(positions=[]), build_status_menu()

    positions: list[dict] = []
    for pos in raw_positions:
        question = pos.market_id  # default fallback
        if _market_cache is not None:
            try:
                question = _market_cache.get_question(pos.market_id, fallback=pos.market_id)
            except Exception:
                pass  # non-fatal: use market_id as fallback

        unrealized_pnl = 0.0
        if _pnl_tracker is not None:
            try:
                rec = _pnl_tracker.get(pos.market_id)
                if rec is not None:
                    unrealized_pnl = rec.unrealized
            except Exception:
                pass  # non-fatal

        positions.append(
            {
                "market_id": pos.market_id,
                "question": question,
                "side": pos.side,
                "avg_price": pos.avg_price,
                "size": pos.size,
                "unrealized_pnl": unrealized_pnl,
            }
        )

    log.info("positions_handler_response", count=len(positions))
    return positions_screen(positions=positions), build_status_menu()
