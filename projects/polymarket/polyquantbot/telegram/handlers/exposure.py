"""telegram.handlers.exposure — Exposure report UI handler for PolyQuantBot.

Displays aggregate and per-position exposure vs portfolio equity.
Uses premium UI components for consistent terminal-grade formatting.
Dependencies are injected at bot startup.

Return type: tuple[str, list]  (text, InlineKeyboard)
"""
from __future__ import annotations

from typing import Optional, TYPE_CHECKING

import structlog

from ..ui.components import render_positions_summary, render_status_bar, render_kv_line, render_insight, SEP
from ..ui.keyboard import build_status_menu

if TYPE_CHECKING:
    from ...core.exposure import ExposureCalculator
    from ...core.positions import PaperPositionManager
    from ...core.wallet_engine import WalletEngine
    from ...core.system_state import SystemStateManager
    from ...core.market.market_cache import MarketMetadataCache

log = structlog.get_logger(__name__)

# Module-level injected dependencies
_exposure_calculator: Optional["ExposureCalculator"] = None
_position_manager: Optional["PaperPositionManager"] = None
_wallet_engine: Optional["WalletEngine"] = None
_system_state: Optional["SystemStateManager"] = None
_market_cache: Optional["MarketMetadataCache"] = None
_mode: str = "PAPER"


def set_exposure_calculator(calc: "ExposureCalculator") -> None:
    """Inject ExposureCalculator instance at bot startup."""
    global _exposure_calculator  # noqa: PLW0603
    _exposure_calculator = calc
    log.info("exposure_handler_calculator_injected")


def set_position_manager(pm: "PaperPositionManager") -> None:
    """Inject PaperPositionManager instance at bot startup."""
    global _position_manager  # noqa: PLW0603
    _position_manager = pm
    log.info("exposure_handler_position_manager_injected")


def set_wallet_engine(engine: "WalletEngine") -> None:
    """Inject WalletEngine instance at bot startup."""
    global _wallet_engine  # noqa: PLW0603
    _wallet_engine = engine
    log.info("exposure_handler_wallet_engine_injected")


def set_system_state(sm: "SystemStateManager") -> None:
    """Inject SystemStateManager at bot startup."""
    global _system_state  # noqa: PLW0603
    _system_state = sm
    log.info("exposure_handler_system_state_injected")


def set_market_cache(cache: "MarketMetadataCache") -> None:
    """Inject MarketMetadataCache at bot startup (optional, for question resolution)."""
    global _market_cache  # noqa: PLW0603
    _market_cache = cache
    log.info("exposure_handler_market_cache_injected")


def set_mode(mode: str) -> None:
    """Update trading mode string."""
    global _mode  # noqa: PLW0603
    _mode = mode


async def handle_exposure() -> tuple[str, list]:
    """Return exposure report screen with real open positions and premium UI.

    Shows:
      - Total exposure ($) and as % of equity
      - Position count
      - Per-position: market name, side, size, unrealized PnL
      - Summary row

    Returns:
        ``(text, keyboard)`` tuple.
    """
    # ── System state for status bar ─────────────────────────────────────────
    sys_state = "RUNNING"
    if _system_state is not None:
        try:
            snap = _system_state.snapshot()
            sys_state = snap.get("state", "RUNNING")
        except Exception:
            pass

    status_bar = render_status_bar(state=sys_state, mode=_mode)

    # ── Guard: services must be ready ────────────────────────────────────────
    if _position_manager is None or _wallet_engine is None:
        log.warning(
            "exposure_handler_not_ready",
            has_pm=_position_manager is not None,
            has_wallet=_wallet_engine is not None,
        )
        text = "\n".join([
            status_bar,
            SEP,
            "📉 *EXPOSURE*",
            SEP,
            render_kv_line("STATUS", "⚠️ Services not ready"),
            "_Please try again momentarily._",
            SEP,
            render_insight("System initializing — retry in a few seconds"),
        ])
        return text, build_status_menu()

    # ── Fetch positions ──────────────────────────────────────────────────────
    try:
        raw_positions = _position_manager.get_all_open()
    except Exception as exc:
        log.error("exposure_handler_fetch_positions_error", error=str(exc))
        return (
            "\n".join([
                status_bar,
                SEP,
                "⚠️ *SYSTEM NOTICE*",
                SEP,
                render_kv_line("STATUS", "Positions fetch error"),
                f"_{exc}_",
                SEP,
                render_insight("Position data unavailable — retry shortly"),
            ]),
            build_status_menu(),
        )

    # ── Fetch wallet equity ──────────────────────────────────────────────────
    try:
        wallet_state = _wallet_engine.get_state()
        wallet_equity = wallet_state.equity
    except Exception as exc:
        log.error("exposure_handler_fetch_wallet_error", error=str(exc))
        wallet_equity = 0.0

    # ── Resolve market questions ─────────────────────────────────────────────
    positions: list[dict] = []
    for pos in raw_positions:
        market_id = getattr(pos, "market_id", str(pos))
        # Try to get human-readable question from market cache
        market_question = market_id
        if _market_cache is not None:
            try:
                meta = _market_cache.get(market_id)
                if meta is not None:
                    market_question = getattr(meta, "question", market_id) or market_id
            except Exception:
                pass

        positions.append({
            "market_id": market_id,
            "market_question": market_question,
            "side": getattr(pos, "side", "?"),
            "size": getattr(pos, "size", 0.0),
            "unrealized_pnl": getattr(pos, "unrealized_pnl", 0.0),
            "entry_price": getattr(pos, "entry_price", 0.0),
            "exposure_pct": (
                (getattr(pos, "size", 0.0) / wallet_equity * 100)
                if wallet_equity > 0 else 0.0
            ),
        })

    text = render_positions_summary(
        positions=positions,
        wallet_equity=wallet_equity,
        status_bar=status_bar,
    )

    log.info(
        "exposure_handler_report_displayed",
        position_count=len(positions),
        total_exposure=sum(p["size"] for p in positions),
        wallet_equity=wallet_equity,
    )
    return text, build_status_menu()


# ── Internal helpers ──────────────────────────────────────────────────────────


def _truncate(s: str, max_len: int) -> str:
    """Truncate a string with ellipsis if it exceeds *max_len*."""
    return s if len(s) <= max_len else s[: max_len - 1] + "…"

