"""Phase 10.6/10.7 — CommandHandler: Routes Telegram commands to system actions.

Handles the following bot commands:
    /status          — return current system state + config snapshot
    /pause           — pause trading (RUNNING → PAUSED)
    /resume          — resume trading (PAUSED → RUNNING)
    /kill            — halt trading permanently (→ HALTED)
    /set_risk [v]    — update risk multiplier (0.0–1.0)
    /set_max_position [v] — update max position (0.0–0.10)
    /metrics         — return current metrics snapshot
    /prelive_check   — run PreLiveValidator and return structured result

Design:
    - All commands are idempotent.
    - All commands produce a response sent back via Telegram.
    - Unknown commands return a usage/error response.
    - Invalid values are rejected with an explanatory error message.
    - Concurrent command execution is serialised via asyncio.Lock.
    - Structured JSON logging on every command.
    - Retry Telegram send 3× with timeout 3s before falling back.
    - On critical failure: fall back to PAUSED state.
    - ALL message text produced via telegram.message_formatter (no raw strings).

Thread-safety: single asyncio event loop only.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Optional

import structlog

from ..config.runtime_config import ConfigManager
from ..core.system_state import SystemState, SystemStateManager
from ..interface.telegram.view_handler import render_view
from .message_formatter import (
    format_capital_allocation_report,
    format_command_response,
    format_error,
    format_health_snapshot,
    format_kill_alert,
    format_metrics,
    format_prelive_check,
    format_state_change,
)

log = structlog.get_logger()

# ── Constants ──────────────────────────────────────────────────────────────────

_SEND_TIMEOUT_S: float = 3.0
_MAX_SEND_RETRIES: int = 3
_RETRY_BASE_DELAY_S: float = 0.5

# ── CommandResult ──────────────────────────────────────────────────────────────


class CommandResult:
    """Result of a handled command.

    Attributes:
        success: True if the command executed without error.
        message: Human-readable response message for Telegram.
        payload: Optional structured data payload.
    """

    __slots__ = ("success", "message", "payload")

    def __init__(
        self,
        success: bool,
        message: str,
        payload: Optional[dict] = None,
    ) -> None:
        self.success = success
        self.message = message
        self.payload = payload or {}


# ── CommandHandler ─────────────────────────────────────────────────────────────


class CommandHandler:
    """Routes Telegram commands to SystemStateManager and ConfigManager.

    Args:
        state_manager: SystemStateManager for pause/resume/halt transitions.
        config_manager: ConfigManager for runtime config updates.
        metrics_source: Optional object with a ``snapshot()`` method that
                        returns a dict of current metrics.
        telegram_sender: Async callable(chat_id, text) for sending responses.
        chat_id: Target chat/channel ID for responses.
        prelive_validator: Optional PreLiveValidator for /prelive_check command.
        allocator: Optional DynamicCapitalAllocator for /allocation command.
        multi_metrics: Optional MultiStrategyMetrics for /strategies + /performance.
        risk_guard: Optional RiskGuard for /health drawdown data.
        mode: Trading mode string ("PAPER" | "LIVE") for /health + /performance.
    """

    def __init__(
        self,
        state_manager: SystemStateManager,
        config_manager: ConfigManager,
        metrics_source: Optional[object] = None,
        telegram_sender: Optional[object] = None,
        chat_id: str = "",
        prelive_validator: Optional[object] = None,
        allocator: Optional[object] = None,
        multi_metrics: Optional[object] = None,
        risk_guard: Optional[object] = None,
        mode: str = "PAPER",
    ) -> None:
        self._state = state_manager
        self._config = config_manager
        self._metrics_source = metrics_source
        self._sender = telegram_sender
        self._chat_id = chat_id
        self._prelive_validator = prelive_validator
        self._allocator = allocator
        self._multi_metrics = multi_metrics
        self._risk_guard = risk_guard
        self._mode = mode
        self._lock = asyncio.Lock()
        self._runner: Optional[object] = None  # wired after pipeline starts

        log.info(
            "command_handler_initialized",
            chat_id=chat_id,
            has_metrics_source=metrics_source is not None,
            has_sender=telegram_sender is not None,
            has_prelive_validator=prelive_validator is not None,
            has_allocator=allocator is not None,
            has_multi_metrics=multi_metrics is not None,
        )

    # ── Primary dispatch ───────────────────────────────────────────────────────

    def set_runner(self, runner: object) -> None:
        """Wire the live pipeline runner for real-time stats in /status."""
        self._runner = runner
        log.info("command_handler_runner_wired")

    async def handle(
        self,
        command: str,
        value: Optional[float] = None,
        user_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> CommandResult:
        """Dispatch a command to the appropriate handler.

        Args:
            command: Command name (e.g. "status", "pause", "/kill").
            value: Optional numeric argument (for set_risk / set_max_position).
            user_id: Telegram user ID for audit logging.
            correlation_id: Request trace ID.

        Returns:
            CommandResult with success flag and response message.
        """
        cid = correlation_id or str(uuid.uuid4())
        cmd = command.lstrip("/").lower().strip()

        log.info(
            "command_received",
            command=cmd,
            value=value,
            user_id=user_id,
            correlation_id=cid,
            timestamp=time.time(),
        )

        async with self._lock:
            try:
                result = await self._dispatch(cmd, value, cid)
            except Exception as exc:  # noqa: BLE001
                log.error(
                    "command_handler_error",
                    command=cmd,
                    user_id=user_id,
                    correlation_id=cid,
                    error=str(exc),
                    exc_info=True,
                )
                # Fail closed — pause on unhandled error
                await self._state.pause(reason=f"command_handler_critical_error:{cmd}")
                result = CommandResult(
                    success=False,
                    message=format_error(
                        context=f"command_handler:/{cmd}",
                        error=str(exc),
                        severity="CRITICAL",
                        correlation_id=cid,
                    ),
                )

        log.info(
            "command_result",
            command=cmd,
            user_id=user_id,
            correlation_id=cid,
            success=result.success,
            timestamp=time.time(),
        )

        # Send response back via Telegram only if not called from polling loop
        # (polling loop handles its own reply to preserve correct chat_id)
        if self._sender is not None and self._chat_id:
            await self._send_response(result.message, cid)
        return result

    # ── Handlers (one per command) ─────────────────────────────────────────────

    async def _dispatch(
        self, cmd: str, value: Optional[float], cid: str
    ) -> CommandResult:
        """Route command string to the corresponding handler method."""
        if cmd in ("start", "help", "menu", "main_menu"):
            from .handlers.start import handle_start  # noqa: PLC0415
            text, keyboard = await handle_start()
            return CommandResult(
                success=True,
                message=text,
                payload={"_keyboard": keyboard},
            )
        if cmd == "status":
            return await self._handle_status()
        if cmd == "home":
            return await self._handle_home()
        if cmd == "pause":
            return await self._handle_pause()
        if cmd == "resume":
            return await self._handle_resume()
        if cmd == "kill":
            return await self._handle_kill()
        if cmd == "set_risk":
            return await self._handle_set_risk(value)
        if cmd == "set_max_position":
            return await self._handle_set_max_position(value)
        if cmd == "metrics":
            return await self._handle_metrics()
        if cmd == "prelive_check":
            return await self._handle_prelive_check()
        if cmd == "allocation":
            return await self._handle_allocation()
        if cmd == "strategies":
            return await self._handle_strategies()
        if cmd == "performance":
            return await self._handle_performance()
        if cmd == "analysis":
            return await self._handle_analysis()
        if cmd == "health":
            return await self._handle_health()
        if cmd == "exposure":
            return await self._handle_exposure()
        if cmd == "risk":
            return await self._handle_risk()
        if cmd == "settings":
            return await self._handle_settings()
        if cmd == "set_markets":
            return await self._handle_set_markets(value)
        if cmd == "set_liquidity":
            return await self._handle_set_liquidity(value)
        if cmd == "markets":
            return await self._handle_markets()
        if cmd == "rediscover":
            return await self._handle_rediscover()
        if cmd == "alpha":
            return await self._handle_alpha()

        # ── New menu callbacks (new Telegram system) ───────────────────────────
        if cmd == "wallet":
            return await self._handle_wallet()
        if cmd in ("wallet_balance", "wallet_exposure"):
            return CommandResult(
                success=True,
                message="💰 *WALLET*\n\nUse /health for full portfolio status.",
            )
        if cmd == "control":
            return await self._handle_control()
        if cmd == "control_pause":
            return await self._handle_pause()
        if cmd == "control_resume":
            return await self._handle_resume()
        if cmd == "control_stop_confirm":
            from .ui.keyboard import build_stop_confirm_menu
            return CommandResult(
                success=True,
                message="🛑 *Stop Trading*\nThis will HALT the system. Are you sure?",
                payload={"_keyboard": build_stop_confirm_menu()},
            )
        if cmd == "control_stop_execute":
            return await self._handle_kill()
        if cmd == "noop":
            return CommandResult(success=True, message="")
        if cmd == "settings_risk":
            return CommandResult(
                success=True,
                message="⚠️ *Risk Level*\nSend `/set_risk [0.1–1.0]` to update.",
            )
        if cmd == "settings_mode":
            from .ui.keyboard import build_mode_confirm_menu
            new_mode = "LIVE" if self._mode == "PAPER" else "PAPER"
            return CommandResult(
                success=True,
                message=(
                    f"🔀 *Mode Switch*\nSwitch from `{self._mode}` → `{new_mode}`?\n\n"
                    f"⚠️ Confirm before proceeding."
                ),
                payload={"_keyboard": build_mode_confirm_menu(new_mode)},
            )
        if cmd.startswith("mode_confirm_"):
            new_mode = cmd.replace("mode_confirm_", "").upper()
            return await self._handle_mode_confirm_switch(new_mode)
        if cmd == "settings_strategy":
            return await self._handle_strategies()
        if cmd in ("settings_notify", "settings_auto"):
            return CommandResult(
                success=True,
                message="⚙️ *Settings*\nUse /settings for full configuration overview.",
            )

        return CommandResult(
            success=True,
            message=(
                "Unknown command. Type /start or /help for available commands."
            ),
        )

    async def _handle_status(self) -> CommandResult:
        return await self._handle_home()

    def _get_metrics_snapshot(self) -> dict:
        if self._metrics_source is None or not hasattr(self._metrics_source, "snapshot"):
            return {}
        try:
            snap = self._metrics_source.snapshot()
            return snap if isinstance(snap, dict) else {}
        except Exception:
            return {}

    def _build_home_payload(self) -> dict[str, object]:
        metrics = self._get_metrics_snapshot()
        snap_state = self._state.snapshot()
        snap_cfg = self._config.snapshot()
        return {
            "status": snap_state.get("state", "N/A"),
            "mode": self._mode,
            "markets": len(getattr(self._runner, "_market_ids", []) or []),
            "positions": metrics.get("open_positions", metrics.get("positions", "N/A")),
            "exposure": metrics.get("exposure", "N/A"),
            "unrealized": metrics.get("unrealized_pnl", metrics.get("unreal", "N/A")),
            "pnl": metrics.get("pnl", metrics.get("realized", "N/A")),
            "winrate": metrics.get("win_rate", metrics.get("wr", "N/A")),
            "drawdown": metrics.get("drawdown", "N/A"),
            "insight": (
                f"Risk {snap_cfg.risk_multiplier:.2f} • Max Pos {snap_cfg.max_position:.2f}"
            ),
        }

    async def _handle_home(self) -> CommandResult:
        payload = self._build_home_payload()
        return CommandResult(success=True, message=render_view("home", payload), payload=payload)

    async def _handle_pause(self) -> CommandResult:
        current = self._state.state
        if current is SystemState.HALTED:
            return CommandResult(
                success=False,
                message=format_command_response(
                    command="pause",
                    success=False,
                    message="Cannot pause — system is already HALTED.",
                ),
            )
        if current is SystemState.PAUSED:
            return CommandResult(
                success=True,
                message=format_command_response(
                    command="pause",
                    success=True,
                    message="System is already PAUSED.",
                ),
            )
        await self._state.pause(reason="operator_telegram_command")
        return CommandResult(
            success=True,
            message=format_state_change(
                previous=current.value,
                current="PAUSED",
                reason="operator_telegram_command",
                initiated_by="telegram",
            ),
            payload={"state": "PAUSED"},
        )

    async def _handle_resume(self) -> CommandResult:
        current = self._state.state
        if current is SystemState.HALTED:
            return CommandResult(
                success=False,
                message=format_command_response(
                    command="resume",
                    success=False,
                    message="Cannot resume — system is HALTED. Manual restart required.",
                ),
            )
        if current is SystemState.RUNNING:
            return CommandResult(
                success=True,
                message=format_command_response(
                    command="resume",
                    success=True,
                    message="System is already RUNNING.",
                ),
            )
        success = await self._state.resume(reason="operator_telegram_command")
        if success:
            return CommandResult(
                success=True,
                message=format_state_change(
                    previous=current.value,
                    current="RUNNING",
                    reason="operator_telegram_command",
                    initiated_by="telegram",
                ),
                payload={"state": "RUNNING"},
            )
        return CommandResult(
            success=False,
            message=format_command_response(
                command="resume",
                success=False,
                message="Resume failed. Check system logs.",
            ),
        )

    async def _handle_kill(self) -> CommandResult:
        current = self._state.state
        if current is SystemState.HALTED:
            return CommandResult(
                success=True,
                message=format_command_response(
                    command="kill",
                    success=True,
                    message="System is already HALTED.",
                ),
            )
        await self._state.halt(reason="operator_kill_command")
        return CommandResult(
            success=True,
            message=format_kill_alert(reason="operator_kill_command"),
            payload={"state": "HALTED"},
        )

    async def _handle_set_risk(self, value: Optional[float]) -> CommandResult:
        if value is None:
            return CommandResult(
                success=False,
                message=format_command_response(
                    command="set_risk",
                    success=False,
                    message="Usage: /set_risk [0.1–1.0]",
                ),
            )
        try:
            applied = await self._config.set_risk_multiplier(float(value))
        except (ValueError, TypeError) as exc:
            return CommandResult(
                success=False,
                message=format_error(
                    context="set_risk",
                    error=str(exc),
                    severity="ERROR",
                ),
            )
        return CommandResult(
            success=True,
            message=format_command_response(
                command="set_risk",
                success=True,
                message=f"Risk multiplier updated to `{applied:.3f}`.",
                payload={"risk_multiplier": applied},
            ),
            payload={"risk_multiplier": applied},
        )

    async def _handle_set_max_position(self, value: Optional[float]) -> CommandResult:
        if value is None:
            return CommandResult(
                success=False,
                message=format_command_response(
                    command="set_max_position",
                    success=False,
                    message="Usage: /set_max_position [0–0.1]",
                ),
            )
        try:
            applied = await self._config.set_max_position(float(value))
        except (ValueError, TypeError) as exc:
            return CommandResult(
                success=False,
                message=format_error(
                    context="set_max_position",
                    error=str(exc),
                    severity="ERROR",
                ),
            )
        return CommandResult(
            success=True,
            message=format_command_response(
                command="set_max_position",
                success=True,
                message=f"Max position updated to `{applied:.3f}`.",
                payload={"max_position": applied},
            ),
            payload={"max_position": applied},
        )

    async def _handle_metrics(self) -> CommandResult:
        if self._metrics_source is None:
            return CommandResult(
                success=False,
                message=format_command_response(
                    command="metrics",
                    success=False,
                    message="Metrics source not configured.",
                ),
            )
        try:
            if hasattr(self._metrics_source, "snapshot"):
                data = self._metrics_source.snapshot()
            elif hasattr(self._metrics_source, "compute"):
                result = self._metrics_source.compute()
                data = result.__dict__ if hasattr(result, "__dict__") else str(result)
            else:
                data = str(self._metrics_source)
        except Exception as exc:  # noqa: BLE001
            return CommandResult(
                success=False,
                message=format_error(
                    context="metrics",
                    error=str(exc),
                    severity="ERROR",
                ),
            )

        if isinstance(data, dict):
            msg = format_metrics(data)
        else:
            msg = format_metrics({"value": str(data)})

        return CommandResult(
            success=True,
            message=msg,
            payload=data if isinstance(data, dict) else {},
        )

    async def _handle_prelive_check(self) -> CommandResult:
        """Run PreLiveValidator and return formatted structured result."""
        log.info("command_prelive_check_invoked")

        if self._prelive_validator is None:
            return CommandResult(
                success=False,
                message=format_command_response(
                    command="prelive_check",
                    success=False,
                    message="PreLiveValidator not configured.",
                ),
            )

        try:
            result = self._prelive_validator.run()
            result_dict = result.to_dict() if hasattr(result, "to_dict") else vars(result)
        except Exception as exc:  # noqa: BLE001
            log.error(
                "command_prelive_check_error",
                error=str(exc),
                exc_info=True,
            )
            return CommandResult(
                success=False,
                message=format_error(
                    context="prelive_check",
                    error=str(exc),
                    severity="ERROR",
                ),
            )

        log.info(
            "command_prelive_check_complete",
            status=result_dict.get("status"),
            reason=result_dict.get("reason"),
        )

        return CommandResult(
            success=result_dict.get("status") == "PASS",
            message=format_prelive_check(result_dict),
            payload=result_dict,
        )

    async def _handle_allocation(self) -> CommandResult:
        """Return capital allocation report from DynamicCapitalAllocator."""
        log.info("command_allocation_invoked")
        if self._allocator is None:
            return CommandResult(
                success=False,
                message=format_command_response(
                    command="allocation",
                    success=False,
                    message="Allocator not configured.",
                ),
            )
        try:
            snap = self._allocator.allocation_snapshot()
            msg = format_capital_allocation_report(
                strategy_weights=snap.strategy_weights,
                position_sizes=snap.position_sizes,
                disabled_strategies=snap.disabled_strategies,
                suppressed_strategies=snap.suppressed_strategies,
                total_allocated_usd=snap.total_allocated_usd,
                bankroll=snap.bankroll,
                mode=self._mode,
            )
            return CommandResult(
                success=True,
                message=msg,
                payload={
                    "strategy_weights": snap.strategy_weights,
                    "total_allocated_usd": snap.total_allocated_usd,
                },
            )
        except Exception as exc:
            return CommandResult(
                success=False,
                message=format_error(
                    context="allocation", error=str(exc), severity="ERROR"
                ),
            )

    async def _handle_strategies(self) -> CommandResult:
        """Return per-strategy performance snapshot from MultiStrategyMetrics."""
        log.info("command_strategies_invoked")
        if self._multi_metrics is None:
            return CommandResult(
                success=False,
                message=format_command_response(
                    command="strategies",
                    success=False,
                    message="MultiStrategyMetrics not configured.",
                ),
            )
        try:
            snapshot = self._multi_metrics.snapshot()
            strategy_states = {
                str(strategy_id): bool((m_data or {}).get("enabled", True))
                for strategy_id, m_data in snapshot.items()
            }
            msg = render_view("strategy", {"strategies": strategy_states})
            return CommandResult(
                success=True,
                message=msg,
                payload={"snapshot": snapshot},
            )
        except Exception as exc:
            return CommandResult(
                success=False,
                message=format_error(
                    context="strategies", error=str(exc), severity="ERROR"
                ),
            )

    async def _handle_performance(self) -> CommandResult:
        """Return PnL + win-rate performance report."""
        log.info("command_performance_invoked")
        if self._multi_metrics is None:
            return CommandResult(
                success=False,
                message=format_command_response(
                    command="performance",
                    success=False,
                    message="MultiStrategyMetrics not configured.",
                ),
            )
        try:
            snapshot = self._multi_metrics.snapshot()
            per_pnl: dict = {}
            per_wr: dict = {}
            per_trades: dict = {}
            total_pnl = 0.0
            total_wins = 0
            total_trade_count = 0
            max_drawdown = 0.0
            for strategy_id, m_data in snapshot.items():
                per_pnl[strategy_id] = float(m_data.get("total_pnl", 0.0))
                per_wr[strategy_id] = float(m_data.get("win_rate", 0.0))
                per_trades[strategy_id] = int(m_data.get("trades_executed", 0))
                total_pnl += per_pnl[strategy_id]
                t = per_trades[strategy_id]
                total_wins += round(per_wr[strategy_id] * t)
                total_trade_count += t
                dd = float(m_data.get("drawdown", 0.0))
                if dd > max_drawdown:
                    max_drawdown = dd

            overall_win_rate = (
                total_wins / total_trade_count if total_trade_count > 0 else 0.0
            )

            ui_payload = {
                "pnl": round(total_pnl, 4),
                "winrate": round(overall_win_rate, 4),
                "trades": self._multi_metrics.total_trades,
                "drawdown": round(max_drawdown, 4),
            }
            return CommandResult(
                success=True,
                message=render_view("performance", ui_payload),
                payload={
                    "total_pnl": round(total_pnl, 4),
                    "total_trades": self._multi_metrics.total_trades,
                    "win_rate": round(overall_win_rate, 4),
                    "drawdown": round(max_drawdown, 4),
                },
            )
        except Exception as exc:
            return CommandResult(
                success=False,
                message=format_error(
                    context="performance", error=str(exc), severity="ERROR"
                ),
            )

    def _safe_float(self, value: object, default: float = 0.0) -> float:
        """Best-effort float conversion with fallback."""
        try:
            if value is None:
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def _extract_breakdown_payload(self) -> dict[str, object]:
        """Load performance_breakdown payload from metrics source snapshot."""
        if self._metrics_source is None or not hasattr(self._metrics_source, "snapshot"):
            return {}
        try:
            snap = self._metrics_source.snapshot()
            if not isinstance(snap, dict):
                return {}
            payload = snap.get("performance_breakdown", {})
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _format_analysis_line(
        self,
        key: str,
        payload: dict[str, object],
        metric_mode: str = "all",
    ) -> str:
        """Format one grouped analysis line for Telegram."""
        wr = self._safe_float(payload.get("win_rate"), 0.0) * 100.0
        pf = self._safe_float(payload.get("profit_factor"), 0.0)
        exp = self._safe_float(payload.get("expectancy"), 0.0)

        if metric_mode == "wr":
            stats = f"WR {wr:.0f}%"
        elif metric_mode == "pf":
            stats = f"PF {pf:.2f}"
        else:
            stats = f"WR {wr:.0f}% PF {pf:.2f} EXP {exp:.2f}"

        return f"├ {key:<10} {stats}"

    async def _handle_analysis(self) -> CommandResult:
        """Return grouped closed-trade edge analysis."""
        log.info("command_analysis_invoked")

        breakdown = self._extract_breakdown_payload()
        by_market = breakdown.get("by_market", {}) if isinstance(breakdown, dict) else {}
        by_signal = breakdown.get("by_signal", {}) if isinstance(breakdown, dict) else {}
        by_edge = breakdown.get("by_edge", {}) if isinstance(breakdown, dict) else {}

        lines = ["📊 PERFORMANCE BREAKDOWN", "", "MARKET"]

        if isinstance(by_market, dict) and by_market:
            items = sorted(by_market.items())
            for idx, (name, metrics) in enumerate(items):
                if not isinstance(metrics, dict):
                    continue
                prefix = "└" if idx == len(items) - 1 else "├"
                line = self._format_analysis_line(str(name), metrics, metric_mode="all")
                lines.append(prefix + line[1:])
        else:
            lines.append("└ NO DATA")

        lines += ["", "SIGNAL"]
        if isinstance(by_signal, dict) and by_signal:
            items = sorted(by_signal.items())
            for idx, (name, metrics) in enumerate(items):
                if not isinstance(metrics, dict):
                    continue
                prefix = "└" if idx == len(items) - 1 else "├"
                line = self._format_analysis_line(str(name), metrics, metric_mode="wr")
                lines.append(prefix + line[1:])
        else:
            lines.append("└ NO DATA")

        lines += ["", "EDGE"]
        if isinstance(by_edge, dict) and by_edge:
            items = sorted(by_edge.items())
            for idx, (name, metrics) in enumerate(items):
                if not isinstance(metrics, dict):
                    continue
                prefix = "└" if idx == len(items) - 1 else "├"
                line = self._format_analysis_line(str(name), metrics, metric_mode="pf")
                lines.append(prefix + line[1:])
        else:
            lines.append("└ NO DATA")

        message = "\n".join(lines)
        return CommandResult(
            success=True,
            message=message,
            payload={"performance_breakdown": breakdown},
        )

    async def _handle_health(self) -> CommandResult:
        """Return full system health snapshot."""
        log.info("command_health_invoked")
        try:
            from ..core.system_snapshot import build_system_snapshot
            snap = build_system_snapshot(
                state_manager=self._state,
                config_manager=self._config,
                metrics=self._multi_metrics,
                allocator=self._allocator,
                risk_guard=self._risk_guard,
                mode=self._mode,
            )
            msg = format_health_snapshot(
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
            return CommandResult(
                success=True,
                message=msg,
                payload=snap.to_dict(),
            )
        except Exception as exc:
            return CommandResult(
                success=False,
                message=format_error(
                    context="health", error=str(exc), severity="ERROR"
                ),
            )

    async def _handle_settings(self) -> CommandResult:
        """Return all current runtime settings in one view."""
        snap_cfg = self._config.snapshot()
        snap_state = self._state.snapshot()
        lines = [
            "⚙️ *BOT SETTINGS*\n",
            f"Mode: `{snap_state.get('state', 'UNKNOWN')}`",
            f"Trading mode: `{self._mode}`",
            "",
            "*Risk & Position*",
            f"Risk multiplier: `{snap_cfg.risk_multiplier:.3f}`",
            f"Max position: `{snap_cfg.max_position:.3f}` ({snap_cfg.max_position*100:.1f}%)",
            "",
            "*Market Discovery*",
            f"Max markets: `{snap_cfg.max_markets}`",
            f"Min liquidity: `${snap_cfg.min_liquidity_usd:,.0f}`",
            f"Active markets: `{len(snap_cfg.market_ids)}`",
            "",
            "_Use /set\\_markets, /set\\_liquidity, /set\\_risk, /set\\_max\\_position to update_",
        ]
        return CommandResult(
            success=True,
            message="\n".join(lines),
            payload=snap_cfg.__dict__,
        )

    async def _handle_set_markets(self, value: Optional[float]) -> CommandResult:
        """Set max auto-discovered markets: /set_markets [1–50]."""
        if value is None:
            return CommandResult(
                success=False,
                message=format_command_response(
                    command="set_markets",
                    success=False,
                    message="Usage: /set_markets [1–50]  — e.g. /set_markets 10",
                ),
            )
        try:
            applied = await self._config.set_max_markets(int(value))
        except (ValueError, TypeError) as exc:
            return CommandResult(
                success=False,
                message=format_error(context="set_markets", error=str(exc), severity="ERROR"),
            )
        return CommandResult(
            success=True,
            message=format_command_response(
                command="set_markets",
                success=True,
                message=f"Max markets updated to `{applied}`. Use /rediscover to apply now.",
                payload={"max_markets": applied},
            ),
            payload={"max_markets": applied},
        )

    async def _handle_set_liquidity(self, value: Optional[float]) -> CommandResult:
        """Set minimum liquidity threshold: /set_liquidity [1000–1000000]."""
        if value is None:
            return CommandResult(
                success=False,
                message=format_command_response(
                    command="set_liquidity",
                    success=False,
                    message="Usage: /set_liquidity [amount]  — e.g. /set_liquidity 25000",
                ),
            )
        try:
            applied = await self._config.set_min_liquidity_usd(float(value))
        except (ValueError, TypeError) as exc:
            return CommandResult(
                success=False,
                message=format_error(context="set_liquidity", error=str(exc), severity="ERROR"),
            )
        return CommandResult(
            success=True,
            message=format_command_response(
                command="set_liquidity",
                success=True,
                message=f"Min liquidity updated to `${applied:,.0f}`. Use /rediscover to apply now.",
                payload={"min_liquidity_usd": applied},
            ),
            payload={"min_liquidity_usd": applied},
        )

    async def _handle_markets(self) -> CommandResult:
        """Show currently active markets with name, price and volume."""
        snap = self._config.snapshot()
        meta = self._config.market_meta

        # Fallback: read from runner if meta not yet loaded
        if not meta and self._runner is not None:
            try:
                ids = list(self._runner._market_ids)
            except Exception:
                ids = []
            if not ids:
                return CommandResult(success=True,
                    message="No markets active. Tap 🔍 Rediscover or run /rediscover.")
            lines = [f"📋 *ACTIVE MARKETS* ({len(ids)})\n"]
            for i, mid in enumerate(ids[:15], 1):
                short = mid[:10] + "…" + mid[-6:] if len(mid) > 18 else mid
                lines.append(f"`{i}.` `{short}`")
            return CommandResult(success=True, message="\n".join(lines))

        if not meta:
            return CommandResult(success=True,
                message="No markets active. Tap 🔍 Rediscover or run /rediscover.")

        lines = [f"📋 *ACTIVE MARKETS* ({len(meta)})\n"]
        for i, m in enumerate(meta, 1):
            q = m.get("question", "Unknown")
            q = q if len(q) <= 55 else q[:52] + "…"
            vol = m.get("volume", 0)
            vol_str = f"${vol/1000:.0f}K" if vol >= 1000 else f"${vol:.0f}"
            yes = m.get("yes_price")
            no = m.get("no_price")
            price_str = f"YES {yes:.0%} | NO {no:.0%}" if yes and no else ""
            end = m.get("end_date", "")
            lines.append(
                f"*{i}.* {q}\n"
                f"   {price_str}  Vol: {vol_str}"
                + (f"  Ends: {end}" if end else "")
            )
            lines.append("")  # blank line between markets

        return CommandResult(
            success=True,
            message="\n".join(lines),
            payload={"markets": meta, "count": len(meta)},
        )

    async def _handle_rediscover(self) -> CommandResult:
        """Trigger fresh market discovery from Gamma API with current settings."""
        log.info("command_rediscover_invoked")
        snap = self._config.snapshot()
        try:
            from ..core.bootstrap import _fetch_active_markets
            new_ids = await _fetch_active_markets(
                gamma_url="https://gamma-api.polymarket.com",
                min_liquidity=snap.min_liquidity_usd,
                max_markets=snap.max_markets,
            )
        except Exception as exc:  # noqa: BLE001
            log.error("command_rediscover_failed", error=str(exc))
            return CommandResult(
                success=False,
                message=format_error(
                    context="rediscover",
                    error=str(exc),
                    severity="ERROR",
                ),
            )
        if not new_ids:
            return CommandResult(
                success=False,
                message=format_command_response(
                    command="rediscover",
                    success=False,
                    message=(
                        f"Discovery returned 0 markets "
                        f"(min_liquidity=${snap.min_liquidity_usd:,.0f}, max={snap.max_markets}).\n"
                        "Try /set_liquidity with a lower value."
                    ),
                ),
            )
        self._config.update_market_ids(new_ids)
        # Also update the live runner if wired
        if self._runner is not None:
            try:
                self._runner._market_ids = new_ids
                log.info("command_rediscover_runner_updated", count=len(new_ids))
            except Exception as exc:
                log.warning("command_rediscover_runner_update_failed", error=str(exc))
        lines = [f"🔍 *REDISCOVER COMPLETE* — {len(new_ids)} market(s)\n"]
        for i, mid in enumerate(new_ids, 1):
            short = mid[:10] + "..." + mid[-6:] if len(mid) > 20 else mid
            lines.append(f"`{i}.` `{short}`")
        lines.append(f"\n_Filter: min_liquidity=${snap.min_liquidity_usd:,.0f}, max={snap.max_markets}_")
        log.info("command_rediscover_complete", count=len(new_ids), market_ids=new_ids)
        return CommandResult(
            success=True,
            message="\n".join(lines),
            payload={"market_ids": new_ids, "count": len(new_ids)},
        )

    async def _handle_wallet(self) -> CommandResult:
        """Show wallet / portfolio overview with new-menu keyboard."""
        from .ui.keyboard import build_wallet_menu
        metrics = self._get_metrics_snapshot()
        payload = {
            "cash": metrics.get("cash", metrics.get("balance", "N/A")),
            "equity": metrics.get("equity", "N/A"),
            "used": metrics.get("used", metrics.get("margin", "N/A")),
            "free": metrics.get("free", "N/A"),
            "positions": metrics.get("open_positions", metrics.get("positions", 0)),
        }
        return CommandResult(
            success=True,
            message=render_view("wallet", payload),
            payload={"_keyboard": build_wallet_menu()},
        )

    async def _handle_exposure(self) -> CommandResult:
        metrics = self._get_metrics_snapshot()
        payload = {
            "total_exposure": metrics.get("total_exposure", metrics.get("exposure", "N/A")),
            "ratio": metrics.get("exposure_ratio", "N/A"),
            "positions": metrics.get("open_positions", metrics.get("positions", 0)),
            "unrealized": metrics.get("unrealized_pnl", metrics.get("unreal", "N/A")),
            "position_lines": metrics.get("position_lines", []),
        }
        return CommandResult(success=True, message=render_view("exposure", payload), payload=payload)

    async def _handle_risk(self) -> CommandResult:
        cfg = self._config.snapshot()
        payload = {
            "kelly": "0.25f",
            "level": f"{cfg.risk_multiplier:.2f}",
            "profile": "Conservative controls active",
        }
        return CommandResult(success=True, message=render_view("risk", payload), payload=payload)

    async def _handle_control(self) -> CommandResult:
        """Show control panel with state-aware keyboard."""
        from .ui.keyboard import build_control_menu
        state_str = self._state.state.value
        return CommandResult(
            success=True,
            message=f"▶ *CONTROL*\nSystem state: `{state_str}`",
            payload={"_keyboard": build_control_menu(state_str)},
        )

    async def _handle_mode_confirm_switch(self, new_mode: str) -> CommandResult:
        """Handle confirmed mode switch from new Telegram menu."""
        import os as _os
        if new_mode not in ("PAPER", "LIVE"):
            return CommandResult(
                success=False,
                message="❌ Unknown mode. Returning to settings.",
            )
        if new_mode == "LIVE":
            live_enabled = _os.environ.get("ENABLE_LIVE_TRADING", "").lower() == "true"
            if not live_enabled:
                log.warning("mode_switch_live_blocked", reason="ENABLE_LIVE_TRADING not set")
                return CommandResult(
                    success=False,
                    message=(
                        "❌ Cannot switch to LIVE — `ENABLE_LIVE_TRADING` env var not set.\n"
                        "Set it to `true` and restart."
                    ),
                )
        self._mode = new_mode
        log.info("telegram_mode_switched", new_mode=new_mode)
        return CommandResult(
            success=True,
            message=f"✅ Mode switched to `{new_mode}`.",
        )

    async def _handle_alpha(self) -> CommandResult:
        """Return alpha model debug diagnostics via /alpha command."""
        from .handlers.alpha_debug import handle_alpha_debug
        try:
            text, _keyboard = await handle_alpha_debug()
            return CommandResult(success=True, message=text)
        except Exception as exc:
            log.error("handle_alpha_error", error=str(exc))
            return CommandResult(
                success=False,
                message="❌ Failed to load alpha debug data.",
            )

    # ── Telegram send with retry ───────────────────────────────────────────────

    async def _send_response(self, message: str, correlation_id: str) -> None:
        """Send a response message via Telegram with retry.

        Retries up to 3× with exponential backoff (timeout 3s per attempt).
        Falls back gracefully — never raises.

        Args:
            message: Message text to send.
            correlation_id: Request trace ID for logging.
        """
        if self._sender is None or not self._chat_id:
            return

        for attempt in range(1, _MAX_SEND_RETRIES + 1):
            try:
                await asyncio.wait_for(
                    self._sender(self._chat_id, message),  # type: ignore[operator]
                    timeout=_SEND_TIMEOUT_S,
                )
                log.info(
                    "command_response_sent",
                    attempt=attempt,
                    correlation_id=correlation_id,
                )
                return
            except asyncio.TimeoutError:
                log.warning(
                    "command_response_timeout",
                    attempt=attempt,
                    correlation_id=correlation_id,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "command_response_send_failed",
                    attempt=attempt,
                    correlation_id=correlation_id,
                    error=str(exc),
                )
            if attempt < _MAX_SEND_RETRIES:
                delay = min(_RETRY_BASE_DELAY_S * (2 ** (attempt - 1)), 4.0)
                await asyncio.sleep(delay)

        log.error(
            "command_response_all_attempts_failed",
            correlation_id=correlation_id,
        )
        # Fallback: pause to fail closed
        await self._state.pause(reason="telegram_send_failure_fallback")
