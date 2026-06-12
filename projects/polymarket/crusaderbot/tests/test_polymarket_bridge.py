from __future__ import annotations

from decimal import Decimal

import pytest

from projects.polymarket.crusaderbot.integrations import polymarket_bridge as bridge


SUPPORTED_ASSETS = {
    "supportedAssets": [
        {
            "chainId": "137",
            "chainName": "Polygon",
            "token": {
                "name": "USD Coin (PoS) (USDC.e)",
                "symbol": "USDC.e",
                "address": bridge.USDCE_POLYGON,
                "decimals": 6,
            },
            "minCheckoutUsd": 2,
        },
        {
            "chainId": "137",
            "chainName": "Polygon",
            "token": {
                "name": "USDC",
                "symbol": "USDC",
                "address": bridge.NATIVE_USDC_POLYGON,
                "decimals": 6,
            },
            "minCheckoutUsd": 2,
        },
        {
            "chainId": "137",
            "chainName": "Polygon",
            "token": {
                "name": "Wormhole Bridged USDT",
                "symbol": "USDT",
                "address": bridge.BRIDGE_USDT_POLYGON,
                "decimals": 6,
            },
            "minCheckoutUsd": 2,
        },
        {
            "chainId": "137",
            "chainName": "Polygon",
            "token": {
                "name": "Polymarket USD",
                "symbol": "pUSD",
                "address": bridge.PUSD_POLYGON,
                "decimals": 6,
            },
            "minCheckoutUsd": 2,
        },
    ]
}


def test_supported_assets_parse_polygon_usdc_usdt_pusd_matrix():
    assets = bridge.parse_supported_assets(SUPPORTED_ASSETS)
    matrix = bridge.required_polygon_bridge_assets_present(assets)
    assert matrix == {"USDC.e": True, "USDC": True, "USDT": True, "pUSD": True}
    native = bridge.polygon_asset_by_address(assets, bridge.NATIVE_USDC_POLYGON)
    assert native is not None
    assert native.symbol == "USDC"
    assert native.min_checkout_usd == Decimal("2")


def test_deposit_addresses_parser_keeps_raw_evm_copy_surface():
    parsed = bridge.parse_deposit_addresses({
        "address": {"evm": "0x" + "12" * 20, "svm": "sol", "btc": "bc1"},
        "note": "Only certain chains and tokens are supported.",
    })
    assert parsed.evm == "0x" + "12" * 20
    assert parsed.note and "supported" in parsed.note


def test_quote_payload_targets_polygon_pusd(monkeypatch):
    seen = {}

    async def fake_request(method, path, *, json_body=None):
        seen.update({"method": method, "path": path, "json_body": json_body})
        return {
            "quoteId": "qid",
            "estToTokenBaseUnit": "14491203",
            "estInputUsd": 14.488305,
            "estOutputUsd": 14.488305,
            "estFeeBreakdown": {"minReceived": 14.488305},
        }

    monkeypatch.setattr(bridge, "_request_json", fake_request)
    import asyncio
    quote = asyncio.run(bridge.get_quote(
        from_amount_base_unit="10000000",
        from_chain_id=137,
        from_token_address=bridge.NATIVE_USDC_POLYGON,
        recipient_address="0x" + "34" * 20,
    ))
    assert quote.quote_id == "qid"
    assert seen["method"] == "POST"
    assert seen["path"] == "/quote"
    assert seen["json_body"]["toTokenAddress"] == bridge.PUSD_POLYGON
    assert seen["json_body"]["fromTokenAddress"] == bridge.NATIVE_USDC_POLYGON


def test_status_parser_only_completed_polygon_pusd_is_creditable():
    txs = bridge.parse_status({
        "transactions": [
            {
                "fromChainId": "137",
                "fromTokenAddress": bridge.NATIVE_USDC_POLYGON,
                "fromAmountBaseUnit": "10000000",
                "toChainId": "137",
                "toTokenAddress": bridge.PUSD_POLYGON,
                "status": "PROCESSING",
            },
            {
                "fromChainId": "137",
                "fromTokenAddress": bridge.BRIDGE_USDT_POLYGON,
                "fromAmountBaseUnit": "10000000",
                "toChainId": "137",
                "toTokenAddress": bridge.PUSD_POLYGON,
                "status": "COMPLETED",
                "txHash": "0xabc",
            },
            {
                "fromChainId": "137",
                "fromTokenAddress": bridge.BRIDGE_USDT_POLYGON,
                "fromAmountBaseUnit": "10000000",
                "toChainId": "137",
                "toTokenAddress": bridge.USDCE_POLYGON,
                "status": "COMPLETED",
                "txHash": "0xwrongtarget",
            },
        ]
    })
    completed = bridge.completed_pusd_settlements(txs)
    assert len(completed) == 1
    assert completed[0].tx_hash == "0xabc"
    assert bridge.base_units_to_decimal(completed[0].from_amount_base_unit or "0", 6) == Decimal("10")
