"""Settings handler — returns (text, keyboard) for settings-related screens.

Return type: tuple[str, InlineKeyboard]
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

import structlog

from ..ui.keyboard import build_settings_menu, build_strategy_menu
from ..ui.screens import settings_screen, mode_switched_screen, error_screen

if TYPE_CHECKING:
    from ..command_handler import CommandHandler
    from ...config.runtime_config import ConfigManager

log = structlog.get_logger(__name__)

_KNOWN_STRATEGIES: list[str] = ["ev_momentum", "mean_reversion", "liquidity_edge"]


async def handle_settings(
    config_manager: "ConfigManager",
    mode: str,
) -> tuple[str, list]:
    """Return settings overview screen with current values."""
    snap = config_manager.snapshot()
    text = settings_screen(
        mode=mode,
        risk_multiplier=snap.risk_multiplier,
        max_position=snap.max_position,
    )
    return text, build_settings_menu()


async def handle_settings_strategy(
    cmd_handler: "CommandHandler",
) -> tuple[str, list]:
    """Return strategy selection menu."""
    active: str | None = None
    multi_metrics = getattr(cmd_handler, "_multi_metrics", None)
    if multi_metrics is not None:
        try:
            snap = multi_metrics.snapshot()
            if snap:
                # Treat strategy with most signals as active
                active = max(snap, key=lambda k: snap[k].get("signals_generated", 0))
        except Exception as exc:
            log.debug("handle_settings_strategy_metrics_error", error=str(exc))

    keyboard = build_strategy_menu(strategies=_KNOWN_STRATEGIES, active=active)
    text = (
        "📐 *STRATEGIES*\n\n"
        f"Active: `{active or 'none'}`\n"
        "Select strategy to inspect:"
    )
    return text, keyboard


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
