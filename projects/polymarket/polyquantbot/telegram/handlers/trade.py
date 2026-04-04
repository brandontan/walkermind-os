"""telegram.handlers.trade — Trade and positions UI handler for PolyQuantBot.

Displays active paper positions with unrealized PnL using premium UI components.
All trade messages show full market context (question, not just ID).
Dependencies are injected at bot startup.

Return type for all handlers: tuple[str, list]  (text, InlineKeyboard)
"""
from __future__ import annotations

from typing import Optional, TYPE_CHECKING

import structlog

from ..ui.components import render_trade_card, render_status_bar, render_kv_line, render_insight, SEP
from ..ui.keyboard import build_status_menu

if TYPE_CHECKING:
    from ...execution.paper_engine import PaperEngine
    from ...core.positions import PaperPositionManager
    from ...core.portfolio.pnl import PnLTracker
    from ...core.system_state import SystemStateManager
    from ...core.market.market_cache import MarketMetadataCache

log = structlog.get_logger(__name__)

# Module-level injected dependencies
_paper_engine: Optional["PaperEngine"] = None
_position_manager: Optional["PaperPositionManager"] = None
_pnl_tracker: Optional["PnLTracker"] = None
_system_state: Optional["SystemStateManager"] = None
_market_cache: Optional["MarketMetadataCache"] = None
_mode: str = "PAPER"


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


def set_system_state(sm: "SystemStateManager") -> None:
    """Inject SystemStateManager at bot startup."""
    global _system_state  # noqa: PLW0603
    _system_state = sm
    log.info("trade_handler_system_state_injected")


def set_market_cache(cache: "MarketMetadataCache") -> None:
    """Inject MarketMetadataCache at bot startup."""
    global _market_cache  # noqa: PLW0603
    _market_cache = cache
    log.info("trade_handler_market_cache_injected")


def set_mode(mode: str) -> None:
    """Update trading mode string."""
    global _mode  # noqa: PLW0603
    _mode = mode


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve_market_question(market_id: str) -> str:
    """Resolve market_id to human-readable question string.

    Falls back to market_id if cache miss or unavailable.
    """
    if _market_cache is None:
        return market_id
    try:
        meta = _market_cache.get(market_id)
        if meta is not None:
            question = getattr(meta, "question", None)
            if question:
                return question
    except Exception as exc:
        log.warning("trade_handler_market_question_error", market_id=market_id, error=str(exc))
    return market_id


def _get_status_bar() -> str:
    sys_state = "RUNNING"
    if _system_state is not None:
        try:
            snap = _system_state.snapshot()
            sys_state = snap.get("state", "RUNNING")
        except Exception:
            pass
    return render_status_bar(state=sys_state, mode=_mode)


# ── Handlers ──────────────────────────────────────────────────────────────────


async def handle_trade(mode: str = "default") -> tuple[str, list]:
    """Return active positions screen with unrealized PnL using premium cards.

    Shows per-position trade cards with: market question (not ID), side,
    entry price, current price, size, unrealized PnL, fill %, wallet state.

    Args:
        mode: Display mode hint (unused, reserved for future use).

    Returns:
        ``(text, keyboard)`` tuple.
    """
    status_bar = _get_status_bar()

    if _position_manager is None:
        log.warning("trade_handler_no_position_manager")
        return (
            "\n".join([
                status_bar,
                SEP,
                "⚠️ *SYSTEM NOTICE*",
                SEP,
                render_kv_line("STATUS", "Manager unavailable"),
                "_Position manager not injected._",
                SEP,
                render_insight("System not ready — restart bot"),
            ]),
            build_status_menu(),
        )

    try:
        open_positions = _position_manager.get_all_open()
    except Exception as exc:
        log.error("trade_handler_fetch_positions_error", error=str(exc))
        return (
            "\n".join([
                status_bar,
                SEP,
                "⚠️ *SYSTEM NOTICE*",
                SEP,
                render_kv_line("STATUS", "Positions fetch error"),
                f"_{exc}_",
                SEP,
                render_insight("Positions unavailable — retry shortly"),
            ]),
            build_status_menu(),
        )

    # ── No open positions ─────────────────────────────────────────────────────
    if not open_positions:
        realized_pnl = 0.0
        if _pnl_tracker is not None:
            try:
                summary = _pnl_tracker.summary()
                realized_pnl = summary.get("total_realized", 0.0)
            except Exception:
                pass

        # Check ledger for realized PnL
        if realized_pnl == 0.0:
            closed_summary = _get_closed_summary()
            if closed_summary:
                realized_pnl = closed_summary.get("realized_pnl", 0.0)

        pnl_sign = "+" if realized_pnl >= 0 else ""
        text = "\n".join([
            status_bar,
            SEP,
            "📊 *POSITIONS*",
            SEP,
            render_kv_line("POSITIONS", "0 (IDLE)"),
            render_kv_line("REALIZED", f"{pnl_sign}${realized_pnl:,.4f}"),
            SEP,
            "_Execute a paper trade to see positions here._",
            render_insight("No open positions — scanning markets"),
        ])
        return text, build_status_menu()

    # ── Build position cards ──────────────────────────────────────────────────
    total_unrealized = sum(p.unrealized_pnl for p in open_positions)
    pnl_summary = _get_pnl_summary()

    header = "\n".join([
        status_bar,
        SEP,
        f"📊 *POSITIONS* — {len(open_positions)} open",
        SEP,
        "",
    ])

    cards = []
    for pos in open_positions:
        market_question = _resolve_market_question(pos.market_id)
        card = render_trade_card(
            market_question=market_question,
            market_id=pos.market_id,
            side=getattr(pos, "side", "?"),
            entry_price=getattr(pos, "entry_price", 0.0),
            current_price=getattr(pos, "current_price", getattr(pos, "entry_price", 0.0)),
            size=getattr(pos, "size", 0.0),
            unrealized_pnl=getattr(pos, "unrealized_pnl", 0.0),
            status=getattr(pos, "status", "OPEN"),
            opened_at=_format_ts(getattr(pos, "opened_at", 0.0)),
        )
        cards.append(card)

    # Summary footer
    u_sign = "+" if total_unrealized >= 0 else ""
    footer_parts = [
        SEP,
        render_kv_line("UNREALIZED", f"{u_sign}${total_unrealized:,.4f}"),
    ]
    if pnl_summary:
        r_pnl = pnl_summary.get("total_realized", 0.0)
        r_sign = "+" if r_pnl >= 0 else ""
        footer_parts.append(render_kv_line("REALIZED", f"{r_sign}${r_pnl:,.4f}"))

    # Add wallet state
    if _paper_engine is not None:
        try:
            ws = _paper_engine._wallet.get_state()  # type: ignore[attr-defined]
            footer_parts += [
                render_kv_line("CASH", f"${ws.cash:.2f}"),
                render_kv_line("LOCKED", f"${ws.locked:.2f}"),
                render_kv_line("EQUITY", f"${ws.equity:.2f}"),
            ]
        except Exception:
            pass

    count = len(open_positions)
    footer_parts += [
        SEP,
        render_insight(f"Monitoring {count} position{'s' if count != 1 else ''}"),
    ]

    text = header + "\n\n".join(cards) + "\n" + "\n".join(footer_parts)
    log.info("trade_handler_positions_displayed", count=len(open_positions))
    return text, build_status_menu()


