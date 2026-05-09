"""Unit tests for CLOB error classification + retry semantics.

Covers the Phase 4E contract:

    400 / 401 / 403 -> ClobAuthError, no retry
    429             -> ClobRateLimitError, retry with backoff
    500/502/503/504 -> ClobServerError, retry with backoff
    httpx timeout   -> ClobTimeoutError, retry
    httpx network   -> ClobNetworkError, retry
    max retries     -> ClobMaxRetriesError

Tests build adapters with ``CIRCUIT_BREAKER_THRESHOLD`` set very high so
the breaker never trips during the retry test -- the breaker has its own
test file and we want one fault domain per test.
"""
from __future__ import annotations

import base64

import httpx
import pytest

from projects.polymarket.crusaderbot.integrations.clob.adapter import (
    ClobAdapter,
    _classify_http_error,
)
from projects.polymarket.crusaderbot.integrations.clob.circuit_breaker import (
    CircuitBreaker,
)
from projects.polymarket.crusaderbot.integrations.clob.exceptions import (
    ClobAPIError,
    ClobAuthError,
    ClobMaxRetriesError,
    ClobNetworkError,
    ClobRateLimitError,
    ClobServerError,
    ClobTimeoutError,
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


@pytest.fixture
def adapter_factory(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ClobAdapter, "_build_signed_order", _stub_signed_order)

    def _build(handler, *, max_retries=3):
        transport = httpx.MockTransport(handler)
        # Threshold high so the breaker never trips during error
        # classification tests; rate limiter disabled so timing is
        # deterministic.
        breaker = CircuitBreaker(
            threshold=10_000, reset_seconds=60.0, name="test",
        )
        limiter = RateLimiter(rps=0)
        return ClobAdapter(
            api_key="api-k",
            api_secret=DETERMINISTIC_SECRET,
            passphrase="pp",
            private_key=DETERMINISTIC_PK,
            transport=transport,
            max_retries=max_retries,
            circuit_breaker=breaker,
            rate_limiter=limiter,
        )

    return _build


# --- pure classifier -----------------------------------------------


def test_classifier_400_401_403_maps_to_auth_error():
    for sc in (400, 401, 403):
        exc = _classify_http_error(sc, path="/order", body="boom")
        assert isinstance(exc, ClobAuthError)
        assert exc.status_code == sc


def test_classifier_429_maps_to_rate_limit():
    exc = _classify_http_error(429, path="/order", body="slow down")
    assert isinstance(exc, ClobRateLimitError)
    assert exc.status_code == 429


@pytest.mark.parametrize("sc", [500, 502, 503, 504])
def test_classifier_5xx_maps_to_server_error(sc):
    exc = _classify_http_error(sc, path="/order", body="upstream")
    assert isinstance(exc, ClobServerError)
    assert exc.status_code == sc


def test_classifier_other_4xx_maps_to_generic_api_error():
    exc = _classify_http_error(404, path="/data/order/x", body="missing")
    assert isinstance(exc, ClobAPIError)
    assert not isinstance(exc, ClobAuthError)
    assert not isinstance(exc, ClobRateLimitError)
    assert not isinstance(exc, ClobServerError)


# --- live adapter behavior -----------------------------------------


@pytest.mark.parametrize("status", [400, 401, 403])
async def test_auth_class_is_not_retried(adapter_factory, status):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(status, text="auth fail")

    with pytest.raises(ClobAuthError) as info:
        async with adapter_factory(handler) as a:
            await a.post_order(token_id="T", side="BUY", price=0.5, size=10)
    assert info.value.status_code == status
    assert calls["n"] == 1


async def test_429_is_retried_then_wraps_max_retries(adapter_factory):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(429, text="slow down")

    with pytest.raises(ClobMaxRetriesError) as info:
        async with adapter_factory(handler, max_retries=3) as a:
            await a.post_order(token_id="T", side="BUY", price=0.5, size=10)
    assert calls["n"] == 3
    assert isinstance(info.value.last_exception, ClobRateLimitError)


async def test_503_is_retried_then_wraps_max_retries(adapter_factory):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(503, text="upstream")

    with pytest.raises(ClobMaxRetriesError) as info:
        async with adapter_factory(handler, max_retries=3) as a:
            await a.post_order(token_id="T", side="BUY", price=0.5, size=10)
    assert calls["n"] == 3
    assert isinstance(info.value.last_exception, ClobServerError)


async def test_timeout_classified_and_retried(adapter_factory):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        raise httpx.ConnectTimeout("timed out")

    with pytest.raises(ClobMaxRetriesError) as info:
        async with adapter_factory(handler, max_retries=3) as a:
            await a.post_order(token_id="T", side="BUY", price=0.5, size=10)
    assert calls["n"] == 3
    assert isinstance(info.value.last_exception, ClobTimeoutError)


async def test_network_error_classified_and_retried(adapter_factory):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        raise httpx.ConnectError("conn refused")

    with pytest.raises(ClobMaxRetriesError) as info:
        async with adapter_factory(handler, max_retries=3) as a:
            await a.post_order(token_id="T", side="BUY", price=0.5, size=10)
    assert calls["n"] == 3
    assert isinstance(info.value.last_exception, ClobNetworkError)


async def test_eventual_success_after_one_retry(adapter_factory):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, text="hiccup")
        return httpx.Response(200, json={"orderID": "abc"})

    async with adapter_factory(handler, max_retries=3) as a:
        out = await a.post_order(token_id="T", side="BUY", price=0.5, size=10)
    assert out == {"orderID": "abc"}
    assert calls["n"] == 2
