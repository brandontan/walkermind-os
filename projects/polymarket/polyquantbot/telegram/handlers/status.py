"""Status handler — returns (text, keyboard) for status-related screens.

All handlers are async, pure functions — no Telegram API calls here.
Return type: tuple[str, InlineKeyboard]

Legacy handlers (handle_performance, handle_health, handle_strategies) have
been removed. All routing to those actions now raises RuntimeError("LEGACY UI DISABLED")
in CallbackRouter before reaching this module.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from ..ui.keyboard import build_status_menu
from ..ui.screens import (
    status_screen,
    error_screen,
)

if TYPE_CHECKING:
    from ..command_handler import CommandHandler
    from ...core.system_state import SystemStateManager
    from ...config.runtime_config import ConfigManager

log = structlog.get_logger(__name__)


async def handle_status(
    state_manager: "SystemStateManager",
    config_manager: "ConfigManager",
    cmd_handler: "CommandHandler",
    mode: str,
) -> tuple[str, list]:
    """Return live system status with optional pipeline stats."""
    snap_state = state_manager.snapshot()
    snap_cfg = config_manager.snapshot()

    pipeline_lines: list[str] = []
    runner = getattr(cmd_handler, "_runner", None)
    if runner is not None:
        try:
            rs = runner.snapshot()
            ws_ok = runner._ws._stats.connected
            pipeline_lines = [
                f"WS: `{'connected' if ws_ok else 'disconnected'}`",
                f"Events: `{rs.event_count}`",
                f"Signals: `{rs.signal_count}`",
                f"Fills: `{rs.fill_count}`",
                f"Markets: `{len(runner._market_ids)}`",
            ]
        except Exception as exc:
            log.debug("handle_status_runner_snapshot_failed", error=str(exc))

    text = status_screen(
        state=snap_state.get("state", "UNKNOWN"),
        reason=snap_state.get("reason", ""),
        mode=mode,
        risk_multiplier=snap_cfg.risk_multiplier,
        max_position=snap_cfg.max_position,
        pipeline_lines=pipeline_lines or None,
    )
    return text, build_status_menu()
