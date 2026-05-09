"""Integration test: circuit breaker wrapping ClobAdapter.post_order /
cancel_order / get_order trips on consecutive transport failures and
short-circuits with no broker call.

Separated from ``test_clob_circuit_breaker.py`` (which covers the breaker
in isolation) so this file documents the wiring contract -- if the
adapter ever bypasses the breaker, this file fails loudly.
"""
from __future__ import annotations

import base64

import httpx
import pytest

from projects.polymarket.crusaderbot.integrations.clob.adapter import (
    ClobAdapter,
)
from projects.polymarket.crusaderbot.integrations.clob.circuit_breaker import (
    CircuitBreaker,
    STATE_OPEN,
)
from projects.polymarket.crusaderbot.integrations.clob.exceptions import (
    ClobCircuitOpenError,
    ClobMaxRetriesError,
)
from projects.polymarket.crusaderbot.integrations.clob.rate_limiter import (
    RateLimiter,
)


pytestmark = pytest.mark.asyncio


DETERMINISTIC_PK = "0x" + ("aa" * 32)
DETERMINISTIC_SECRET = base64.urlsafe_b64encode(
    b"test-secret-32-bytes-for-hmac-aa"
).decode()


def _stub_signed_order(self, *, token_id, side, price, size, **_kwargs):
    return {
        "orderType": "GTC",
        "tokenId": token_id,
        "side": side.upper(),
        "price": str(price),
        "size": str(size),
        "signature": "0xstub",
        "salt": "0",
        "maker": self._funder,
    }


def _make_adapter(handler, *, threshold: int, on_open=None, max_retries: int = 1):
    breaker = CircuitBreaker(
        threshold=threshold, reset_seconds=60.0, on_open=on_open, name="test",
    )
    return ClobAdapter(
        api_key="api-k",
        api_secret=DETERMINISTIC_SECRET,
        passphrase="pp",
        private_key=DETERMINISTIC_PK,
        transport=httpx.MockTransport(handler),
        max_retries=max_retries,
        circuit_breaker=breaker,
        rate_limiter=RateLimiter(rps=0),
    )


async def test_post_order_trips_breaker_after_threshold(monkeypatch):
    monkeypatch.setattr(ClobAdapter, "_build_signed_order", _stub_signed_order)
    fired = []

    async def on_open(name):
        fired.append(name)

    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(503, text="upstream")

    a = _make_adapter(handler, threshold=2, on_open=on_open, max_retries=1)
    try:
        with pytest.raises(ClobMaxRetriesError):
            await a.post_order(token_id="T", side="BUY", price=0.5, size=10)
        with pytest.raises(ClobMaxRetriesError):
            await a.post_order(token_id="T", side="BUY", price=0.5, size=10)
    finally:
        await a.aclose()

    assert a.circuit_breaker.state == STATE_OPEN
    assert fired == ["test"]


async def test_post_order_open_circuit_skips_broker_call(monkeypatch):
    monkeypatch.setattr(ClobAdapter, "_build_signed_order", _stub_signed_order)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(503, text="upstream")

    a = _make_adapter(handler, threshold=2, max_retries=1)
    try:
        with pytest.raises(ClobMaxRetriesError):
            await a.post_order(token_id="T", side="BUY", price=0.5, size=10)
        with pytest.raises(ClobMaxRetriesError):
            await a.post_order(token_id="T", side="BUY", price=0.5, size=10)
        assert a.circuit_breaker.state == STATE_OPEN
        pre_calls = calls["n"]
        with pytest.raises(ClobCircuitOpenError):
            await a.post_order(token_id="T", side="BUY", price=0.5, size=10)
        assert calls["n"] == pre_calls  # broker NOT called
    finally:
        await a.aclose()


async def test_cancel_order_open_circuit_skips_broker_call(monkeypatch):
    monkeypatch.setattr(ClobAdapter, "_build_signed_order", _stub_signed_order)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(503, text="upstream")

    a = _make_adapter(handler, threshold=1, max_retries=1)
    try:
        with pytest.raises(ClobMaxRetriesError):
            await a.cancel_order("abc")
        assert a.circuit_breaker.state == STATE_OPEN
        pre_calls = calls["n"]
        with pytest.raises(ClobCircuitOpenError):
            await a.cancel_order("abc")
        assert calls["n"] == pre_calls
    finally:
        await a.aclose()


async def test_get_order_open_circuit_skips_broker_call(monkeypatch):
    monkeypatch.setattr(ClobAdapter, "_build_signed_order", _stub_signed_order)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(503, text="upstream")

    a = _make_adapter(handler, threshold=1, max_retries=1)
    try:
        with pytest.raises(ClobMaxRetriesError):
            await a.get_order("abc")
        assert a.circuit_breaker.state == STATE_OPEN
        pre_calls = calls["n"]
        with pytest.raises(ClobCircuitOpenError):
            await a.get_order("abc")
        assert calls["n"] == pre_calls
    finally:
        await a.aclose()
