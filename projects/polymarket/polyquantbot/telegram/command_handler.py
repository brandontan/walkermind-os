"""Phase 10.6 — CommandHandler: Routes Telegram commands to system actions.

Handles the following bot commands:
    /status          — return current system state + config snapshot
    /pause           — pause trading (RUNNING → PAUSED)
    /resume          — resume trading (PAUSED → RUNNING)
    /kill            — halt trading permanently (→ HALTED)
    /set_risk [v]    — update risk multiplier (0.0–1.0)
    /set_max_position [v] — update max position (0.0–0.10)
    /metrics         — return current metrics snapshot

Design:
    - All commands are idempotent.
    - All commands produce a response sent back via Telegram.
    - Unknown commands return a usage/error response.
    - Invalid values are rejected with an explanatory error message.
    - Concurrent command execution is serialised via asyncio.Lock.
    - Structured JSON logging on every command.
    - Retry Telegram send 3× with timeout 3s before falling back.
    - On critical failure: fall back to PAUSED state.

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
    """

    def __init__(
        self,
        state_manager: SystemStateManager,
        config_manager: ConfigManager,
        metrics_source: Optional[object] = None,
        telegram_sender: Optional[object] = None,
        chat_id: str = "",
    ) -> None:
        self._state = state_manager
        self._config = config_manager
        self._metrics_source = metrics_source
        self._sender = telegram_sender
        self._chat_id = chat_id
        self._lock = asyncio.Lock()

        log.info(
            "command_handler_initialized",
            chat_id=chat_id,
            has_metrics_source=metrics_source is not None,
            has_sender=telegram_sender is not None,
        )

    # ── Primary dispatch ───────────────────────────────────────────────────────

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
                    message=f"⚠️ Critical error handling `/{cmd}`. System paused for safety.",
                )

        log.info(
            "command_result",
            command=cmd,
            user_id=user_id,
            correlation_id=cid,
            success=result.success,
            timestamp=time.time(),
        )

        # Send response back via Telegram
        await self._send_response(result.message, cid)
        return result

    # ── Handlers (one per command) ─────────────────────────────────────────────

    async def _dispatch(
        self, cmd: str, value: Optional[float], cid: str
    ) -> CommandResult:
        """Route command string to the corresponding handler method."""
        if cmd == "status":
            return await self._handle_status()
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

        return CommandResult(
            success=False,
            message=(
                "❓ Unknown command. Available: "
                "/status /pause /resume /kill /set_risk /set_max_position /metrics"
            ),
        )

    async def _handle_status(self) -> CommandResult:
        snap_state = self._state.snapshot()
        snap_cfg = self._config.snapshot()
        msg = (
            f"📊 *SYSTEM STATUS*\n"
            f"State: `{snap_state['state']}`\n"
            f"Reason: `{snap_state['reason']}`\n"
            f"Risk multiplier: `{snap_cfg.risk_multiplier:.3f}`\n"
            f"Max position: `{snap_cfg.max_position:.3f}`"
        )
        return CommandResult(
            success=True,
            message=msg,
            payload={"state": snap_state, "config": snap_cfg.__dict__},
        )

    async def _handle_pause(self) -> CommandResult:
        current = self._state.state
        if current is SystemState.HALTED:
            return CommandResult(
                success=False,
                message="🚫 Cannot pause — system is already HALTED.",
            )
        if current is SystemState.PAUSED:
            return CommandResult(
                success=True,
                message="⏸️ System is already PAUSED.",
            )
        await self._state.pause(reason="operator_telegram_command")
        return CommandResult(
            success=True,
            message="⏸️ System PAUSED. Use /resume to restart.",
            payload={"state": "PAUSED"},
        )

    async def _handle_resume(self) -> CommandResult:
        current = self._state.state
        if current is SystemState.HALTED:
            return CommandResult(
                success=False,
                message="🚫 Cannot resume — system is HALTED. Manual restart required.",
            )
        if current is SystemState.RUNNING:
            return CommandResult(
                success=True,
                message="▶️ System is already RUNNING.",
            )
        success = await self._state.resume(reason="operator_telegram_command")
        if success:
            return CommandResult(
                success=True,
                message="▶️ System RESUMED. Trading is now ACTIVE.",
                payload={"state": "RUNNING"},
            )
        return CommandResult(
            success=False,
            message="❌ Resume failed. Check system logs.",
        )

    async def _handle_kill(self) -> CommandResult:
        current = self._state.state
        if current is SystemState.HALTED:
            return CommandResult(
                success=True,
                message="🛑 System is already HALTED.",
            )
        await self._state.halt(reason="operator_kill_command")
        return CommandResult(
            success=True,
            message="🛑 *KILL SWITCH ACTIVATED*. All trading halted permanently.",
            payload={"state": "HALTED"},
        )

    async def _handle_set_risk(self, value: Optional[float]) -> CommandResult:
        if value is None:
            return CommandResult(
                success=False,
                message="❌ Usage: /set_risk [0.1–1.0]",
            )
        try:
            applied = await self._config.set_risk_multiplier(float(value))
        except (ValueError, TypeError) as exc:
            return CommandResult(
                success=False,
                message=f"❌ Invalid risk value: {exc}",
            )
        return CommandResult(
            success=True,
            message=f"✅ Risk multiplier updated to `{applied:.3f}`.",
            payload={"risk_multiplier": applied},
        )

    async def _handle_set_max_position(self, value: Optional[float]) -> CommandResult:
        if value is None:
            return CommandResult(
                success=False,
                message="❌ Usage: /set_max_position [0–0.1]",
            )
        try:
            applied = await self._config.set_max_position(float(value))
        except (ValueError, TypeError) as exc:
            return CommandResult(
                success=False,
                message=f"❌ Invalid max_position value: {exc}",
            )
        return CommandResult(
            success=True,
            message=f"✅ Max position updated to `{applied:.3f}`.",
            payload={"max_position": applied},
        )

    async def _handle_metrics(self) -> CommandResult:
        if self._metrics_source is None:
            return CommandResult(
                success=False,
                message="⚠️ Metrics source not configured.",
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
                message=f"❌ Failed to read metrics: {exc}",
            )

        msg = "📈 *METRICS SNAPSHOT*\n" + "\n".join(
            f"`{k}`: `{v}`" for k, v in (data.items() if isinstance(data, dict) else {})
        )
        if not isinstance(data, dict):
            msg = f"📈 *METRICS*\n`{data}`"

        return CommandResult(success=True, message=msg, payload=data if isinstance(data, dict) else {})

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
