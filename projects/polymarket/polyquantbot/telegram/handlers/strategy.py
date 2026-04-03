"""telegram.handlers.strategy — Dedicated strategy menu handler for PolyQuantBot.

Provides:
  - Full strategy toggle menu with visual state (🟢/🔴) and descriptions
  - Per-strategy detail view (what it does, when to use, risk impact)
  - Instant toggle feedback with confirmation message

Dependencies are injected at bot startup.

Return type for all handlers: tuple[str, list]  (text, InlineKeyboard)
"""
from __future__ import annotations

from typing import Optional, TYPE_CHECKING

import structlog

from ..ui.components import render_strategy_card, render_status_bar, SEP
from ..ui.keyboard import build_strategy_menu

if TYPE_CHECKING:
    from ...strategy.strategy_manager import StrategyStateManager
    from ...core.system_state import SystemStateManager

log = structlog.get_logger(__name__)

_KNOWN_STRATEGIES: list[str] = ["ev_momentum", "mean_reversion", "liquidity_edge"]

# ── Injected dependencies ─────────────────────────────────────────────────────

_strategy_state: Optional["StrategyStateManager"] = None
_system_state: Optional["SystemStateManager"] = None
_mode: str = "PAPER"


def set_strategy_state(ss: "StrategyStateManager") -> None:
    """Inject StrategyStateManager at bot startup."""
    global _strategy_state  # noqa: PLW0603
    _strategy_state = ss
    log.info("strategy_handler_state_injected")


def set_system_state(sm: "SystemStateManager") -> None:
    """Inject SystemStateManager at bot startup."""
    global _system_state  # noqa: PLW0603
    _system_state = sm
    log.info("strategy_handler_system_state_injected")


def set_mode(mode: str) -> None:
    """Update trading mode string."""
    global _mode  # noqa: PLW0603
    _mode = mode


# ── Handlers ──────────────────────────────────────────────────────────────────


async def handle_strategy_menu() -> tuple[str, list]:
    """Return full strategy menu with visual toggle state and descriptions.

    Returns:
        ``(text, keyboard)`` tuple.
    """
    active_states: dict[str, bool] = {}

    if _strategy_state is not None:
        try:
            active_states = _strategy_state.get_state()
        except Exception as exc:
            log.error("strategy_handler_fetch_error", error=str(exc))

    # Build status bar
    sys_state = "RUNNING"
    if _system_state is not None:
        try:
            snap = _system_state.snapshot()
            sys_state = snap.get("state", "RUNNING")
        except Exception:
            pass

    status_bar = render_status_bar(state=sys_state, mode=_mode)

    text = render_strategy_card(
        strategies=_KNOWN_STRATEGIES,
        active_states=active_states,
        status_bar=status_bar,
        show_descriptions=True,
    )

    keyboard = build_strategy_menu(
        strategies=_KNOWN_STRATEGIES,
        active_states=active_states,
    )

    log.info(
        "strategy_handler_menu_displayed",
        active_count=sum(1 for v in active_states.values() if v),
    )

    return text, keyboard


async def handle_strategy_toggle(strategy_name: str) -> tuple[str, list]:
    """Toggle a strategy on/off and return updated menu with confirmation.

    Args:
        strategy_name: Name of strategy to toggle.

    Returns:
        ``(text, keyboard)`` tuple with confirmation prefix.
    """
    if _strategy_state is None:
        log.warning("strategy_toggle_no_state_manager", strategy=strategy_name)
        text = (
            "⚠️ *Strategy Manager Unavailable*\n\n"
            "_Cannot toggle strategies — manager not injected._"
        )
        return text, build_strategy_menu(
            strategies=_KNOWN_STRATEGIES,
            active_states={},
        )

    if strategy_name not in _KNOWN_STRATEGIES:
        log.warning("strategy_toggle_unknown", strategy=strategy_name)
        confirmation = f"⚠️ Unknown strategy: `{strategy_name}`\n\n"
    else:
        try:
            _strategy_state.toggle(strategy_name)
            now_active = _strategy_state.get_state().get(strategy_name, False)
            if now_active:
                confirmation = f"✅ *Strategy activated:* `{strategy_name}`\n\n"
                log.info("strategy_toggled_on", strategy=strategy_name)
            else:
                confirmation = f"❌ *Strategy disabled:* `{strategy_name}`\n\n"
                log.info("strategy_toggled_off", strategy=strategy_name)
        except Exception as exc:
            log.error("strategy_toggle_error", strategy=strategy_name, error=str(exc))
            confirmation = f"❌ *Toggle failed:* `{strategy_name}`\n\n"

    # Rebuild menu with updated state
    try:
        active_states = _strategy_state.get_state()
    except Exception:
        active_states = {}

    status_bar = render_status_bar(state="RUNNING", mode=_mode)
    menu_text = render_strategy_card(
        strategies=_KNOWN_STRATEGIES,
        active_states=active_states,
        status_bar=None,
        show_descriptions=False,
    )

    text = confirmation + menu_text
    keyboard = build_strategy_menu(
        strategies=_KNOWN_STRATEGIES,
        active_states=active_states,
    )

    return text, keyboard
