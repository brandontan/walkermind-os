"""Control handler — pause, resume, halt system via Telegram callbacks.

All handlers are async and idempotent.  They interact with SystemStateManager
directly and return (text, keyboard) — no Telegram API calls here.

Return type: tuple[str, InlineKeyboard]
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from ..ui.keyboard import build_control_menu, build_main_menu
from ..ui.screens import (
    control_screen,
    control_paused_screen,
    control_resumed_screen,
    control_halted_screen,
    error_screen,
)

if TYPE_CHECKING:
    from ...core.system_state import SystemStateManager

log = structlog.get_logger(__name__)


async def handle_control(state_manager: "SystemStateManager") -> tuple[str, list]:
    """Return control panel with state-aware buttons."""
    state_str = state_manager.state.value
    return control_screen(state_str), build_control_menu(state_str)


async def handle_pause(state_manager: "SystemStateManager") -> tuple[str, list]:
    """Pause trading.  Idempotent — safe to call when already PAUSED."""
    from ...core.system_state import SystemState

    current = state_manager.state
    if current is SystemState.HALTED:
        return "🔴 System HALTED — cannot pause.", build_control_menu("HALTED")
    if current is SystemState.PAUSED:
        return "ℹ️ System already PAUSED.", build_control_menu("PAUSED")

    await state_manager.pause(reason="telegram_callback_pause")
    log.info("control_paused_via_callback")
    return control_paused_screen(), build_control_menu("PAUSED")


async def handle_resume(state_manager: "SystemStateManager") -> tuple[str, list]:
    """Resume trading.  Idempotent — safe to call when already RUNNING."""
    from ...core.system_state import SystemState

    current = state_manager.state
    if current is SystemState.HALTED:
        return "🔴 System HALTED — manual restart required.", build_control_menu("HALTED")
    if current is SystemState.RUNNING:
        return "ℹ️ System already RUNNING.", build_control_menu("RUNNING")

    success = await state_manager.resume(reason="telegram_callback_resume")
    if success:
        log.info("control_resumed_via_callback")
        return control_resumed_screen(), build_control_menu("RUNNING")

    current_str = state_manager.state.value
    return "❌ Resume failed. Check logs.", build_control_menu(current_str)


async def handle_kill(state_manager: "SystemStateManager") -> tuple[str, list]:
    """Halt system permanently.  Requires manual restart to recover."""
    await state_manager.halt(reason="telegram_callback_stop_execute")
    log.warning("control_halted_via_callback")
    return control_halted_screen(), build_control_menu("HALTED")
