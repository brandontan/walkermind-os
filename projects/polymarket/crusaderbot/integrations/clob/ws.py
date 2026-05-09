"""Polymarket CLOB WebSocket client (Phase 4D).

Push-based fill streaming. The client opens a single connection to
``wss://ws-subscriptions-clob.polymarket.com/ws``, subscribes to the
``user`` channel with L2 HMAC auth, and dispatches normalised fill +
order-update events into ``OrderLifecycleManager``. Polling stays
registered as a fallback; the lifecycle manager's
``ON CONFLICT (fill_id) DO NOTHING`` constraint makes the dual-source
model naturally idempotent.

Hard rules respected:

* USE_REAL_CLOB=False -> ``connect()`` is a no-op. The socket is NEVER
  opened in paper mode, even if a job tries to call us. This is the
  capital-safety boundary that guarantees CI cannot accidentally hit
  the broker.
* Reconnect with exponential backoff + jitter, capped at
  ``WS_RECONNECT_MAX_DELAY_SECONDS``.
* Application-level heartbeat: send a ping every
  ``WS_HEARTBEAT_INTERVAL_SECONDS``; if no pong within
  ``WS_HEARTBEAT_TIMEOUT_SECONDS`` the socket is recycled.
* Graceful shutdown: ``stop()`` cancels the run loop and closes the
  socket; safe to await even if the client never connected.
* Per-message error containment: a malformed frame is logged but the
  loop keeps running.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import random
import time
from typing import Any, Awaitable, Callable, Optional

from ...config import Settings, get_settings
from .auth import ClobAuthSigner, build_l2_headers
from . import ws_handler

logger = logging.getLogger(__name__)

# Type aliases for the dispatcher callbacks the lifecycle layer plugs in.
FillDispatcher = Callable[[dict], Awaitable[None]]
OrderUpdateDispatcher = Callable[[dict], Awaitable[None]]

# Initial reconnect delay before the exponential ramp. 1s avoids spamming
# the broker on a brief network blip while still recovering quickly.
INITIAL_BACKOFF_SECONDS = 1.0


def _now_monotonic() -> float:
    """Indirection used by tests to drive the heartbeat clock."""
    return time.monotonic()


def _backoff_delay(
    attempt: int, *, max_delay: float,
    base: float = INITIAL_BACKOFF_SECONDS,
) -> float:
    """Exponential backoff with +/-25% jitter, clipped at ``max_delay``.

    ``attempt`` is 1-indexed: attempt=1 -> ~base, attempt=2 -> ~2*base, etc.
    Jitter prevents thundering-herd reconnect against the broker after a
    region-wide blip.
    """
    raw = base * (2 ** max(0, attempt - 1))
    capped = min(raw, max_delay)
    jitter = capped * 0.25
    return max(0.0, capped + random.uniform(-jitter, jitter))


class ClobWebSocketClient:
    """Manages one persistent ``wss://`` connection to Polymarket CLOB.

    The client owns three async tasks once started:
        * ``_run_loop`` — connect / read / dispatch / reconnect.
        * ``_heartbeat_loop`` — periodic ping + pong-deadline tracking.
        * (the consumer task is whatever loop awaits ``connect()``.)

    Test seams: every external dependency is injected via constructor
    (settings, dispatchers, ``connect_factory``) so no real WebSocket is
    opened in unit tests.
    """

    def __init__(
        self,
        *,
        settings: Optional[Settings] = None,
        on_fill: Optional[FillDispatcher] = None,
        on_order_update: Optional[OrderUpdateDispatcher] = None,
        connect_factory: Optional[Callable[..., Any]] = None,
        clock: Callable[[], float] = _now_monotonic,
    ) -> None:
        self._settings = settings
        self._on_fill = on_fill
        self._on_order_update = on_order_update
        self._connect_factory = connect_factory
        self._clock = clock

        self._ws: Any = None
        self._run_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._connected_event = asyncio.Event()
        self._last_pong_at: float = 0.0
        self._connect_attempts = 0

    # ----- public surface --------------------------------------------------

    def is_alive(self) -> bool:
        """True iff the run loop task is active.

        Used by the APScheduler watchdog to decide whether to relaunch.
        ``False`` covers both "never started" and "task crashed and
        exited" — both demand a reconnect.
        """
        return self._run_task is not None and not self._run_task.done()

    def is_connected(self) -> bool:
        """True iff the underlying socket is currently open."""
        return self._connected_event.is_set()

    async def start(self) -> None:
        """Spawn the run loop. Returns immediately.

        Paper-mode short-circuit: when ``USE_REAL_CLOB`` is False the
        run loop is NOT spawned. The capital-safety contract is that
        no broker traffic is generated unless the operator has flipped
        the toggle explicitly.
        """
        s = self._settings or get_settings()
        if not s.USE_REAL_CLOB:
            logger.info(
                "ws: USE_REAL_CLOB=False, WebSocket client will not open"
            )
            return
        if self.is_alive():
            return
        self._stop_event.clear()
        self._run_task = asyncio.create_task(
            self._run_loop(s), name="clob-ws-run"
        )

    async def stop(self) -> None:
        """Signal the run loop to shut down and await its exit."""
        self._stop_event.set()
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._heartbeat_task
            self._heartbeat_task = None
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()
            self._ws = None
        if self._run_task is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._run_task
            self._run_task = None
        self._connected_event.clear()

    # ----- internals -------------------------------------------------------

    async def _run_loop(self, s: Settings) -> None:
        """Outer connect-with-backoff loop.

        Each iteration:
            1. compute backoff delay (skipped on first attempt).
            2. open the socket via ``_open_connection``.
            3. send subscribe frame.
            4. read messages until the socket dies or stop is signalled.
            5. close + reset state, return to step 1.
        """
        max_delay = float(s.WS_RECONNECT_MAX_DELAY_SECONDS)
        while not self._stop_event.is_set():
            self._connect_attempts += 1
            if self._connect_attempts > 1:
                delay = _backoff_delay(
                    self._connect_attempts - 1, max_delay=max_delay,
                )
                logger.info(
                    "ws: reconnect attempt %s in %.2fs",
                    self._connect_attempts, delay,
                )
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=delay,
                    )
                    return  # stop signalled during backoff
                except asyncio.TimeoutError:
                    pass

            try:
                await self._connect_and_read(s)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("ws: session ended with error: %s", exc)
            else:
                logger.info("ws: session ended cleanly")

    async def _connect_and_read(self, s: Settings) -> None:
        """One socket lifetime: open, subscribe, drain, close."""
        ws = await self._open_connection(s)
        self._ws = ws
        self._connected_event.set()
        # Reset attempt counter on a successful open so the next
        # disconnect starts the backoff ramp from zero, not from
        # wherever the previous outage left off.
        self._connect_attempts = 1
        self._last_pong_at = self._clock()
        try:
            await self._send_subscribe(ws, s)
            self._heartbeat_task = asyncio.create_task(
                self._heartbeat_loop(ws, s), name="clob-ws-heartbeat",
            )
            await self._read_loop(ws)
        finally:
            if self._heartbeat_task is not None:
                self._heartbeat_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await self._heartbeat_task
                self._heartbeat_task = None
            with contextlib.suppress(Exception):
                await ws.close()
            self._ws = None
            self._connected_event.clear()

    async def _open_connection(self, s: Settings) -> Any:
        """Open the socket via the injected factory or ``websockets.connect``.

        We keep ``websockets`` as a soft import so the unit tests can
        run on machines without it installed; production deploys list
        it as a hard dependency in ``pyproject.toml``.
        """
        if self._connect_factory is not None:
            return await self._connect_factory(s.CLOB_WS_URL)
        # Lazy import — keeps test environments without ``websockets``
        # functional and surfaces the missing dep with a clear error
        # instead of an ImportError at module load.
        try:
            import websockets  # type: ignore
        except ImportError as exc:  # pragma: no cover - exercised only on missing dep
            raise RuntimeError(
                "websockets package not installed; add to pyproject.toml"
            ) from exc
        return await websockets.connect(
            s.CLOB_WS_URL,
            ping_interval=None,  # we run an app-level heartbeat instead.
            close_timeout=5,
        )

    async def _send_subscribe(self, ws: Any, s: Settings) -> None:
        """Send the ``user`` channel subscribe frame with L2 auth headers."""
        signer = ClobAuthSigner(private_key=s.POLYMARKET_PRIVATE_KEY or "")
        passphrase = s.POLYMARKET_API_PASSPHRASE or s.POLYMARKET_PASSPHRASE or ""
        auth_headers = build_l2_headers(
            api_key=s.POLYMARKET_API_KEY or "",
            api_secret=s.POLYMARKET_API_SECRET or "",
            passphrase=passphrase,
            address=signer.address,
            method="GET",
            path="/ws",
        )
        # Polymarket WS expects the auth payload inside the subscribe
        # message itself. Header-based auth is a HTTP-only convention.
        # We pass through every L2 header value into ``auth`` so the
        # broker can verify the signature against the same fields.
        frame = {
            "type": "subscribe",
            "channel": "user",
            "auth": {
                "apiKey": auth_headers["POLY_API_KEY"],
                "passphrase": auth_headers["POLY_PASSPHRASE"],
                "signature": auth_headers["POLY_SIGNATURE"],
                "timestamp": auth_headers["POLY_TIMESTAMP"],
                "address": auth_headers["POLY_ADDRESS"],
            },
        }
        await ws.send(json.dumps(frame))

    async def _read_loop(self, ws: Any) -> None:
        """Drain frames until the socket closes or stop is signalled."""
        async for raw in ws:
            if self._stop_event.is_set():
                return
            await self._dispatch_raw(raw)

    async def _dispatch_raw(self, raw: Any) -> None:
        """Parse a single frame and forward each derived event.

        ALL exceptions are caught — a single malformed frame must not
        bring down the read loop and stop subsequent fills from being
        recorded.
        """
        try:
            payload = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
        except (TypeError, ValueError) as exc:
            logger.warning("ws: dropping non-JSON frame: %s", exc)
            return

        # Heartbeat reply: peer echoes ``pong`` either as a top-level
        # event or by setting ``type=pong`` on a subscribe ack. Both
        # advance the watchdog deadline.
        if isinstance(payload, dict) and (
            payload.get("type") == "pong"
            or payload.get("event_type") == "pong"
        ):
            self._last_pong_at = self._clock()
            return

        events = ws_handler.parse_message(payload)
        for event in events:
            try:
                await self._fanout(event)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "ws: dispatcher failed for %s: %s",
                    event.get("kind"), exc, exc_info=True,
                )

    async def _fanout(self, event: dict) -> None:
        kind = event.get("kind")
        if kind == ws_handler.EVENT_FILL and self._on_fill is not None:
            await self._on_fill(event)
            return
        if (
            kind == ws_handler.EVENT_ORDER_UPDATE
            and self._on_order_update is not None
        ):
            await self._on_order_update(event)

    async def _heartbeat_loop(self, ws: Any, s: Settings) -> None:
        """Periodic ping with deadline enforcement.

        The deadline is computed from ``_last_pong_at`` so a pong that
        arrives during the sleep correctly resets the clock without
        racing this task.
        """
        interval = float(s.WS_HEARTBEAT_INTERVAL_SECONDS)
        timeout = float(s.WS_HEARTBEAT_TIMEOUT_SECONDS)
        try:
            while not self._stop_event.is_set():
                await asyncio.sleep(interval)
                if self._stop_event.is_set():
                    return
                try:
                    await ws.send(json.dumps({"type": "ping"}))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("ws: heartbeat send failed: %s", exc)
                    with contextlib.suppress(Exception):
                        await ws.close()
                    return
                # Wait one full timeout window before declaring death;
                # a pong arriving inside this window updates
                # ``_last_pong_at`` via ``_dispatch_raw``.
                await asyncio.sleep(timeout)
                if self._stop_event.is_set():
                    return
                if self._clock() - self._last_pong_at > interval + timeout:
                    logger.warning(
                        "ws: heartbeat timeout, recycling socket"
                    )
                    with contextlib.suppress(Exception):
                        await ws.close()
                    return
        except asyncio.CancelledError:
            return
