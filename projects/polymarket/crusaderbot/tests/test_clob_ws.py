"""Unit tests for ``ClobWebSocketClient`` (Phase 4D).

Hermetic: NO real ``websockets`` import is exercised. Every socket is a
``FakeWebSocket`` that the test drives directly, and the connect path is
overridden via the ``connect_factory`` constructor seam. The capital-
safety contract — paper mode never opens a socket — is asserted twice:
once via ``start()`` not spawning the run task, once via the factory
never being invoked.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from projects.polymarket.crusaderbot.integrations.clob import ws as ws_module
from projects.polymarket.crusaderbot.integrations.clob.ws import (
    ClobWebSocketClient,
    _backoff_delay,
)


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Settings + fake socket
# ---------------------------------------------------------------------------


class FakeSettings:
    USE_REAL_CLOB = True
    CLOB_WS_URL = "wss://test/ws/user"
    POLYMARKET_API_KEY = "k"
    POLYMARKET_API_SECRET = "c2VjcmV0LWFiY2Q="  # urlsafe-b64 "secret-abcd"
    POLYMARKET_API_PASSPHRASE = "p"
    POLYMARKET_PASSPHRASE = "p"
    POLYMARKET_PRIVATE_KEY = (
        "0x" + "11" * 32  # deterministic deadbeef-style 32-byte key
    )
    WS_RECONNECT_MAX_DELAY_SECONDS = 1
    WS_HEARTBEAT_INTERVAL_SECONDS = 1
    WS_HEARTBEAT_TIMEOUT_SECONDS = 1


class FakeWebSocket:
    """Minimal stand-in for ``websockets.client.WebSocketClientProtocol``.

    The test drives traffic by calling ``feed`` (push a frame the read
    loop will yield) and ``end`` (close the iterator). Everything the
    client sends is captured in ``sent`` for assertions.
    """

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.closed = False
        self._inbox: asyncio.Queue[Any] = asyncio.Queue()
        self._eof = asyncio.Event()

    async def send(self, raw: str) -> None:
        self.sent.append(raw)

    async def close(self) -> None:
        self.closed = True
        self._eof.set()
        # Unblock any pending get() so the consumer exits cleanly.
        await self._inbox.put(_SENTINEL_EOF)

    async def feed(self, payload: Any) -> None:
        await self._inbox.put(payload)

    async def end(self) -> None:
        self._eof.set()
        await self._inbox.put(_SENTINEL_EOF)

    def __aiter__(self) -> "FakeWebSocket":
        return self

    async def __anext__(self) -> Any:
        item = await self._inbox.get()
        if item is _SENTINEL_EOF:
            raise StopAsyncIteration
        return item


_SENTINEL_EOF = object()


# ---------------------------------------------------------------------------
# Paper-mode capital-safety guard
# ---------------------------------------------------------------------------


async def test_paper_mode_start_is_noop_and_factory_never_called():
    settings = FakeSettings()
    settings.USE_REAL_CLOB = False
    factory_calls: list[str] = []

    async def factory(url: str) -> Any:
        factory_calls.append(url)
        raise AssertionError("connect_factory must not be called in paper mode")

    client = ClobWebSocketClient(
        settings=settings, connect_factory=factory,
        on_fill=AsyncMock(), on_order_update=AsyncMock(),
    )
    await client.start()
    assert not client.is_alive()
    assert not client.is_connected()
    assert factory_calls == []
    # Stopping a never-started client is a no-op.
    await client.stop()


# ---------------------------------------------------------------------------
# Backoff math
# ---------------------------------------------------------------------------


def test_backoff_delay_caps_at_max_delay():
    # huge attempt would otherwise produce a huge delay; cap kicks in.
    for _ in range(10):
        delay = _backoff_delay(20, max_delay=5.0)
        assert 0 <= delay <= 5.0 * 1.25 + 0.001


def test_backoff_delay_scales_exponentially_under_cap():
    # Average over many runs to smooth jitter; the ratio must be ~2x.
    samples_a = [_backoff_delay(2, max_delay=120.0, base=1.0) for _ in range(200)]
    samples_b = [_backoff_delay(3, max_delay=120.0, base=1.0) for _ in range(200)]
    avg_a = sum(samples_a) / len(samples_a)
    avg_b = sum(samples_b) / len(samples_b)
    # attempt=2 -> ~2.0, attempt=3 -> ~4.0; jitter is +/-25%.
    assert 1.5 < avg_a < 2.5
    assert 3.0 < avg_b < 5.0


# ---------------------------------------------------------------------------
# Subscribe + dispatch
# ---------------------------------------------------------------------------


async def test_start_opens_socket_and_sends_subscribe_with_auth():
    settings = FakeSettings()
    fake = FakeWebSocket()

    async def factory(url: str) -> FakeWebSocket:
        assert url == settings.CLOB_WS_URL
        return fake

    on_fill = AsyncMock()
    client = ClobWebSocketClient(
        settings=settings, connect_factory=factory,
        on_fill=on_fill, on_order_update=AsyncMock(),
    )
    await client.start()
    # Give the run task a tick to send the subscribe frame.
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert client.is_alive()
    assert len(fake.sent) >= 1
    sub = json.loads(fake.sent[0])
    # Polymarket user-channel subscribe: {auth:{apiKey,secret,passphrase},
    # type:"user", markets:[]}. No L2-HMAC signed headers — those are
    # for the REST endpoints.
    assert sub["type"] == "user"
    assert sub["markets"] == []
    assert sub["auth"]["apiKey"] == "k"
    assert sub["auth"]["secret"] == "c2VjcmV0LWFiY2Q="
    assert sub["auth"]["passphrase"] == "p"
    assert "signature" not in sub["auth"]

    await fake.end()
    await client.stop()


async def test_user_fill_frame_dispatches_to_on_fill():
    settings = FakeSettings()
    fake = FakeWebSocket()

    async def factory(url: str) -> FakeWebSocket:
        return fake

    on_fill = AsyncMock()
    on_order = AsyncMock()
    client = ClobWebSocketClient(
        settings=settings, connect_factory=factory,
        on_fill=on_fill, on_order_update=on_order,
    )
    await client.start()
    await asyncio.sleep(0)

    await fake.feed(json.dumps({
        "event_type": "user_fill",
        "id": "f1", "order_id": "broker-1",
        "price": "0.55", "size": "10", "side": "BUY",
    }))
    # Yield until the dispatcher records the call.
    for _ in range(50):
        if on_fill.await_count >= 1:
            break
        await asyncio.sleep(0.01)

    assert on_fill.await_count == 1
    event = on_fill.await_args.args[0]
    assert event["broker_order_id"] == "broker-1"
    assert event["fill_id"] == "f1"
    assert event["price"] == pytest.approx(0.55)
    assert on_order.await_count == 0

    await fake.end()
    await client.stop()


async def test_unknown_frame_does_not_crash_loop():
    settings = FakeSettings()
    fake = FakeWebSocket()

    async def factory(url: str) -> FakeWebSocket:
        return fake

    on_fill = AsyncMock()
    client = ClobWebSocketClient(
        settings=settings, connect_factory=factory,
        on_fill=on_fill, on_order_update=AsyncMock(),
    )
    await client.start()
    await asyncio.sleep(0)
    # Garbage payload, then a real fill. The fill must still arrive.
    await fake.feed("not-json")
    await fake.feed({"event_type": "totally_unknown"})
    await fake.feed(json.dumps({
        "event_type": "user_fill",
        "id": "f2", "order_id": "b2",
        "price": "0.4", "size": "1",
    }))
    for _ in range(50):
        if on_fill.await_count >= 1:
            break
        await asyncio.sleep(0.01)
    assert on_fill.await_count == 1

    await fake.end()
    await client.stop()


async def test_dispatcher_exception_is_contained():
    settings = FakeSettings()
    fake = FakeWebSocket()

    async def factory(url: str) -> FakeWebSocket:
        return fake

    calls: list[dict] = []

    async def on_fill(event: dict) -> None:
        calls.append(event)
        if len(calls) == 1:
            raise RuntimeError("boom")

    client = ClobWebSocketClient(
        settings=settings, connect_factory=factory,
        on_fill=on_fill, on_order_update=AsyncMock(),
    )
    await client.start()
    await asyncio.sleep(0)
    await fake.feed(json.dumps({
        "event_type": "user_fill", "id": "fa", "order_id": "ba",
        "price": "0.5", "size": "1",
    }))
    await fake.feed(json.dumps({
        "event_type": "user_fill", "id": "fb", "order_id": "bb",
        "price": "0.5", "size": "1",
    }))
    for _ in range(80):
        if len(calls) >= 2:
            break
        await asyncio.sleep(0.01)
    assert len(calls) == 2  # second fill survived first dispatcher's exception

    await fake.end()
    await client.stop()


# ---------------------------------------------------------------------------
# Heartbeat: pong arrives -> alive; pong missed -> recycle
# ---------------------------------------------------------------------------


async def test_heartbeat_pong_keeps_socket_alive():
    settings = FakeSettings()
    fake = FakeWebSocket()
    clock_value = [1000.0]

    def clock() -> float:
        return clock_value[0]

    async def factory(url: str) -> FakeWebSocket:
        return fake

    client = ClobWebSocketClient(
        settings=settings, connect_factory=factory,
        on_fill=AsyncMock(), on_order_update=AsyncMock(),
        clock=clock,
    )
    await client.start()
    await asyncio.sleep(0)
    # Simulate the broker echoing pongs: every time the client sends a
    # plain-text "PING" frame, push back a "PONG" frame and bump the
    # clock to keep the deadline check happy.
    for _ in range(3):
        for _ in range(20):
            if any(s == "PING" for s in fake.sent):
                break
            await asyncio.sleep(0.05)
        fake.sent.clear()
        clock_value[0] += 0.5
        await fake.feed("PONG")
        await asyncio.sleep(0.05)

    assert not fake.closed
    await fake.end()
    await client.stop()


async def test_heartbeat_timeout_recycles_socket():
    settings = FakeSettings()
    fake = FakeWebSocket()
    # Clock starts at zero; never advances pong timestamp.
    clock_value = [0.0]

    def clock() -> float:
        # Advance past the ping+pong window so the deadline check fires.
        clock_value[0] += 5.0
        return clock_value[0]

    async def factory(url: str) -> FakeWebSocket:
        return fake

    client = ClobWebSocketClient(
        settings=settings, connect_factory=factory,
        on_fill=AsyncMock(), on_order_update=AsyncMock(),
        clock=clock,
    )
    await client.start()
    # Wait long enough for one ping interval + timeout window.
    for _ in range(80):
        if fake.closed:
            break
        await asyncio.sleep(0.05)
    assert fake.closed

    await client.stop()


# ---------------------------------------------------------------------------
# Reconnect on socket end
# ---------------------------------------------------------------------------


async def test_socket_end_triggers_reconnect_attempt():
    settings = FakeSettings()
    settings.WS_RECONNECT_MAX_DELAY_SECONDS = 1
    sockets: list[FakeWebSocket] = []

    async def factory(url: str) -> FakeWebSocket:
        ws = FakeWebSocket()
        sockets.append(ws)
        return ws

    client = ClobWebSocketClient(
        settings=settings, connect_factory=factory,
        on_fill=AsyncMock(), on_order_update=AsyncMock(),
    )
    await client.start()
    await asyncio.sleep(0)

    # End the first socket; the run loop should backoff and reconnect.
    assert len(sockets) >= 1
    await sockets[0].end()
    for _ in range(80):
        if len(sockets) >= 2:
            break
        await asyncio.sleep(0.05)
    assert len(sockets) >= 2

    await sockets[-1].end()
    await client.stop()


# ---------------------------------------------------------------------------
# Liveness API
# ---------------------------------------------------------------------------


async def test_is_alive_false_before_start_and_after_stop():
    settings = FakeSettings()
    fake = FakeWebSocket()

    async def factory(url: str) -> FakeWebSocket:
        return fake

    client = ClobWebSocketClient(
        settings=settings, connect_factory=factory,
        on_fill=AsyncMock(), on_order_update=AsyncMock(),
    )
    assert not client.is_alive()
    await client.start()
    await asyncio.sleep(0)
    assert client.is_alive()
    await fake.end()
    await client.stop()
    assert not client.is_alive()


# ---------------------------------------------------------------------------
# Module-level smoke
# ---------------------------------------------------------------------------


def test_module_exposes_client_class():
    assert hasattr(ws_module, "ClobWebSocketClient")
