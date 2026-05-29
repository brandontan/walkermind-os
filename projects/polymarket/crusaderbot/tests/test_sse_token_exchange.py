"""WARP•R00T audit Lane 3b — SSE token exchange (B2).

The main 24h JWT used to ride in the EventSource URL (?token=), leaking into
proxy/access logs. Now the stream authenticates via a short-lived, SSE-scoped
handshake token that (a) expires in 60s and (b) is rejected by the API auth path.

Hermetic: JWT secret injected via monkeypatch; no DB/network.
"""
from __future__ import annotations

import asyncio
import inspect
import time
import types

import jwt
import pytest

from projects.polymarket.crusaderbot.webtrader.backend import auth

_SECRET = "test-jwt-secret-for-sse-exchange"


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setattr(
        auth, "get_settings",
        lambda: types.SimpleNamespace(WEBTRADER_JWT_SECRET=_SECRET),
    )


def test_mint_stream_token_is_sse_scoped_and_short():
    tok = auth.mint_stream_token("u1", 123)
    decoded = jwt.decode(tok, _SECRET, algorithms=["HS256"])
    assert decoded["scope"] == "sse"
    assert decoded["user_id"] == "u1"
    assert decoded["telegram_id"] == 123
    ttl = decoded["exp"] - decoded["iat"]
    assert ttl == auth._STREAM_TOKEN_TTL and ttl <= 120


def test_decode_stream_token_accepts_sse():
    p = auth.decode_stream_token(auth.mint_stream_token("u1"))
    assert p["user_id"] == "u1"


def test_decode_stream_token_rejects_non_sse():
    now = int(time.time())
    api_tok = jwt.encode({"user_id": "u1", "exp": now + 3600}, _SECRET, algorithm="HS256")
    with pytest.raises(Exception) as e:
        auth.decode_stream_token(api_tok)
    assert "401" in str(e.value) or "stream token" in str(e.value)


def test_decode_stream_token_rejects_missing():
    with pytest.raises(Exception):
        auth.decode_stream_token(None)


def test_get_current_user_rejects_sse_token():
    """A leaked SSE token must NOT authenticate an API request."""
    sse = auth.mint_stream_token("u1")
    with pytest.raises(Exception) as e:
        asyncio.run(auth.get_current_user(creds=None, token=sse))
    assert "401" in str(e.value) or "invalid token" in str(e.value)


def test_get_current_user_accepts_normal_token():
    now = int(time.time())
    api_tok = jwt.encode(
        {"user_id": "u1", "first_name": "W", "exp": now + 3600}, _SECRET, algorithm="HS256"
    )
    out = asyncio.run(auth.get_current_user(creds=None, token=api_tok))
    assert out["user_id"] == "u1"


def test_sse_stream_authenticates_via_stream_token_only():
    from projects.polymarket.crusaderbot.webtrader.backend import router as r
    src = inspect.getsource(r.sse_stream)
    assert "decode_stream_token" in src, "sse_stream must validate the scoped token"
    assert "_CurrentUser" not in src, "sse_stream must not auth via the main JWT"
