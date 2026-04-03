"""Settings handler — returns (text, keyboard) for settings-related screens.

Full UX intelligence layer:
  - Every setting includes: what it does, when to use, risk impact
  - render_risk_info(), render_strategy_info(), render_mode_info() via components
  - Premium status bar on every settings screen
  - Auto-trade explanation

Return type: tuple[str, InlineKeyboard]
"""
from __future__ import annotations

import os
from typing import Optional, TYPE_CHECKING

import structlog

from ..ui.keyboard import build_settings_menu, build_strategy_menu, build_risk_level_menu
from ..ui.components import (
    render_risk_card,
    render_strategy_card,
    render_mode_card,
    render_status_bar,
    SEP,
)
from ..ui.screens import mode_switched_screen, error_screen

if TYPE_CHECKING:
    from ..command_handler import CommandHandler
    from ...config.runtime_config import ConfigManager
    from ...strategy.strategy_manager import StrategyStateManager
    from ...core.system_state import SystemStateManager

log = structlog.get_logger(__name__)

_KNOWN_STRATEGIES: list[str] = ["ev_momentum", "mean_reversion", "liquidity_edge"]

# ── Injected dependencies ─────────────────────────────────────────────────────

_system_state: Optional["SystemStateManager"] = None
_mode: str = "PAPER"


def set_system_state(sm: "SystemStateManager") -> None:
    """Inject SystemStateManager at bot startup."""
    global _system_state  # noqa: PLW0603
    _system_state = sm


def set_mode(mode: str) -> None:
    """Update trading mode string."""
    global _mode  # noqa: PLW0603
    _mode = mode


# ── Helpers ───────────────────────────────────────────────────────────────────

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

async def handle_settings(
    config_manager: "ConfigManager",
    mode: str,
) -> tuple[str, list]:
    """Return settings overview screen with current values and explanations."""
    snap = config_manager.snapshot()
    status_bar = _get_status_bar()

    text = (
        f"{status_bar}\n{SEP}\n"
        "⚙️ *SETTINGS*\n\n"
        f"⚠️ Risk Level:    `{snap.risk_multiplier:.2f}` (Kelly fraction)\n"
        f"📏 Max Position:  `{snap.max_position:.2f}` (USD cap per trade)\n"
        f"🔀 Mode:          `{mode}`\n\n"
        "_Select a setting to configure:_"
    )
    return text, build_settings_menu()


async def handle_settings_risk(config_manager: "ConfigManager") -> tuple[str, list]:
    """Return risk level screen with explanation, impact, and preset buttons."""
    snap = config_manager.snapshot()
    status_bar = _get_status_bar()
    text = render_risk_card(
        current_value=snap.risk_multiplier,
        status_bar=status_bar,
    )
    return text, build_risk_level_menu()


async def handle_settings_strategy(
    cmd_handler: "CommandHandler",
    strategy_state: "Optional[StrategyStateManager]" = None,
) -> tuple[str, list]:
    """Return strategy toggle menu with descriptions and visual state.

    Delegates to the dedicated strategy handler when strategy_state is available.

    Args:
        cmd_handler: CommandHandler for legacy metrics fallback.
        strategy_state: Optional StrategyStateManager for multi-toggle UI.
    """
    from .strategy import handle_strategy_menu  # noqa: PLC0415

    if strategy_state is not None:
        return await handle_strategy_menu()

    # Legacy fallback: derive single-active from metrics
    active: str | None = None
    multi_metrics = getattr(cmd_handler, "_multi_metrics", None)
    if multi_metrics is not None:
        try:
            snap = multi_metrics.snapshot()
            if snap:
                active = max(snap, key=lambda k: snap[k].get("signals_generated", 0))
        except Exception as exc:
            log.debug("handle_settings_strategy_metrics_error", error=str(exc))

    keyboard = build_strategy_menu(strategies=_KNOWN_STRATEGIES, active=active)
    active_states = {s: (s == active) for s in _KNOWN_STRATEGIES}
    status_bar = _get_status_bar()
    text = render_strategy_card(
        strategies=_KNOWN_STRATEGIES,
        active_states=active_states,
        status_bar=status_bar,
        show_descriptions=True,
    )
    return text, keyboard


async def handle_settings_mode(current_mode: str) -> tuple[str, list]:
    """Return mode explanation card with confirmation prompt."""
    from ..ui.keyboard import build_mode_confirm_menu  # noqa: PLC0415
    status_bar = _get_status_bar()
    text = render_mode_card(current_mode=current_mode, status_bar=status_bar)
    new_mode = "PAPER" if current_mode.upper() == "LIVE" else "LIVE"
    return text, build_mode_confirm_menu(new_mode)


async def handle_settings_auto(mode: str) -> tuple[str, list]:
    """Return auto-trade setting screen with explanation."""
    status_bar = _get_status_bar()
    text = (
        f"{status_bar}\n{SEP}\n"
        "🤖 *AUTO TRADE*\n\n"
        "📋 *What it does:*\n"
        "_When enabled, the bot automatically executes trades based on\n"
        "active strategy signals without manual confirmation._\n\n"
        "📌 *When to use:*\n"
        "_When signals are validated and risk limits are set correctly._\n\n"
        "⚠️ *Risk impact:*\n"
        "_Higher throughput — more trades per cycle. Ensure Kelly α ≤ 0.25._\n\n"
        f"{SEP}\n"
        f"Current Mode: `{mode}`\n"
        "_Use `/set_auto true/false` to configure._"
    )
    return text, build_settings_menu()


async def handle_settings_notify() -> tuple[str, list]:
    """Return notifications explanation screen."""
    status_bar = _get_status_bar()
    text = (
        f"{status_bar}\n{SEP}\n"
        "🔔 *NOTIFICATIONS*\n\n"
        "📋 *What it does:*\n"
        "_Controls which events trigger Telegram alerts._\n\n"
        "📌 *Alert types:*\n"
        "  • 📈 Trade opened / closed\n"
        "  • ⚠️ Risk limit breached\n"
        "  • 🔴 System halt triggered\n"
        "  • 💹 Daily PnL summary\n\n"
        "_Notifications are always active for critical events (halt, risk breach)._\n\n"
        f"{SEP}\n"
        "_Use `/set_notify` commands to configure levels._"
    )
    return text, build_settings_menu()


async def handle_mode_confirm_switch(
    new_mode: str,
    config_manager: "ConfigManager",
) -> tuple[str, list]:
    """Handle confirmed mode switch — validates ENABLE_LIVE_TRADING guard."""
    if new_mode not in ("PAPER", "LIVE"):
        log.warning("mode_confirm_unknown_mode", new_mode=new_mode)
        return "❌ Unknown mode. Returning to settings.", build_settings_menu()

    if new_mode == "LIVE":
        live_enabled = os.environ.get("ENABLE_LIVE_TRADING", "").lower() == "true"
        if not live_enabled:
            log.warning("mode_switch_live_blocked", reason="ENABLE_LIVE_TRADING not set")
            return (
                "❌ Cannot switch to LIVE — `ENABLE_LIVE_TRADING` env var not set.\n"
                "Set it to `true` and restart.",
                build_settings_menu(),
            )

    log.info("telegram_mode_switched", new_mode=new_mode)
    return mode_switched_screen(new_mode), build_settings_menu()

