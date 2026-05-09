"""Tests for ClobAdapter — auth + transport layer only.

Network is stubbed via ``httpx.MockTransport``; on-chain order signing
(py-clob-client OrderBuilder) is monkeypatched to a deterministic stub
so we don't need a live CTF Exchange to exercise the POST /order path.
"""
from __future__ import annotations

import base64
import json

import httpx
import pytest

from projects.polymarket.crusaderbot.integrations.clob.adapter import (
    ClobAdapter,
)
from projects.polymarket.crusaderbot.integrations.clob.exceptions import (
    ClobAPIError,
    ClobAuthError,
)


pytestmark = pytest.mark.asyncio

DETERMINISTIC_PK = "0x" + ("aa" * 32)
DETERMINISTIC_ADDR = "0x8fd379246834eac74B8419FfdA202CF8051F7A03"
DETERMINISTIC_SECRET = base64.urlsafe_b64encode(
    b"test-secret-32-bytes-for-hmac-aa"
).decode()


def _stub_signed_order(self, *, token_id, side, price, size, **_kwargs):  # noqa: D401
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
    """Build a ClobAdapter with an injected MockTransport handler.

    ``monkeypatch`` patches ``_build_signed_order`` so post_order works
    without py-clob-client's on-chain signer. Returns a factory so each
    test can wire its own response handler.
    """
    monkeypatch.setattr(ClobAdapter, "_build_signed_order", _stub_signed_order)

    def _build(handler):
        transport = httpx.MockTransport(handler)
        return ClobAdapter(
            api_key="api-k",
            api_secret=DETERMINISTIC_SECRET,
            passphrase="pp",
            private_key=DETERMINISTIC_PK,
            transport=transport,
        )

    return _build


# --- post_order path ------------------------------------------------


async def test_post_order_attaches_l2_headers_and_returns_payload(
    adapter_factory,
):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["body"] = request.content.decode()
        return httpx.Response(
            200,
            json={"orderID": "abc-123", "status": "matched"},
        )

    async with adapter_factory(handler) as a:
        resp = await a.post_order(
            token_id="T", side="BUY", price=0.5, size=10,
        )

    assert resp == {"orderID": "abc-123", "status": "matched"}
    h = captured["headers"]
    for required in (
        "poly_address",
        "poly_signature",
        "poly_timestamp",
        "poly_api_key",
        "poly_passphrase",
    ):
        assert required in h, f"missing {required}"
    assert h["poly_address"].lower() == DETERMINISTIC_ADDR.lower()
    assert h["poly_api_key"] == "api-k"
    assert h["poly_passphrase"] == "pp"
    # Body is the JSON we POST'd; compact (no whitespace) so the HMAC
    # the server recomputes matches what we signed.
    body = json.loads(captured["body"])
    assert body["owner"] == "api-k"
    assert body["orderType"] == "GTC"
    assert body["order"]["tokenId"] == "T"


async def test_post_order_omits_builder_headers_when_unconfigured(
    adapter_factory,
):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json={"orderID": "x"})

    async with adapter_factory(handler) as a:
        await a.post_order(token_id="T", side="BUY", price=0.5, size=10)

    for k in captured["headers"]:
        assert not k.startswith("poly_builder_"), k


async def test_post_order_attaches_builder_headers_when_configured(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(ClobAdapter, "_build_signed_order", _stub_signed_order)
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json={"orderID": "x"})

    async with ClobAdapter(
        api_key="api-k",
        api_secret=DETERMINISTIC_SECRET,
        passphrase="pp",
        private_key=DETERMINISTIC_PK,
        builder_api_key="bk",
        builder_api_secret=DETERMINISTIC_SECRET,
        builder_passphrase="bpp",
        transport=httpx.MockTransport(handler),
    ) as a:
        assert a.has_builder_credentials is True
        await a.post_order(token_id="T", side="BUY", price=0.5, size=10)

    h = captured["headers"]
    for required in (
        "poly_builder_api_key",
        "poly_builder_timestamp",
        "poly_builder_passphrase",
        "poly_builder_signature",
    ):
        assert required in h, f"missing {required}"
    assert h["poly_builder_api_key"] == "bk"
    assert h["poly_builder_passphrase"] == "bpp"


# --- error classification ------------------------------------------


async def test_post_order_4xx_raises_api_error_no_retry(adapter_factory):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, json={"error": "bad price"})

    with pytest.raises(ClobAPIError) as exc:
        async with adapter_factory(handler) as a:
            await a.post_order(
                token_id="T", side="BUY", price=0.5, size=10,
            )
    assert exc.value.status_code == 400
    # 4xx must NOT be retried — duplicate POST after broker-class reject
    # is a capital-safety footgun.
    assert calls["n"] == 1


async def test_post_order_401_raises_auth_error(adapter_factory):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="invalid signature")

    with pytest.raises(ClobAuthError):
        async with adapter_factory(handler) as a:
            await a.post_order(
                token_id="T", side="BUY", price=0.5, size=10,
            )


async def test_post_order_5xx_retries_then_raises(adapter_factory):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, text="upstream")

    with pytest.raises(httpx.HTTPStatusError):
        async with adapter_factory(handler) as a:
            await a.post_order(
                token_id="T", side="BUY", price=0.5, size=10,
            )
    # tenacity stop_after_attempt(3) -> 3 transport calls
    assert calls["n"] == 3


# --- L1 / cancel paths ---------------------------------------------


async def test_derive_api_credentials_uses_l1_headers(adapter_factory):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={"apiKey": "k", "secret": "s", "passphrase": "p"},
        )

    async with adapter_factory(handler) as a:
        creds = await a.derive_api_credentials(nonce=0)

    assert creds == {"apiKey": "k", "secret": "s", "passphrase": "p"}
    assert "/auth/derive-api-key" in captured["url"]
    h = captured["headers"]
    for required in (
        "poly_address",
        "poly_signature",
        "poly_timestamp",
        "poly_nonce",
    ):
        assert required in h, f"missing {required}"
    # L1 path must NOT carry L2 headers (apiKey isn't known yet)
    assert "poly_api_key" not in h
    assert "poly_passphrase" not in h


async def test_cancel_order_sends_delete_with_body(adapter_factory):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["body"] = request.content.decode()
        return httpx.Response(200, json={"canceled": ["abc"]})

    async with adapter_factory(handler) as a:
        out = await a.cancel_order("abc")
    assert out == {"canceled": ["abc"]}
    assert captured["method"] == "DELETE"
    assert json.loads(captured["body"]) == {"orderID": "abc"}
