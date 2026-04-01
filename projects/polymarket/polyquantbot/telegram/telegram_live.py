"""Phase 9 — TelegramLive: Real-time Telegram alert system.

Sends structured alerts for all critical trading events:
    OPEN    — new position opened
    CLOSE   — position closed with PnL
    KILL    — kill switch triggered
    DAILY   — end-of-day performance summary
    ERROR   — critical error or exception
    RECONNECT — WebSocket reconnect event

Design:
    - Non-blocking: alerts sent via asyncio.Queue + background worker.
    - Alert queue has maxsize=128; overflow drops oldest (WARNING logged).
    - All sends use aiohttp with timeout (5s) and retry (max 3).
    - Disabled gracefully via enabled=False config or missing env vars.
    - Structured JSON logging on every send attempt.
    - Never raises — all exceptions caught and logged.

Environment variables:
    TELEGRAM_BOT_TOKEN — Telegram Bot API token
    TELEGRAM_CHAT_ID   — Target chat/channel ID

Usage::

    tg = TelegramLive.from_env()
    await tg.start()

    await tg.alert_open(market_id="0xabc", side="YES", price=0.62, size=50.0)
    await tg.alert_kill(reason="daily_loss_limit_breached")
    await tg.alert_daily(pnl=120.5, trades=8, win_rate=0.75)

    await tg.stop()
"""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import structlog

from .message_formatter import (
    format_checkpoint,
    format_error,
    format_kill_alert,
    format_metrics,
    format_state_change,
)

log = structlog.get_logger()

# ── Constants ─────────────────────────────────────────────────────────────────

_TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"
_SEND_TIMEOUT_S: float = 5.0
_MAX_RETRIES: int = 3
_RETRY_BASE_DELAY: float = 1.0
_QUEUE_MAXSIZE: int = 128


# ── Alert types ───────────────────────────────────────────────────────────────

class AlertType(str, Enum):
    """Supported alert categories."""
    OPEN = "OPEN"
    CLOSE = "CLOSE"
    KILL = "KILL"
    DAILY = "DAILY"
    ERROR = "ERROR"
    RECONNECT = "RECONNECT"


@dataclass
class Alert:
    """Internal alert payload."""
    alert_type: AlertType
    message: str
    correlation_id: str


# ── TelegramLive ──────────────────────────────────────────────────────────────

