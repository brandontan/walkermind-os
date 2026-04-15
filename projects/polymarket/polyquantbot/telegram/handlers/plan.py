"""telegram.handlers.plan — Fast Plan Bot Telegram handler.

Handles the /plan command: retrieves available market candidates from
the injected market cache, runs PlanEngine, formats results, and
returns a (text, keyboard) tuple for the Telegram UI.

Dependencies are injected at bot startup via module-level setters,
consistent with the established handler pattern.

Return type for handle_plan(): tuple[str, list]  (text, InlineKeyboard)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING

import structlog

from ...strategy.plan_engine import PlanEngine, TradePlan
from ...strategy.plan_formatter import format_plan_list, format_plan_empty
from ..ui.keyboard import build_status_menu

if TYPE_CHECKING:
    from ...core.market.market_cache import MarketMetadataCache
    from ...core.system_state import SystemStateManager

log = structlog.get_logger(__name__)

# ── Module-level injected dependencies ────────────────────────────────────────

_market_cache: Optional["MarketMetadataCache"] = None
_system_state: Optional["SystemStateManager"] = None
_mode: str = "PAPER"
_capital_usdc: float = 1_000.0

# Fast Plan Bot engine — instantiated once at injection time
_plan_engine: Optional[PlanEngine] = None

# Maximum number of plans to show in Telegram (mobile-readable)
_MAX_DISPLAY_PLANS: int = 3


# ── Injection setters ─────────────────────────────────────────────────────────


def set_market_cache(cache: "MarketMetadataCache") -> None:
    """Inject MarketMetadataCache at bot startup."""
    global _market_cache  # noqa: PLW0603
    _market_cache = cache
    log.info("plan_handler_market_cache_injected")


def set_system_state(sm: "SystemStateManager") -> None:
    """Inject SystemStateManager at bot startup."""
    global _system_state  # noqa: PLW0603
    _system_state = sm
    log.info("plan_handler_system_state_injected")


def set_mode(mode: str) -> None:
    """Update trading mode string."""
    global _mode  # noqa: PLW0603
    _mode = mode


def set_capital(capital_usdc: float) -> None:
    """Set available capital for plan sizing."""
    global _capital_usdc, _plan_engine  # noqa: PLW0603
    _capital_usdc = max(1.0, capital_usdc)
    _plan_engine = PlanEngine(capital_usdc=_capital_usdc, max_plans=_MAX_DISPLAY_PLANS)
    log.info("plan_handler_capital_set", capital_usdc=_capital_usdc)


def _get_engine() -> PlanEngine:
    """Return the shared PlanEngine, initialising lazily if needed."""
    global _plan_engine  # noqa: PLW0603
    if _plan_engine is None:
        _plan_engine = PlanEngine(capital_usdc=_capital_usdc, max_plans=_MAX_DISPLAY_PLANS)
    return _plan_engine


# ── Handler ────────────────────────────────────────────────────────────────────


async def handle_plan() -> tuple[str, list]:
    """Generate and return a Fast Plan Bot screen.

    Pulls available markets from the injected cache, evaluates them
    through PlanEngine, formats the ranked plans, and returns the
    (text, keyboard) tuple.

    Returns:
        ``(text, keyboard)`` tuple.
    """
    markets = _collect_markets()

    if not markets:
        log.info("plan_handler_no_markets")
        return format_plan_empty(mode=_mode), build_status_menu()

    engine = _get_engine()

    try:
        plans: List[TradePlan] = await engine.generate_plans(markets)
    except Exception as exc:
        log.error("plan_handler_engine_error", error=str(exc))
        return _error_screen(str(exc)), build_status_menu()

    text = format_plan_list(plans, mode=_mode, capital_usdc=_capital_usdc)

    log.info(
        "plan_handler_complete",
        markets_evaluated=len(markets),
        plans_returned=len(plans),
        mode=_mode,
    )
    return text, build_status_menu()


# ── Internal helpers ──────────────────────────────────────────────────────────


def _collect_markets() -> List[Dict[str, Any]]:
    """Pull market candidates from the cache as PlanEngine-ready dicts.

    Converts MarketMetadata objects to the flat dict format expected by
    PlanEngine.  Falls back gracefully when cache is unavailable.
    """
    if _market_cache is None:
        log.warning("plan_handler_no_cache")
        return []

    try:
        all_meta = _market_cache.get_all()
    except Exception as exc:
        log.error("plan_handler_cache_fetch_error", error=str(exc))
        return []

    if not all_meta:
        return []

    markets: List[Dict[str, Any]] = []
    for meta in all_meta:
        try:
            market_id = str(getattr(meta, "condition_id", "") or getattr(meta, "market_id", ""))
            title = str(getattr(meta, "question", "") or getattr(meta, "title", market_id))

            # Price fields — use sensible defaults when not available
            bid: float = float(getattr(meta, "best_bid", 0.0) or 0.0)
            ask: float = float(getattr(meta, "best_ask", 1.0) or 1.0)
            mid: float = float(getattr(meta, "mid", (bid + ask) / 2.0) or (bid + ask) / 2.0)
            depth_yes: float = float(getattr(meta, "depth_yes", 10_000.0) or 10_000.0)
            depth_no: float = float(getattr(meta, "depth_no", 10_000.0) or 10_000.0)
            volume: float = float(getattr(meta, "volume", 0.0) or 0.0)

            if not market_id:
                continue

            markets.append({
                "market_id": market_id,
                "title": title,
                "bid": bid,
                "ask": ask,
                "mid": mid,
                "depth_yes": depth_yes,
                "depth_no": depth_no,
                "volume": volume,
            })
        except Exception as exc:
            log.warning("plan_handler_market_parse_error", error=str(exc))

    log.info("plan_handler_markets_collected", count=len(markets))
    return markets


def _error_screen(error: str) -> str:
    """Return a formatted error screen for Telegram."""
    from ..ui.components import SEP, render_kv_line, render_insight  # noqa: PLC0415
    return "\n".join([
        f"📋 *FAST PLAN BOT*  `[{_mode}]`",
        SEP,
        "⚠️ *PLAN ENGINE ERROR*",
        SEP,
        render_kv_line("STATUS", "Engine error"),
        f"_{error[:80]}_",
        SEP,
        render_insight("Retry /plan — if issue persists check logs"),
    ])
