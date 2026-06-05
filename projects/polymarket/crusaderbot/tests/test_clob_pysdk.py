"""Unit tests for the CLOB v2 backend (PolymarketSdkClient).

py-sdk is mocked: a fake AsyncSecureClient is injected as the cached
``_client`` so no network or real ``AsyncSecureClient.create()`` runs.
These tests lock the response/error mapping contract the rest of the
system depends on. The live behaviour is proven separately by the
WARP-74 staging proof (real broker, isolated wallet) under SENTINEL.
"""
from __future__ import annotations

import pytest

from projects.polymarket.crusaderbot.integrations.clob.exceptions import (
    ClobAPIError,
    ClobAuthError,
    ClobConfigError,
    ClobRateLimitError,
)
from projects.polymarket.crusaderbot.integrations.clob.sdk_client import (
    PolymarketSdkClient,
)

_KEY = "0x" + ("11" * 32)


class _Model:
    """Stand-in for a pydantic response model (has model_dump)."""

    def __init__(self, **data):
        self._data = data

    def model_dump(self):
        return dict(self._data)


class _FakeSecureClient:
    def __init__(self):
        self.posted = []
        self.cancelled = []
        self._open = []
        self._trades = []
        self._post_response = _Model(ok=True, order_id="OID-1", status="live")

    async def create_limit_order(self, *, token_id, side, price, size):
        return {"token_id": token_id, "side": side, "price": price, "size": size}

    async def post_order(self, signed):
        self.posted.append(signed)
        return self._post_response

    async def cancel_order(self, *, order_id):
        self.cancelled.append(order_id)
        return _Model(canceled=[order_id], not_canceled={})

    async def cancel_orders(self, *, order_ids):
        self.cancelled.extend(order_ids)
        return _Model(canceled=list(order_ids), not_canceled={})

    async def cancel_all(self):
        return _Model(canceled=["a", "b"], not_canceled={})

    def list_open_orders(self, **kwargs):
        return _AsyncIter(self._open)

    def list_account_trades(self, **kwargs):
        return _AsyncIter(self._trades)

    async def get_order(self, *, order_id):
        return _Model(id=order_id, token_id="T", price=0.4, status="live")


class _AsyncIter:
    def __init__(self, items):
        self._items = list(items)

    def __aiter__(self):
        async def gen():
            for it in self._items:
                yield it
        return gen()


def _client():
    c = PolymarketSdkClient(private_key=_KEY, funder_address=None)
    c._client = _FakeSecureClient()  # bypass network _ensure()
    return c


@pytest.mark.asyncio
async def test_post_order_maps_accepted_to_dict():
    c = _client()
    out = await c.post_order(token_id="T", side="buy", price=0.4, size=10)
    assert out["success"] is True
    assert out["orderID"] == "OID-1"
    assert out["order_id"] == "OID-1"
    assert out["id"] == "OID-1"
    assert out["status"] == "live"


@pytest.mark.asyncio
async def test_post_order_raises_on_rejected():
    c = _client()
    c._client._post_response = _Model(ok=False, code="INVALID", message="bad price")
    with pytest.raises(ClobAPIError):
        await c.post_order(token_id="T", side="BUY", price=0.4, size=10)


@pytest.mark.asyncio
async def test_post_order_rejects_non_gtc():
    c = _client()
    with pytest.raises(ClobConfigError):
        await c.post_order(
            token_id="T", side="BUY", price=0.4, size=10, order_type="FOK",
        )


@pytest.mark.asyncio
async def test_get_open_orders_aliases_id_and_asset():
    c = _client()
    c._client._open = [_Model(id="O1", token_id="TK", price=0.5, status="live")]
    rows = await c.get_open_orders()
    assert rows[0]["orderID"] == "O1"
    assert rows[0]["order_id"] == "O1"
    assert rows[0]["asset_id"] == "TK"


class _Page:
    """A pysdk-style pagination wrapper: rows live in .items, plus pagination
    metadata. _collect must flatten this into its rows, not map the wrapper
    (the run-#12 defect: list_open_orders yields Page, not orders)."""

    def __init__(self, items):
        self.items = list(items)
        self.has_more = False
        self.next_cursor = None
        self.total_count = len(items)


@pytest.mark.asyncio
async def test_get_open_orders_flattens_page_wrapper():
    c = _client()
    # paginator async-iterates ONE Page that holds the actual order rows
    c._client._open = [_Page([_Model(id="O1", token_id="TK", price=0.5, status="live")])]
    rows = await c.get_open_orders()
    assert len(rows) == 1
    assert rows[0]["orderID"] == "O1"
    assert rows[0]["order_id"] == "O1"
    assert rows[0]["asset_id"] == "TK"


class _EmptyPage:
    """A Page wrapper with markers but items=None (empty/malformed page).
    Must NOT be appended as a bogus row — yields zero rows."""

    def __init__(self):
        self.items = None
        self.has_more = False
        self.next_cursor = None
        self.total_count = 0


@pytest.mark.asyncio
async def test_get_open_orders_malformed_page_yields_no_rows():
    c = _client()
    c._client._open = [_EmptyPage()]
    rows = await c.get_open_orders()
    assert rows == []   # the wrapper itself is never collected as a row


@pytest.mark.asyncio
async def test_get_fills_flattens_page_wrapper():
    c = _client()
    c._client._trades = [_Page([
        _Model(id="t1", taker_order_id="OID-1", price=0.4, size=5),
        _Model(id="t2", taker_order_id="OTHER", price=0.4, size=5),
    ])]
    fills = await c.get_fills("OID-1")
    assert len(fills) == 1
    assert fills[0]["id"] == "t1"


