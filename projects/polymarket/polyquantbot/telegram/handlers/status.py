"""Status handler — returns (text, keyboard) for status-related screens.

All handlers are async, pure functions — no Telegram API calls here.
Return type: tuple[str, InlineKeyboard]
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from ..ui.keyboard import build_status_menu
from ..ui.screens import (
    status_screen,
    performance_screen,
    strategies_screen,
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


async def handle_performance(
    cmd_handler: "CommandHandler",
    mode: str,
) -> tuple[str, list]:
    """Return PnL + win-rate performance summary."""
    multi_metrics = getattr(cmd_handler, "_multi_metrics", None)
    if multi_metrics is None:
        return "📈 *PERFORMANCE*\n\nMultiStrategyMetrics not configured.", build_status_menu()
    try:
        snapshot = multi_metrics.snapshot()
        total_pnl = sum(float(v.get("total_pnl", 0.0)) for v in snapshot.values())
        total_trades = getattr(multi_metrics, "total_trades", 0)
        text = performance_screen(
            total_pnl=round(total_pnl, 4),
            total_trades=total_trades,
            mode=mode,
        )
    except Exception as exc:
        log.error("handle_performance_error", error=str(exc))
        text = error_screen(context="performance", error=str(exc))
    return text, build_status_menu()


async def handle_health(
    state_manager: "SystemStateManager",
    config_manager: "ConfigManager",
    cmd_handler: "CommandHandler",
    mode: str,
) -> tuple[str, list]:
    """Return full system health snapshot."""
    try:
        from ...core.system_snapshot import build_system_snapshot
        from ..message_formatter import format_health_snapshot

        snap = build_system_snapshot(
            state_manager=state_manager,
            config_manager=config_manager,
            metrics=getattr(cmd_handler, "_multi_metrics", None),
            allocator=getattr(cmd_handler, "_allocator", None),
            risk_guard=getattr(cmd_handler, "_risk_guard", None),
            mode=mode,
        )
        text = format_health_snapshot(
            mode=snap.mode,
            system_state=snap.system_state,
            state_reason=snap.state_reason,
            total_exposure_usd=snap.total_exposure_usd,
            total_pnl=snap.total_pnl,
            drawdown=snap.drawdown,
            bankroll=snap.bankroll,
            active_strategies=snap.active_strategies,
            disabled_strategies=snap.disabled_strategies,
            suppressed_strategies=snap.suppressed_strategies,
            total_trades=snap.total_trades,
            total_signals=snap.total_signals,
            risk_multiplier=snap.risk_multiplier,
            max_position=snap.max_position,
        )
    except Exception as exc:
        log.error("handle_health_error", error=str(exc))
        text = error_screen(context="health", error=str(exc))
    return text, build_status_menu()


async def handle_strategies(
    cmd_handler: "CommandHandler",
) -> tuple[str, list]:
    """Return per-strategy metrics snapshot."""
    multi_metrics = getattr(cmd_handler, "_multi_metrics", None)
    if multi_metrics is None:
        return "📋 *STRATEGIES*\n\nMultiStrategyMetrics not configured.", build_status_menu()
    try:
        snapshot = multi_metrics.snapshot()
        conflicts = getattr(multi_metrics, "total_conflicts", 0)
        text = strategies_screen(snapshot=snapshot, conflicts=conflicts)
    except Exception as exc:
        log.error("handle_strategies_error", error=str(exc))
        text = error_screen(context="strategies", error=str(exc))
    return text, build_status_menu()
