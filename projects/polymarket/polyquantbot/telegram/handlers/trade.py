"""telegram.handlers.trade — Trade and positions UI handler for PolyQuantBot.

Displays active paper positions with unrealized PnL and per-position detail
screens.  Dependencies are injected at bot startup.

Return type for all handlers: tuple[str, list]  (text, InlineKeyboard)
"""
from __future__ import annotations

from typing import Optional, TYPE_CHECKING

import structlog

from ..ui.keyboard import build_status_menu

if TYPE_CHECKING:
    from ...execution.paper_engine import PaperEngine
    from ...core.positions import PaperPositionManager
    from ...core.portfolio.pnl import PnLTracker

log = structlog.get_logger(__name__)

# Module-level injected dependencies
_paper_engine: Optional["PaperEngine"] = None
_position_manager: Optional["PaperPositionManager"] = None
_pnl_tracker: Optional["PnLTracker"] = None


def set_paper_engine(engine: "PaperEngine") -> None:
    """Inject PaperEngine instance at bot startup."""
    global _paper_engine  # noqa: PLW0603
    _paper_engine = engine
    log.info("trade_handler_paper_engine_injected")


def set_position_manager(pm: "PaperPositionManager") -> None:
    """Inject PaperPositionManager instance at bot startup."""
    global _position_manager  # noqa: PLW0603
    _position_manager = pm
    log.info("trade_handler_position_manager_injected")


def set_pnl_tracker(tracker: "PnLTracker") -> None:
    """Inject PnLTracker instance at bot startup."""
    global _pnl_tracker  # noqa: PLW0603
    _pnl_tracker = tracker
    log.info("trade_handler_pnl_tracker_injected")


async def handle_trade(mode: str = "default") -> tuple[str, list]:
    """Return active positions screen with unrealized PnL.

    Args:
        mode: Display mode hint (unused, reserved for future use).

    Returns:
        ``(text, keyboard)`` tuple.
    """
    if _position_manager is None:
        log.warning("trade_handler_no_position_manager")
        return "⚠️ *Paper Trading*\n\n_Position manager not available._", build_status_menu()

    try:
        open_positions = _position_manager.get_all_open()
    except Exception as exc:
        log.error("trade_handler_fetch_positions_error", error=str(exc))
        return "❌ *Error loading positions*", build_status_menu()

    if not open_positions:
        text = (
            "📊 *Paper Positions*\n\n"
            "_No open positions._\n\n"
            "Use the bot to execute a paper trade."
        )
        return text, build_status_menu()

    total_unrealized = sum(p.unrealized_pnl for p in open_positions)
    pnl_summary = _get_pnl_summary()

    lines = ["📊 *Paper Positions*\n"]
    for pos in open_positions:
        pnl_sign = "+" if pos.unrealized_pnl >= 0 else ""
        lines.append(
            f"• `{_truncate(pos.market_id, 20)}` — {pos.side} "
            f"${pos.size:.2f} @ {pos.entry_price:.4f}\n"
            f"  └ Unrealized: {pnl_sign}{pos.unrealized_pnl:.4f} USD"
        )

    lines.append(
        f"\n💹 *Total Unrealized:* "
        f"{'+'if total_unrealized >= 0 else ''}{total_unrealized:.4f} USD"  # noqa: E275
    )

    if pnl_summary:
        lines.append(
            f"✅ *Realized PnL:* {pnl_summary['total_realized']:+.4f} USD"
        )

    text = "\n".join(lines)
    log.info("trade_handler_positions_displayed", count=len(open_positions))
    return text, build_status_menu()


async def handle_trade_detail(market_id: str) -> tuple[str, list]:
    """Return single position detail screen.

    Args:
        market_id: Polymarket condition ID.

    Returns:
        ``(text, keyboard)`` tuple.
    """
    if _position_manager is None:
        log.warning("trade_handler_detail_no_manager", market_id=market_id)
        return "⚠️ _Position manager not available._", build_status_menu()

    try:
        pos = _position_manager.get_position(market_id)
    except Exception as exc:
        log.error(
            "trade_handler_detail_fetch_error",
            market_id=market_id,
            error=str(exc),
        )
        return "❌ *Error loading position*", build_status_menu()

    if pos is None:
        return (
            f"⚠️ *Position Not Found*\n\n"
            f"`{market_id}`\n\n"
            f"_Position may have been closed._"
        ), build_status_menu()

    pnl_sign = "+" if pos.unrealized_pnl >= 0 else ""
    text = (
        f"📌 *Position Detail*\n\n"
        f"Market: `{pos.market_id}`\n"
        f"Side: *{pos.side}*\n"
        f"Size: ${pos.size:.4f}\n"
        f"Entry Price: {pos.entry_price:.6f}\n"
        f"Current Price: {pos.current_price:.6f}\n"
        f"Unrealized PnL: {pnl_sign}{pos.unrealized_pnl:.4f} USD\n"
        f"Status: {pos.status}\n"
        f"Opened: {_format_ts(pos.opened_at)}"
    )

    log.info("trade_handler_detail_displayed", market_id=market_id)
    return text, build_status_menu()


# ── Internal helpers ──────────────────────────────────────────────────────────


def _get_pnl_summary() -> dict | None:
    """Return PnL summary dict or None if tracker unavailable."""
    if _pnl_tracker is None:
        return None
    try:
        return _pnl_tracker.summary()
    except Exception as exc:
        log.warning("trade_handler_pnl_summary_error", error=str(exc))
        return None


def _truncate(s: str, max_len: int) -> str:
    """Truncate a string with ellipsis if it exceeds *max_len*."""
    return s if len(s) <= max_len else s[: max_len - 1] + "…"


def _format_ts(ts: float) -> str:
    """Format a UNIX timestamp as a human-readable string."""
    import datetime

    try:
        dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return str(ts)
