"""ClobV2Client -- the py-clob-client-v2 CLOB backend (WARP/clob-v2-cutover).

Drives the ClobClientProtocol surface against a fake synchronous v2 client
injected through the ``_build_client`` seam, so the dict-shape contract +
error taxonomy mapping are verified without the real SDK construction or any
network. Also pins the factory wiring (USE_CLOB_V2 takes precedence).
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from projects.polymarket.crusaderbot.integrations.clob.v2_client import ClobV2Client
from projects.polymarket.crusaderbot.integrations.clob.exceptions import (
    ClobAPIError,
    ClobRateLimitError,
)

# A valid throwaway private key (Hardhat account #0 — never funded).
_PK = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"


class _FakeV2:
    """Synchronous stand-in for py_clob_client_v2.ClobClient."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.raise_on_get_order: Exception | None = None

    def create_and_post_order(self, args, opts, order_type):
        self.calls.append(("post", args.token_id, args.side, order_type))
        return {"success": True, "orderID": "0xORDER", "status": "live",
                "making_amount": "0"}

    def get_order(self, order_id):
        if self.raise_on_get_order is not None:
            raise self.raise_on_get_order
        return {"order_id": order_id, "token_id": "0xTOK", "status": "LIVE"}

    def get_open_orders(self, params=None):
        return [{"order_id": "0xORDER", "asset_id": "0xTOK", "status": "LIVE"}]

    def get_trades(self, params=None):
        return [
            {"taker_order_id": "0xORDER", "price": "0.5", "size": "10"},
            {"taker_order_id": "0xOTHER", "price": "0.4", "size": "5"},
        ]

    def cancel_order(self, payload):
        self.calls.append(("cancel", payload.orderID))
        return {"canceled": [payload.orderID]}

    def cancel_market_orders(self, payload):
        self.calls.append(("cancel_market", payload.market))
        return {"canceled": [], "market": payload.market}

    def cancel_all(self):
        self.calls.append(("cancel_all",))
        return {"canceled": []}


def _client(fake: _FakeV2) -> ClobV2Client:
    c = ClobV2Client(private_key=_PK, funder_address="0xFUNDER", signature_type=2)
    # Inject the fake through the construction seam (no real SDK / network).
    c._build_client = lambda: fake  # type: ignore[assignment]
    return c


def _run(coro):
    return asyncio.run(coro)


def test_post_order_normalizes_accepted():
    fake = _FakeV2()
    c = _client(fake)
    out = _run(c.post_order(token_id="0xTOK", side="BUY", price=0.5, size=10,
                            tick_size="0.01", neg_risk=False))
    assert out["success"] is True
    assert out["orderID"] == "0xORDER" == out["order_id"] == out["id"]
    assert out["status"] == "live"
    assert fake.calls[0][0] == "post"


def test_post_order_rejects_unsupported_type():
    c = _client(_FakeV2())
    with pytest.raises(Exception) as ei:
        _run(c.post_order(token_id="0xTOK", side="BUY", price=0.5, size=10,
                          order_type="GTD"))
    assert "unsupported" in str(ei.value).lower()


def test_post_order_raises_on_rejection():
    fake = _FakeV2()
    fake.create_and_post_order = lambda *a, **k: {  # type: ignore[assignment]
        "success": False, "errorMsg": "bad price"}
    c = _client(fake)
    with pytest.raises(ClobAPIError):
        _run(c.post_order(token_id="0xTOK", side="BUY", price=2.0, size=10))


def test_get_order_aliases_id_and_asset():
    c = _client(_FakeV2())
    out = _run(c.get_order("0xORDER"))
    assert out["id"] == out["order_id"] == out["orderID"] == "0xORDER"
    assert out["asset_id"] == "0xTOK"


def test_get_open_orders_maps_each_row():
    c = _client(_FakeV2())
    rows = _run(c.get_open_orders())
    assert len(rows) == 1
    assert rows[0]["id"] == "0xORDER" and rows[0]["asset_id"] == "0xTOK"


def test_get_fills_filters_to_order():
    c = _client(_FakeV2())
    fills = _run(c.get_fills("0xORDER"))
    assert len(fills) == 1
    assert fills[0]["taker_order_id"] == "0xORDER"


def test_cancel_all_routes_market_vs_global():
    fake = _FakeV2()
    c = _client(fake)
    _run(c.cancel_all_orders(market="0xMKT"))
    _run(c.cancel_all_orders())
    kinds = [x[0] for x in fake.calls]
    assert "cancel_market" in kinds and "cancel_all" in kinds


def test_error_mapping_rate_limit_and_api():
    fake = _FakeV2()

    class _Err429(Exception):
        status_code = 429

    class _Err400(Exception):
        status_code = 400

    c = _client(fake)
    fake.raise_on_get_order = _Err429("slow down")
    with pytest.raises(ClobRateLimitError):
        _run(c.get_order("0xORDER"))
    fake.raise_on_get_order = _Err400("bad request")
    with pytest.raises(ClobAPIError):
        _run(c.get_order("0xORDER"))


def test_factory_selects_v2_when_enabled():
    from projects.polymarket.crusaderbot.integrations import clob

    class _S:
        USE_REAL_CLOB = True
        USE_CLOB_V2 = True
        USE_PYSDK_CLOB = False
        POLYMARKET_PRIVATE_KEY = _PK
        POLYMARKET_FUNDER_ADDRESS = "0xFUNDER"
        POLYMARKET_SIGNATURE_TYPE = 2
        POLYMARKET_API_KEY = ""
        POLYMARKET_API_SECRET = ""
        POLYMARKET_API_PASSPHRASE = ""
        POLYMARKET_PASSPHRASE = ""
        POLYMARKET_BUILDER_CODE = None
        POLYMARKET_BUILDER_ADDRESS = None
        CIRCUIT_BREAKER_THRESHOLD = 5
        CIRCUIT_BREAKER_RESET_SECONDS = 30
        CLOB_RATE_LIMIT_RPS = 0

    clob.reset_clob_resilience()
    with patch.object(clob, "effective_credentials", return_value=("", "", "")):
        client = clob.get_clob_client(_S())
    assert isinstance(client, ClobV2Client)
    clob.reset_clob_resilience()