class TelegramLive:
    """Non-blocking Telegram alert dispatcher for Phase 9.

    Uses a background asyncio task to send queued alerts without blocking
    the trading event loop.

    Thread-safety: single asyncio event loop only.
    """

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        enabled: bool = True,
        send_timeout_s: float = _SEND_TIMEOUT_S,
        max_retries: int = _MAX_RETRIES,
    ) -> None:
        """Initialise TelegramLive.

        Args:
            bot_token: Telegram Bot API token.
            chat_id: Target chat or channel ID.
            enabled: If False, all alerts are silently dropped (no API calls).
            send_timeout_s: Timeout for each HTTP send attempt.
            max_retries: Max retry attempts per alert.
        """
        self._token = bot_token
        self._chat_id = chat_id
        self._enabled = enabled
        self._timeout = send_timeout_s
        self._max_retries = max_retries
        self._url = _TELEGRAM_API_BASE.format(token=bot_token)

        self._queue: asyncio.Queue[Alert] = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        self._worker_task: Optional[asyncio.Task] = None
        self._running: bool = False

        log.info(
            "telegram_live_initialized",
            enabled=enabled,
            chat_id=chat_id,
            queue_maxsize=_QUEUE_MAXSIZE,
        )

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls, enabled: bool = True) -> "TelegramLive":
        """Build from environment variables.

        Reads:
            TELEGRAM_BOT_TOKEN
            TELEGRAM_CHAT_ID
        """
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

        if not token or not chat_id:
            log.warning(
                "telegram_live_missing_env",
                has_token=bool(token),
                has_chat_id=bool(chat_id),
            )
            enabled = False

        return cls(bot_token=token, chat_id=chat_id, enabled=enabled)

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        """Return True when Telegram alerts are active (credentials present)."""
        return self._enabled

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the background alert worker."""
        if self._running:
            return
        self._running = True
        self._worker_task = asyncio.create_task(
            self._worker_loop(), name="telegram_alert_worker"
        )
        log.info("telegram_live_started")

    async def stop(self) -> None:
        """Flush remaining alerts and stop the worker."""
        self._running = False

        # Drain queue with timeout
        try:
            await asyncio.wait_for(self._queue.join(), timeout=10.0)
        except asyncio.TimeoutError:
            log.warning("telegram_live_stop_queue_drain_timeout")

        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

        log.info("telegram_live_stopped")

    # ── Public alert API ──────────────────────────────────────────────────────

    async def alert_open(
        self,
        market_id: str,
        side: str,
        price: float,
        size: float,
        fill_prob: float = 0.0,
        correlation_id: Optional[str] = None,
    ) -> None:
        """Send OPEN position alert.

        Args:
            market_id: Polymarket condition ID.
            side: "YES" | "NO".
            price: Entry price.
            size: Position size in USD.
            fill_prob: Expected fill probability from Phase 6.6.
            correlation_id: Request trace ID.
        """
        data = {
            "market": market_id[:16] + "...",
            "side": side,
            "price": price,
            "size_usd": size,
            "fill_prob": fill_prob,
        }
        msg = "🟢 *POSITION OPEN*\n" + format_metrics(data, title="POSITION OPEN")
        await self._enqueue(AlertType.OPEN, msg, correlation_id)

    async def alert_close(
        self,
        market_id: str,
        side: str,
        entry_price: float,
        exit_price: float,
        size: float,
        realised_pnl: float,
        reason: str,
        correlation_id: Optional[str] = None,
    ) -> None:
        """Send CLOSE position alert.

        Args:
            market_id: Polymarket condition ID.
            side: "YES" | "NO".
            entry_price: Price at entry.
            exit_price: Price at exit.
            size: Position size in USD.
            realised_pnl: Profit/loss in USD (positive = profit).
            reason: Close reason (take_profit | stop_loss | kill_switch | manual).
            correlation_id: Request trace ID.
        """
        pnl_emoji = "✅" if realised_pnl >= 0 else "🔴"
        pnl_sign = "+" if realised_pnl >= 0 else ""
        data = {
            "market": market_id[:16] + "...",
            "side": side,
            "entry": entry_price,
            "exit": exit_price,
            "size_usd": size,
            "pnl": f"{pnl_sign}${realised_pnl:.2f}",
            "reason": reason,
        }
        msg = f"{pnl_emoji} *POSITION CLOSE*\n" + format_metrics(data, title="POSITION CLOSE")
        await self._enqueue(AlertType.CLOSE, msg, correlation_id)

    async def alert_kill(
        self,
        reason: str,
        correlation_id: Optional[str] = None,
    ) -> None:
        """Send KILL SWITCH activated alert.

        Args:
            reason: Human-readable kill switch trigger reason.
            correlation_id: Request trace ID.
        """
        msg = format_kill_alert(reason=reason, correlation_id=correlation_id or "")
        await self._enqueue(AlertType.KILL, msg, correlation_id)

    async def alert_daily(
        self,
        pnl: float,
        trades: int,
        win_rate: float,
        fill_rate: float = 0.0,
        p95_latency_ms: float = 0.0,
        correlation_id: Optional[str] = None,
    ) -> None:
        """Send end-of-day performance summary alert.

        Args:
            pnl: Total daily realised PnL in USD.
            trades: Number of completed trades.
            win_rate: Fraction of winning trades (0.0–1.0).
            fill_rate: Order fill rate (0.0–1.0).
            p95_latency_ms: p95 execution latency in milliseconds.
            correlation_id: Request trace ID.
        """
        pnl_sign = "+" if pnl >= 0 else ""
        data = {
            "pnl": f"{pnl_sign}${pnl:.2f}",
            "trades": trades,
            "win_rate": win_rate,
            "fill_rate": fill_rate,
            "p95_latency_ms": p95_latency_ms,
        }
        msg = format_checkpoint(
            elapsed_h=0.0,
            metrics=data,
            label="DAILY",
            correlation_id=correlation_id or "",
        )
        await self._enqueue(AlertType.DAILY, msg, correlation_id)

    async def alert_error(
        self,
        error: str,
        context: str = "",
        correlation_id: Optional[str] = None,
    ) -> None:
        """Send critical error alert.

        Args:
            error: Error message or exception string.
            context: Additional context (module, operation, etc.).
            correlation_id: Request trace ID.
        """
        msg = format_error(
            context=context or "trading_system",
            error=error,
            severity="CRITICAL",
            correlation_id=correlation_id or "",
        )
        await self._enqueue(AlertType.ERROR, msg, correlation_id)

    async def alert_reconnect(
        self,
        attempt: int,
        delay_s: float,
        reason: str = "",
        correlation_id: Optional[str] = None,
    ) -> None:
        """Send WebSocket reconnect alert.

        Args:
            attempt: Reconnect attempt number.
            delay_s: Backoff delay before this attempt (seconds).
            reason: Disconnect reason.
            correlation_id: Request trace ID.
        """
        data = {
            "attempt": attempt,
            "backoff_s": delay_s,
            "reason": reason or "unknown",
        }
        msg = format_state_change(
            previous="disconnected",
            current="reconnecting",
            reason=f"attempt #{attempt} backoff {delay_s:.1f}s — {reason or 'unknown'}",
            initiated_by="ws_client",
        )
        msg = "🔄 *WS RECONNECT*\n" + format_metrics(data, title="WS RECONNECT")
        await self._enqueue(AlertType.RECONNECT, msg, correlation_id)

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _enqueue(
        self,
        alert_type: AlertType,
        message: str,
        correlation_id: Optional[str],
    ) -> None:
        """Enqueue an alert for background dispatch.

        If queue is full, drop the oldest alert (backpressure).
        Never raises.
        """
        if not self._enabled:
            return

        cid = correlation_id or str(uuid.uuid4())
        alert = Alert(alert_type=alert_type, message=message, correlation_id=cid)

        try:
            self._queue.put_nowait(alert)
        except asyncio.QueueFull:
            # Drop oldest to make room
            try:
                dropped = self._queue.get_nowait()
                self._queue.task_done()
                log.warning(
                    "telegram_alert_queue_full_dropped_oldest",
                    dropped_type=dropped.alert_type,
                    new_type=alert_type,
                )
                self._queue.put_nowait(alert)
            except Exception:  # noqa: BLE001
                log.warning("telegram_alert_enqueue_failed", alert_type=alert_type)

    async def _worker_loop(self) -> None:
        """Background loop — dequeues and sends alerts."""
        while self._running or not self._queue.empty():
            try:
                alert = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            try:
                await self._send_with_retry(alert)
            except Exception as exc:  # noqa: BLE001
                log.error(
                    "telegram_send_unhandled_exception",
                    alert_type=alert.alert_type,
                    error=str(exc),
                    exc_info=True,
                )
            finally:
                self._queue.task_done()

    async def _send_with_retry(self, alert: Alert) -> None:
        """Send alert to Telegram API with exponential backoff retry.

        Args:
            alert: Alert to send.
        """
        import aiohttp

        for attempt in range(1, self._max_retries + 1):
            try:
                async with aiohttp.ClientSession() as session:
                    payload = {
                        "chat_id": self._chat_id,
                        "text": alert.message,
                        "parse_mode": "Markdown",
                    }
                    async with session.post(
                        self._url,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=self._timeout),
                    ) as resp:
                        if resp.status == 200:
                            log.info(
                                "telegram_alert_sent",
                                alert_type=alert.alert_type,
                                attempt=attempt,
                                correlation_id=alert.correlation_id,
                            )
                            return
                        else:
                            body = await resp.text()
                            log.warning(
                                "telegram_send_non_200",
                                status=resp.status,
                                body=body[:200],
                                attempt=attempt,
                                alert_type=alert.alert_type,
                            )

            except Exception as exc:  # noqa: BLE001
                delay = min(_RETRY_BASE_DELAY * (2 ** (attempt - 1)), 8.0)
                log.warning(
                    "telegram_send_attempt_failed",
                    attempt=attempt,
                    alert_type=alert.alert_type,
                    error=str(exc),
                    retry_delay_s=delay,
                )
                if attempt < self._max_retries:
                    await asyncio.sleep(delay)

        log.error(
            "telegram_send_all_attempts_failed",
            alert_type=alert.alert_type,
            correlation_id=alert.correlation_id,
        )