class _SlotsOrder:
    """An open-order object with __slots__ and NO model_dump/dict/usable
    __dict__ — the run-#11 staging shape that collapsed to {} and lost the id.
    Regression guard: _order_to_dict must still surface id/asset via slots."""

    __slots__ = ("id", "asset_id", "price", "size", "status")

    def __init__(self):
        self.id = "OSLOT"
        self.asset_id = "TKSLOT"
        self.price = 0.4
        self.size = 10
        self.status = "live"


@pytest.mark.asyncio
async def test_get_open_orders_maps_slots_shape():
    c = _client()
    c._client._open = [_SlotsOrder()]
    rows = await c.get_open_orders()
    assert rows[0]["id"] == "OSLOT"
    assert rows[0]["orderID"] == "OSLOT"
    assert rows[0]["order_id"] == "OSLOT"
    assert rows[0]["asset_id"] == "TKSLOT"


class _PropOrder:
    """An open-order exposing id/asset only via @property (empty __dict__).
    Direct getattr fallback in _order_to_dict must still find them."""

    @property
    def order_id(self):
        return "OPROP"

    @property
    def token_id(self):
        return "TKPROP"


@pytest.mark.asyncio
async def test_get_open_orders_maps_property_shape():
    c = _client()
    c._client._open = [_PropOrder()]
    rows = await c.get_open_orders()
    assert rows[0]["orderID"] == "OPROP"
    assert rows[0]["order_id"] == "OPROP"
    assert rows[0]["asset_id"] == "TKPROP"


class _ScopedClient:
    """list_open_orders with an EXPLICIT maker_address param, so _owner_kwargs
    detects and scopes by it (proxy/funder owner-scoping; mirrors get_fills F1)."""

    def __init__(self):
        self.captured: dict = {}

    def list_open_orders(self, *, maker_address=None, market=None):
        self.captured = {"maker_address": maker_address, "market": market}
        return _AsyncIter([_Model(id="O1", token_id="TK", price=0.5, status="live")])


@pytest.mark.asyncio
async def test_get_open_orders_scopes_by_funder():
    c = PolymarketSdkClient(private_key=_KEY, funder_address="0x000000000000000000000000000000000000dEaD")
    c._client = _ScopedClient()
    rows = await c.get_open_orders("MKT")
    assert c._client.captured["maker_address"] == c.funder   # proxy funder, not EOA
    assert c._client.captured["market"] == "MKT"
    assert rows[0]["orderID"] == "O1"


@pytest.mark.asyncio
async def test_get_open_orders_falls_back_to_eoa_without_funder():
    c = PolymarketSdkClient(private_key=_KEY, funder_address=None)
    c._client = _ScopedClient()
    await c.get_open_orders()
    assert c._client.captured["maker_address"] == c.address   # EOA signer
    assert c._client.captured["market"] is None


@pytest.mark.asyncio
async def test_get_fills_filters_by_order_id():
    c = _client()
    c._client._trades = [
        _Model(id="t1", taker_order_id="OID-1", price=0.4, size=5),
        _Model(id="t2", taker_order_id="OTHER", price=0.4, size=5),
    ]
    fills = await c.get_fills("OID-1")
    assert len(fills) == 1
    assert fills[0]["id"] == "t1"


@pytest.mark.asyncio
async def test_get_order_maps_status():
    c = _client()
    out = await c.get_order("O9")
    assert out["status"] == "live"
    assert out["orderID"] == "O9"


@pytest.mark.asyncio
async def test_cancel_all_orders_global():
    c = _client()
    out = await c.cancel_all_orders()
    assert set(out["canceled"]) == {"a", "b"}


@pytest.mark.asyncio
async def test_cancel_all_orders_market_scoped_lists_then_cancels():
    c = _client()
    c._client._open = [
        _Model(id="O1", token_id="TK", price=0.5, status="live"),
        _Model(id="O2", token_id="TK", price=0.6, status="live"),
    ]
    out = await c.cancel_all_orders(market="MKT")
    assert set(out["canceled"]) == {"O1", "O2"}
    assert c._client.cancelled == ["O1", "O2"]


@pytest.mark.asyncio
async def test_cancel_all_orders_market_scoped_noop_when_empty():
    c = _client()
    c._client._open = []
    out = await c.cancel_all_orders(market="MKT")
    assert out == {"canceled": [], "not_canceled": {}}


@pytest.mark.asyncio
async def test_post_order_tick_size_neg_risk_are_advisory_not_raised():
    """Live callers always pass tick_size/neg_risk; py-sdk resolves them
    from market truth, so they must be accepted (not raised on)."""
    c = _client()
    out = await c.post_order(
        token_id="T", side="BUY", price=0.4, size=10,
        tick_size="0.01", neg_risk=True,
    )
    assert out["orderID"] == "OID-1"


def test_map_error_rate_limit():
    from polymarket import RateLimitError

    c = _client()
    mapped = c._map_error(RateLimitError("slow down"), "/order")
    assert isinstance(mapped, ClobRateLimitError)


def test_map_error_request_rejected_auth():
    from polymarket import RequestRejectedError

    c = _client()
    mapped = c._map_error(RequestRejectedError("forbidden", status=403), "/order")
    assert isinstance(mapped, ClobAuthError)
    assert mapped.status_code == 403


def test_map_error_request_rejected_400_is_api_not_auth():
    """A 400 request-rejection (e.g. "the orderbook does not exist", bad
    price/tick, closed market) is a validation error, NOT an auth failure.
    Regression guard for the staging-proof mis-bucketing fix."""
    from polymarket import RequestRejectedError

    c = _client()
    mapped = c._map_error(
        RequestRejectedError("the orderbook does not exist", status=400), "/order"
    )
    assert isinstance(mapped, ClobAPIError)
    assert not isinstance(mapped, ClobAuthError)
    assert mapped.status_code == 400
