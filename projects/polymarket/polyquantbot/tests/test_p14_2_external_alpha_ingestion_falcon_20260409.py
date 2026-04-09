from __future__ import annotations

import asyncio
from typing import Any

from projects.polymarket.polyquantbot.data import market_context
from projects.polymarket.polyquantbot.data.ingestion import falcon_alpha
from projects.polymarket.polyquantbot.data.ingestion.falcon_alpha import (
    FalconAPIClient,
    FalconPagination,
    fetch_candles,
    fetch_external_alpha_with_fallback,
    fetch_markets,
    fetch_orderbook,
    fetch_trades,
    normalize_external_signal,
)
from projects.polymarket.polyquantbot.data.market_context import get_market_context_with_external_alpha


class _CaptureTransport:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.payloads: list[dict[str, Any]] = []

    async def __call__(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.payloads.append(payload)
        if not self.responses:
            raise RuntimeError("no_more_responses")
        return self.responses.pop(0)


def test_api_calls_success_and_parse_rows() -> None:
    async def _run() -> None:
        transport = _CaptureTransport(
            responses=[
                {"data": [{"market_id": "m1", "title": "Election"}]},
                {"data": [{"wallet": "0xa", "size": 2400}]},
                {"data": [{"close": 0.51}, {"close": 0.56}]},
                {"data": [{"side": "bid", "price": 0.51, "depth": 9000}]},
            ]
        )
        client = FalconAPIClient(transport=transport)

        markets = await fetch_markets(client, params={"market_id": "m1"}, pagination=FalconPagination(limit=500, offset=0))
        trades = await fetch_trades(client, params={"market_id": "m1"})
        candles = await fetch_candles(client, params={"token_id": "t1"})
        orderbook = await fetch_orderbook(client, params={"token_id": "t1"})

        assert markets[0]["market_id"] == "m1"
        assert trades[0]["wallet"] == "0xa"
        assert candles[-1]["close"] == 0.56
        assert orderbook[0]["side"] == "bid"

        # bounded payload safety checks
        first_payload = transport.payloads[0]
        assert first_payload["agent_id"] == 574
        assert first_payload["pagination"]["limit"] == 200
        assert first_payload["params"]["market_id"] == "m1"
        assert first_payload["formatter_config"] == {"format_type": "raw"}

    asyncio.run(_run())


def test_normalization_correctness_and_deterministic_shape() -> None:
    normalized = normalize_external_signal(
        market={"market_id": "m2", "market_title": "Fed Decision", "price": 0.44, "volume": 120000},
        trades=[
            {"wallet": "0xaaa", "size": 1500},
            {"wallet": "0xaaa", "size": 2600},
            {"wallet": "0xaaa", "size": 2800},
            {"wallet": "0xbbb", "size": 200},
        ],
        candles=[{"close": 0.40}, {"close": 0.42}, {"close": 0.46}],
        orderbook=[
            {"side": "bid", "price": 0.45, "depth": 12000},
            {"side": "ask", "price": 0.46, "depth": 13000},
        ],
    )

    assert set(normalized.keys()) == {
        "market_id",
        "market_title",
        "price",
        "volume",
        "momentum",
        "liquidity",
        "smart_money_indicator",
        "volatility_snapshot",
    }
    assert normalized["market_id"] == "m2"
    assert normalized["market_title"] == "Fed Decision"
    assert isinstance(normalized["momentum"], float)
    assert isinstance(normalized["smart_money_indicator"], float)
    assert normalized["liquidity"] == 25000.0


def test_failure_fallback_and_context_integration() -> None:
    async def _run() -> None:
        async def failing_transport(_: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("falcon_down")

        client = FalconAPIClient(transport=failing_transport)
        alpha = await fetch_external_alpha_with_fallback(client, market_id="m3", token_id="t3")
        assert alpha == {
            "market_id": "m3",
            "market_title": "Market m3",
            "price": 0.0,
            "volume": 0.0,
            "momentum": 0.0,
            "liquidity": 0.0,
            "smart_money_indicator": 0.0,
            "volatility_snapshot": 0.0,
        }

    asyncio.run(_run())


def test_runtime_proof_samples_market_trade_and_normalized_output() -> None:
    async def _run() -> None:
        transport = _CaptureTransport(
            responses=[
                {"data": [{"market_id": "m4", "market_title": "AI Act", "price": 0.61, "volume": 90000}]},
                {
                    "data": [
                        {"wallet": "0x1", "size": 2100},
                        {"wallet": "0x1", "size": 2300},
                        {"wallet": "0x1", "size": 2500},
                    ]
                },
                {"data": [{"close": 0.58}, {"close": 0.60}, {"close": 0.61}]},
                {
                    "data": [
                        {"side": "bid", "price": 0.60, "depth": 11000},
                        {"side": "ask", "price": 0.62, "depth": 12000},
                    ]
                },
            ]
        )
        client = FalconAPIClient(transport=transport)
        context = await get_market_context_with_external_alpha(
            market_id="m4",
            token_id="t4",
            falcon_client=client,
        )

        # runtime proof tuple: market fetch sample, trade sample, normalized output sample
        assert context["market_title"] == "AI Act"
        assert context["liquidity_usd"] == 23000.0
        assert context["smart_money_score"] > 0.0
        assert context["momentum"] > 0.0

    asyncio.run(_run())


def test_market_id_only_resolves_real_title_and_portfolio_context() -> None:
    async def _run() -> None:
        falcon_alpha._market_title_cache.clear()
        market_context.market_cache.clear()
        market_context.market_title_cache.clear()

        transport = _CaptureTransport(
            responses=[
                {"data": [{"market_id": "540816", "question": "Will BTC close above $120k in 2026?", "price": 0.61, "volume": 90000}]},
                {"data": [{"wallet": "0x1", "size": 2100}]},
                {"data": [{"close": 0.58}, {"close": 0.60}, {"close": 0.61}]},
                {"data": [{"side": "bid", "price": 0.60, "depth": 11000}, {"side": "ask", "price": 0.62, "depth": 12000}]},
            ]
        )
        client = FalconAPIClient(transport=transport)

        context = await get_market_context_with_external_alpha(
            market_id="540816",
            token_id="t540816",
            falcon_client=client,
        )

        assert context["market_title"] == "Will BTC close above $120k in 2026?"
        assert context["market_title"] != "Market 540816"

    asyncio.run(_run())


def test_multiple_market_ids_resolve_all_titles() -> None:
    async def _run() -> None:
        falcon_alpha._market_title_cache.clear()
        market_context.market_cache.clear()
        market_context.market_title_cache.clear()

        m1 = normalize_external_signal(
            market={"market_id": "m100", "question": "Will ETH close above $6k?", "price": 0.44, "volume": 120000},
            trades=[{"wallet": "0xaaa", "size": 1500}],
            candles=[{"close": 0.40}, {"close": 0.42}],
            orderbook=[{"side": "bid", "price": 0.41, "depth": 12000}, {"side": "ask", "price": 0.42, "depth": 13000}],
        )
        m2 = normalize_external_signal(
            market={"market_id": "m200", "title": "Will SOL close above $300?", "price": 0.54, "volume": 110000},
            trades=[{"wallet": "0xbbb", "size": 2500}],
            candles=[{"close": 0.50}, {"close": 0.53}],
            orderbook=[{"side": "bid", "price": 0.52, "depth": 15000}, {"side": "ask", "price": 0.53, "depth": 14000}],
        )

        assert m1["market_title"] == "Will ETH close above $6k?"
        assert m2["market_title"] == "Will SOL close above $300?"

    asyncio.run(_run())


def test_fallback_uses_cached_title_when_api_unavailable() -> None:
    async def _run() -> None:
        falcon_alpha._market_title_cache.clear()
        falcon_alpha._market_title_cache["m500"] = "Will CPI print under 2.5%?"

        async def failing_transport(_: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("falcon_down")

        client = FalconAPIClient(transport=failing_transport)
        alpha = await fetch_external_alpha_with_fallback(client, market_id="m500", token_id="t500")

        assert alpha["market_title"] == "Will CPI print under 2.5%?"
        assert alpha["market_title"] != "Market m500"

    asyncio.run(_run())


def test_partial_falcon_failure_uses_resolved_market_title_not_numeric_placeholder() -> None:
    async def _run() -> None:
        falcon_alpha._market_title_cache.clear()

        transport = _CaptureTransport(
            responses=[
                {"data": [{"market_id": "m900", "question": "Will Fed cut rates in June?", "price": 0.52, "volume": 88000}]},
            ]
        )
        client = FalconAPIClient(transport=transport)
        alpha = await fetch_external_alpha_with_fallback(client, market_id="m900", token_id="t900")

        assert alpha["market_title"] == "Will Fed cut rates in June?"
        assert alpha["market_title"] != "Market m900"

    asyncio.run(_run())
