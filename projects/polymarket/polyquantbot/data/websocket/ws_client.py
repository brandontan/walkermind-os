"""Phase 7 — PolymarketWSClient.

Async WebSocket client for Polymarket CLOB real-time feed.
Streams orderbook snapshots + updates and trade events.

Features:
    - Auto-reconnect with exponential backoff (cap 60 s).
    - Heartbeat watchdog: triggers reconnect if no message in `heartbeat_timeout_s`.
    - Event parsing into canonical WS event dicts consumed by Phase 7 runner.
    - Dedup guard: ignores events with timestamp regression.
    - Zero polling — fully event-driven via asyncio.Queue.

Usage::

    client = PolymarketWSClient.from_env(market_ids=["0xabc..."])
    await client.connect()
    async for event in client.events():
        # event = {"type": "orderbook|trade", "market_id": ..., "timestamp": ..., "data": ...}
        process(event)

Environment variables:
    CLOB_WS_URL  — WebSocket endpoint (default: wss://ws-subscriptions-clob.polymarket.com/ws/market)
    CLOB_API_KEY — optional API key if endpoint requires auth
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

import structlog
import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

log = structlog.get_logger()

# ── Constants ─────────────────────────────────────────────────────────────────

_DEFAULT_WS_URL = (
    "wss://ws-subscriptions-clob.polymarket.com/ws/market"
)
_RECONNECT_BASE_DELAY: float = 1.0      # seconds
_RECONNECT_MAX_DELAY: float = 60.0      # seconds
_RECONNECT_MULTIPLIER: float = 2.0
_HEARTBEAT_TIMEOUT: float = 30.0        # seconds — reconnect if silent this long
_QUEUE_MAXSIZE: int = 1024              # backpressure cap
_PING_INTERVAL: float = 20.0           # WS ping interval
_PING_TIMEOUT: float = 10.0            # WS ping timeout


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class WSEvent:
    """Canonical WebSocket event produced by PolymarketWSClient.

    Attributes:
        type: "orderbook" | "trade"
        market_id: Polymarket condition ID (0x-prefixed hex string).
        timestamp: Unix epoch seconds (float).
        data: Raw parsed dict — varies by type.
            orderbook: {"bids": [[price, size], ...], "asks": [[price, size], ...], "update_type": "snapshot|delta"}
            trade: {"price": float, "size": float, "side": "BUY|SELL", "trade_id": str}
    """

    type: str
    market_id: str
    timestamp: float
    data: dict


@dataclass
class WSClientStats:
    """Telemetry counters for the WS client."""

    messages_received: int = 0
    events_emitted: int = 0
    reconnects: int = 0
    parse_errors: int = 0
    heartbeat_timeouts: int = 0
    last_message_ts: float = field(default_factory=time.time)


# ── Client ────────────────────────────────────────────────────────────────────

class PolymarketWSClient:
    """Async WebSocket client for the Polymarket CLOB market feed.

    Thread-safety: single asyncio event loop only.
    """

    def __init__(
        self,
        market_ids: list[str],
        ws_url: str = _DEFAULT_WS_URL,
        api_key: Optional[str] = None,
        heartbeat_timeout_s: float = _HEARTBEAT_TIMEOUT,
        reconnect_base_delay: float = _RECONNECT_BASE_DELAY,
        reconnect_max_delay: float = _RECONNECT_MAX_DELAY,
        queue_maxsize: int = _QUEUE_MAXSIZE,
    ) -> None:
        """Initialise the WS client.

        Args:
            market_ids: List of Polymarket condition IDs to subscribe to.
            ws_url: WebSocket endpoint URL.
            api_key: Optional API key header value.
            heartbeat_timeout_s: Seconds of silence before forced reconnect.
            reconnect_base_delay: Initial delay between reconnect attempts (s).
            reconnect_max_delay: Maximum delay between reconnect attempts (s).
            queue_maxsize: Max buffered events before backpressure.
        """
        if not market_ids:
            raise ValueError("market_ids must not be empty")

        self._market_ids = list(market_ids)
        self._ws_url = ws_url
        self._api_key = api_key
        self._heartbeat_timeout = heartbeat_timeout_s
        self._reconnect_base = reconnect_base_delay
        self._reconnect_max = reconnect_max_delay

        self._queue: asyncio.Queue[WSEvent] = asyncio.Queue(maxsize=queue_maxsize)
        self._running: bool = False
        self._stats = WSClientStats()

        # Per-market last-timestamp guard (dedup regression)
        self._last_ts: dict[str, float] = {}

        self._ws_task: Optional[asyncio.Task] = None
        self._watchdog_task: Optional[asyncio.Task] = None

    # ── Public API ────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Start the WS streaming loop and heartbeat watchdog."""
        if self._running:
            log.warning("ws_client_already_running")
            return
        self._running = True
        self._ws_task = asyncio.create_task(
            self._run_ws_loop(), name="polymarket_ws_loop"
        )
        self._watchdog_task = asyncio.create_task(
            self._heartbeat_watchdog(), name="polymarket_ws_watchdog"
        )
        log.info(
            "ws_client_started",
            market_count=len(self._market_ids),
            ws_url=self._ws_url,
            heartbeat_timeout_s=self._heartbeat_timeout,
        )

    async def disconnect(self) -> None:
        """Gracefully stop all background tasks."""
        self._running = False
        for task in (self._ws_task, self._watchdog_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        log.info("ws_client_stopped", stats=self._stats.__dict__)

    async def events(self) -> AsyncIterator[WSEvent]:
        """Async generator yielding WSEvent objects as they arrive.

        Yields until disconnect() is called.
        """
        while self._running or not self._queue.empty():
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                yield event
            except asyncio.TimeoutError:
                continue

    def stats(self) -> WSClientStats:
        """Return current telemetry snapshot."""
        return self._stats

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls, market_ids: list[str]) -> "PolymarketWSClient":
        """Build from environment variables.

        Reads:
            CLOB_WS_URL  (optional, uses default if absent)
            CLOB_API_KEY (optional)
        """
        return cls(
            market_ids=market_ids,
            ws_url=os.getenv("CLOB_WS_URL", _DEFAULT_WS_URL),
            api_key=os.getenv("CLOB_API_KEY"),
        )

    # ── Internal WS loop ──────────────────────────────────────────────────────

    async def _run_ws_loop(self) -> None:
        """Persistent reconnect loop — runs until self._running is False."""
        delay = self._reconnect_base
        attempt = 0

        while self._running:
            attempt += 1
            try:
                await self._connect_and_stream(attempt)
                # Clean disconnect → reset backoff
                delay = self._reconnect_base

            except asyncio.CancelledError:
                break

            except (ConnectionClosed, WebSocketException, OSError) as exc:
                self._stats.reconnects += 1
                log.warning(
                    "ws_disconnected",
                    attempt=attempt,
                    reconnect_delay_s=delay,
                    error=str(exc),
                )
                if not self._running:
                    break
                await asyncio.sleep(delay)
                delay = min(delay * _RECONNECT_MULTIPLIER, self._reconnect_max)

            except Exception as exc:  # noqa: BLE001
                self._stats.reconnects += 1
                log.error(
                    "ws_unexpected_error",
                    attempt=attempt,
                    reconnect_delay_s=delay,
                    error=str(exc),
                    exc_info=True,
                )
                if not self._running:
                    break
                await asyncio.sleep(delay)
                delay = min(delay * _RECONNECT_MULTIPLIER, self._reconnect_max)

    async def _connect_and_stream(self, attempt: int) -> None:
        """Open one WebSocket connection, subscribe, and read until closed."""
        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        log.info(
            "ws_connecting",
            attempt=attempt,
            url=self._ws_url,
            market_count=len(self._market_ids),
        )

        async with websockets.connect(
            self._ws_url,
            extra_headers=headers,
            ping_interval=_PING_INTERVAL,
            ping_timeout=_PING_TIMEOUT,
            open_timeout=10,
        ) as ws:
            log.info("ws_connected", attempt=attempt)
            await self._subscribe(ws)

            async for raw_msg in ws:
                if not self._running:
                    break
                self._stats.messages_received += 1
                self._stats.last_message_ts = time.time()
                await self._handle_raw(raw_msg)

    async def _subscribe(self, ws) -> None:
        """Send subscription message for all configured market IDs."""
        sub_msg = {
            "auth": {"apiKey": self._api_key} if self._api_key else {},
            "markets": self._market_ids,
            "type": "Market",
        }
        await ws.send(json.dumps(sub_msg))
        log.info("ws_subscribed", market_ids=self._market_ids)

    async def _handle_raw(self, raw: str | bytes) -> None:
        """Parse a raw WS message and enqueue canonical WSEvent(s)."""
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._stats.parse_errors += 1
            log.warning("ws_parse_error", error=str(exc), raw_preview=str(raw)[:120])
            return

        # Polymarket sends a list of events in one message
        if isinstance(payload, list):
            for item in payload:
                await self._dispatch(item)
        elif isinstance(payload, dict):
            await self._dispatch(payload)
        else:
            log.debug("ws_unknown_payload_shape", payload_type=type(payload).__name__)

    async def _dispatch(self, item: dict) -> None:
        """Map a Polymarket raw event to a canonical WSEvent and enqueue it."""
        event_type = item.get("event_type", "")
        market_id = item.get("asset_id") or item.get("market_id", "")
        ts = float(item.get("timestamp", time.time()))

        # Dedup: reject timestamp regression for same market
        last = self._last_ts.get(market_id, 0.0)
        if ts < last - 1.0:  # allow 1-second jitter
            log.debug(
                "ws_timestamp_regression_skipped",
                market_id=market_id,
                ts=ts,
                last_ts=last,
            )
            return
        self._last_ts[market_id] = max(last, ts)

        if event_type == "book":
            event = WSEvent(
                type="orderbook",
                market_id=market_id,
                timestamp=ts,
                data={
                    "bids": item.get("bids", []),
                    "asks": item.get("asks", []),
                    "update_type": "snapshot" if item.get("hash") else "delta",
                },
            )
        elif event_type == "price_change":
            # Treat price change as lightweight orderbook delta
            event = WSEvent(
                type="orderbook",
                market_id=market_id,
                timestamp=ts,
                data={
                    "bids": item.get("changes", {}).get("bids", []),
                    "asks": item.get("changes", {}).get("asks", []),
                    "update_type": "delta",
                },
            )
        elif event_type == "trade":
            event = WSEvent(
                type="trade",
                market_id=market_id,
                timestamp=ts,
                data={
                    "price": float(item.get("price", 0.0)),
                    "size": float(item.get("size", 0.0)),
                    "side": item.get("side", "UNKNOWN"),
                    "trade_id": str(item.get("id", "")),
                },
            )
        else:
            # Heartbeat or unknown — update last_message_ts only
            log.debug("ws_unhandled_event_type", event_type=event_type)
            return

        # Non-blocking enqueue with backpressure warning
        try:
            self._queue.put_nowait(event)
            self._stats.events_emitted += 1
        except asyncio.QueueFull:
            log.warning(
                "ws_queue_full_event_dropped",
                market_id=market_id,
                event_type=event.type,
            )

    # ── Heartbeat watchdog ────────────────────────────────────────────────────

    async def _heartbeat_watchdog(self) -> None:
        """Periodic check: if no message received within timeout, force reconnect."""
        while self._running:
            await asyncio.sleep(self._heartbeat_timeout / 2)
            elapsed = time.time() - self._stats.last_message_ts
            if elapsed > self._heartbeat_timeout:
                self._stats.heartbeat_timeouts += 1
                log.warning(
                    "ws_heartbeat_timeout",
                    elapsed_s=round(elapsed, 1),
                    timeout_s=self._heartbeat_timeout,
                )
                # Cancel the WS loop — it will reconnect automatically
                if self._ws_task and not self._ws_task.done():
                    self._ws_task.cancel()
                    self._ws_task = asyncio.create_task(
                        self._run_ws_loop(), name="polymarket_ws_loop"
                    )
