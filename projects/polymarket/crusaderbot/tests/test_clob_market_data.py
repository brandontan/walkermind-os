"""Tests for MarketDataClient — unauthenticated read endpoints.

Stubs the network with ``httpx.MockTransport``; verifies query params,
URL paths, and response parsing for every method on the public surface.
"""
from __future__ import annotations

import httpx
import pytest

from projects.polymarket.crusaderbot.integrations.clob.exceptions import (
    ClobAPIError,
)
from projects.polymarket.crusaderbot.integrations.clob.market_data import (
    MarketDataClient,
)


pytestmark = pytest.mark.asyncio


def _client(handler):
    return MarketDataClient(transport=httpx.MockTransport(handler))


async def test_get_orderbook_passes_token_id_param():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(
            200, json={"bids": [{"price": "0.50", "size": "10"}], "asks": []},
        )

    async with _client(handler) as md:
        book = await md.get_orderbook("TKN")

    assert book["bids"][0]["price"] == "0.50"
    assert "/book" in captured["url"]
    assert "token_id=TKN" in captured["url"]


async def test_get_midpoint_and_spread_paths():
    paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, json={"mid": "0.5", "spread": "0.02"})

    async with _client(handler) as md:
        await md.get_midpoint("T")
        await md.get_spread("T")

    assert paths == ["/midpoint", "/spread"]


async def test_get_price_uppercases_side():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"price": "0.5"})

    async with _client(handler) as md:
        await md.get_price("T", side="buy")

    assert "side=BUY" in captured["url"]


async def test_get_market_uses_path_param():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        return httpx.Response(200, json={"condition_id": "0xabc"})

    async with _client(handler) as md:
        await md.get_market("0xabc")

    assert captured["path"] == "/markets/0xabc"


async def test_get_markets_pagination_passes_cursor():
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(str(request.url))
        return httpx.Response(
            200, json={"data": [], "next_cursor": "MA=="},
        )

    async with _client(handler) as md:
        await md.get_markets()
        await md.get_markets(next_cursor="MA==")

    assert "next_cursor" not in captured[0]
    assert "next_cursor=MA%3D%3D" in captured[1] or "next_cursor=MA==" in captured[1]


async def test_get_tick_size_returns_string():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"minimum_tick_size": "0.01"})

    async with _client(handler) as md:
        ts = await md.get_tick_size("T")
    assert ts == "0.01"


async def test_get_neg_risk_returns_bool():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"neg_risk": True})

    async with _client(handler) as md:
        flag = await md.get_neg_risk("T")
    assert flag is True


async def test_4xx_raises_api_error_no_retry():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404, text="not found")

    with pytest.raises(ClobAPIError) as exc:
        async with _client(handler) as md:
            await md.get_orderbook("missing")

    assert exc.value.status_code == 404
    assert calls["n"] == 1  # no retry on 4xx


async def test_5xx_retries_then_raises():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(502, text="bad gateway")

    with pytest.raises(httpx.HTTPStatusError):
        async with _client(handler) as md:
            await md.get_orderbook("T")
    assert calls["n"] == 3


async def test_no_credentials_required():
    """The market-data path must work without any Polymarket secrets —
    that's the whole point of separating it from ClobAdapter.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        # Reject if we ever leak L2/L1 headers on the unauth path
        for h in request.headers:
            assert not h.lower().startswith("poly_"), (
                f"market-data leaked auth header {h}"
            )
        return httpx.Response(200, json={"bids": [], "asks": []})

    async with _client(handler) as md:
        await md.get_orderbook("T")