async def handle_trade_detail(market_id: str) -> tuple[str, list]:
    """Return single position detail card.

    Args:
        market_id: Polymarket condition ID.

    Returns:
        ``(text, keyboard)`` tuple.
    """
    status_bar = _get_status_bar()

    if _position_manager is None:
        log.warning("trade_handler_detail_no_manager", market_id=market_id)
        return (
            "\n".join([
                status_bar,
                SEP,
                "⚠️ *SYSTEM NOTICE*",
                SEP,
                render_kv_line("STATUS", "Manager unavailable"),
                SEP,
                render_insight("System not ready — restart bot"),
            ]),
            build_status_menu(),
        )

    try:
        pos = _position_manager.get_position(market_id)
    except Exception as exc:
        log.error("trade_handler_detail_fetch_error", market_id=market_id, error=str(exc))
        return (
            "\n".join([
                status_bar,
                SEP,
                "⚠️ *SYSTEM NOTICE*",
                SEP,
                render_kv_line("STATUS", "Position fetch error"),
                SEP,
                render_insight("Position data unavailable — retry"),
            ]),
            build_status_menu(),
        )

    if pos is None:
        return (
            "\n".join([
                status_bar,
                SEP,
                "📊 *POSITION NOT FOUND*",
                SEP,
                render_kv_line("MARKET ID", market_id[:20] + "…" if len(market_id) > 20 else market_id),
                SEP,
                "_Position may have been closed or does not exist._",
                render_insight("No active position — check trade history"),
            ]),
            build_status_menu(),
        )

    market_question = _resolve_market_question(pos.market_id)

    text = render_trade_card(
        market_question=market_question,
        market_id=pos.market_id,
        side=getattr(pos, "side", "?"),
        entry_price=getattr(pos, "entry_price", 0.0),
        current_price=getattr(pos, "current_price", getattr(pos, "entry_price", 0.0)),
        size=getattr(pos, "size", 0.0),
        unrealized_pnl=getattr(pos, "unrealized_pnl", 0.0),
        status=getattr(pos, "status", "OPEN"),
        opened_at=_format_ts(getattr(pos, "opened_at", 0.0)),
        status_bar=status_bar,
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


def _get_closed_summary() -> dict | None:
    """Return closed position PnL summary from the ledger if available."""
    if _paper_engine is None:
        return None
    try:
        ledger = _paper_engine._ledger  # type: ignore[attr-defined]
        realized_pnl = ledger.get_realized_pnl()
        return {"realized_pnl": realized_pnl}
    except Exception as exc:
        log.warning("trade_handler_closed_summary_error", error=str(exc))
        return None


def _format_ts(ts: float) -> str:
    """Format a UNIX timestamp as a human-readable string."""
    import datetime  # noqa: PLC0415
    try:
        dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return str(ts)
