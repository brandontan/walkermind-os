from __future__ import annotations

import asyncio
import time
import uuid
from typing import Optional

import structlog

from ..config.runtime_config import ConfigManager
from ..core.system_state import SystemState, SystemStateManager
from ..interface.telegram.view_handler import render_view, safe_count, safe_number
from ..execution.engine import export_execution_payload, get_execution_engine
from ..execution.strategy_trigger import StrategyConfig, StrategyTrigger
from .ui.keyboard import build_dashboard_menu
from .handlers.portfolio_service import get_portfolio_service
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
            payload = self._build_home_payload()
            return CommandResult(
                success=True,
                message=await render_view("home", payload),
                payload=payload,
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
        if cmd == "trade":
            return await self._handle_trade(value)

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

    async def _handle_trade(self, args: Optional[float] = None) -> CommandResult:
        """Parse /trade [test/close/status] [args]."""
        if args is None:
            return CommandResult(
                success=False,
                message="Usage: /trade [test|close|status] [args]",
            )
        parts = str(args).split()
        if not parts:
            return CommandResult(
                success=False,
                message="Usage: /trade [test|close|status] [args]",
            )
        action = parts[0].lower()
        if action == "test":
            return await self._handle_trade_test(" ".join(parts[1:]))
        if action == "close":
            return await self._handle_trade_close(" ".join(parts[1:]))
        if action == "status":
            return await self._handle_trade_status()
        return CommandResult(
            success=False,
            message="Usage: /trade [test|close|status] [args]",
        )

    async def _handle_trade_test(self, args: str) -> CommandResult:
        """Parse /trade test [market] [side] [size]."""
        if not args:
            return CommandResult(
                success=False,
                message="Usage: /trade test [market] [side YES/NO] [size]",
            )
        parts = args.split()
        if len(parts) < 3:
            return CommandResult(
                success=False,
                message="Usage: /trade test [market] [side YES/NO] [size]",
            )
        market, side, size_str = parts[0], parts[1].upper(), parts[2]
        try:
            size = float(size_str)
        except ValueError:
            return CommandResult(
                success=False,
                message="Size must be a number.",
            )
        if side not in ("YES", "NO"):
            return CommandResult(
                success=False,
                message="Side must be YES or NO.",
            )
        engine = get_execution_engine()
        trigger = StrategyTrigger(
            engine=engine,
            config=StrategyConfig(
                market_id=market,
                side=side,
                threshold=0.45,
                target_pnl=20.0,
            ),
        )
        await trigger.evaluate(0.42)
        await engine.update_mark_to_market({market: 0.46})
        payload = await export_execution_payload()
        get_portfolio_service().merge_execution_state(
            positions=payload.get("positions", []),
            cash=float(payload.get("cash", 0.0)),
            equity=float(payload.get("equity", 0.0)),
            realized_pnl=float(payload.get("realized", 0.0)),
        )
        return CommandResult(
            success=True,
            message=await render_view("positions", payload),
            payload=payload,
        )

    async def _handle_trade_close(self, args: str) -> CommandResult:
        """Parse /trade close [market]."""
        if not args:
            return CommandResult(
                success=False,
                message="Usage: /trade close [market]",
            )
        market = args.strip()
        engine = get_execution_engine()
        snapshot = await engine.snapshot()
        position = next((p for p in snapshot.positions if p.market_id == market), None)
        if position is None:
            return CommandResult(
                success=False,
                message=f"No open position for {market}.",
            )
        await engine.close_position(position, 0.50)
        payload = await export_execution_payload()
        get_portfolio_service().merge_execution_state(
            positions=payload.get("positions", []),
            cash=float(payload.get("cash", 0.0)),
            equity=float(payload.get("equity", 0.0)),
            realized_pnl=float(payload.get("realized", 0.0)),
        )
        return CommandResult(
            success=True,
            message=f"Closed position for {market}.",
            payload=payload,
        )

    async def _handle_trade_status(self) -> CommandResult:
        """Return current execution state."""
        payload = await export_execution_payload()
        return CommandResult(
            success=True,
            message=await render_view("positions", payload),
            payload=payload,
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
        risk_multiplier = safe_number(getattr(snap_cfg, "risk_multiplier", 0.25), 0.25)
        max_position = safe_number(getattr(snap_cfg, "max_position", 0.10), 0.10)
        return {
            "status": snap_state.get("state", "N/A"),
            "mode": self._mode,
            "latency": safe_number(metrics.get("latency_ms", metrics.get("latency", 0.0)), 0.0),
            "balance": safe_number(metrics.get("cash", metrics.get("balance", 0.0)), 0.0),
            "equity": safe_number(metrics.get("equity", 0.0), 0.0),
            "positions": safe_count(metrics.get("open_positions", metrics.get("positions", 0)), 0),
            "unrealized": safe_number(metrics.get("unrealized_pnl", metrics.get("unreal", 0.0)), 0.0),
            "realized": safe_number(metrics.get("pnl", metrics.get("realized", 0.0)), 0.0),
            "_keyboard": build_dashboard_menu(),
            "insight": (
                f"Risk {risk_multiplier:.2f} • Max Pos {max_position:.2f}"
            ),
        }

    async def _handle_home(self) -> CommandResult:
        payload = self._build_home_payload()
        return CommandResult(success=True, message=await render_view("home", payload), payload=payload)

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
                "EV Momentum": True,
                "Mean Reversion": True,
                "Liquidity Edge": False,
            }
            for strategy_id, m_data in snapshot.items():
                enabled = bool((m_data or {}).get("enabled", True))
                sid = str(strategy_id).strip().lower()
                if "ev" in sid or "moment" in sid:
                    strategy_states["EV Momentum"] = enabled
                elif "mean" in sid or "revert" in sid:
                    strategy_states["Mean Reversion"] = enabled
                elif "liq" in sid or "edge" in sid:
                    strategy_states["Liquidity Edge"] = enabled
            msg = await render_view("strategy", {"strategies": strategy_states})
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
                message=await render_view("performance", ui_payload),
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

    def _derive_edge_type(self, distribution: dict[str, int]) -> str:
        if not distribution:
            return "N/A"
        total = sum(distribution.values())
        bond_count = sum(
            count for key, count in distribution.items() if "bond" in str(key).lower()
        )
        if bond_count > total / 2:
            return "BOND ARB"
        if len(distribution) > 1:
            return "DIVERSIFIED"
        return "TREND"

    def _build_market_payload(self, metrics: dict[str, object]) -> dict[str, object]:
        distribution_raw = metrics.get("market_distribution", {})
        distribution = distribution_raw if isinstance(distribution_raw, dict) else {}

        top_raw = metrics.get("top_opportunities", [])
        top_items = top_raw if isinstance(top_raw, list) else []

        total_markets = metrics.get("total_markets", metrics.get("markets_scanned", 0))
        active_markets = metrics.get("active_markets", len(top_items))
        dominant_signal = metrics.get("dominant_signal", "N/A")
        top_edge_type = metrics.get("top_edge_type", self._derive_edge_type(distribution))

        return {
            "total_markets": total_markets,
            "active_markets": active_markets,
            "top_edge_type": top_edge_type,
            "dominant_signal": dominant_signal,
            "top_opportunities": top_items[:5],
        }

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

        lines = ["📊 PERFORMANCE BREAKDOWN", ""]
