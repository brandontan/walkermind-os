"""WS subscribe must use auto-derived creds, not empty settings.

Regression: when POLYMARKET_API_KEY/SECRET/PASSPHRASE are unset (creds
auto-derived from the private key), the WS subscribe frame was sent with
empty auth → broker rejected it → endless reconnect loop. The WS must resolve
creds the same way the REST client does (env, else `_derived`).
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

from projects.polymarket.crusaderbot.integrations import clob as clob_pkg
from projects.polymarket.crusaderbot.integrations.clob.ws import ClobWebSocketClient


class _EnvSettings:
    POLYMARKET_API_KEY = "envk"
    POLYMARKET_API_SECRET = "envs"
    POLYMARKET_API_PASSPHRASE = "envp"
    POLYMARKET_PASSPHRASE = ""


class _DerivedOnlySettings:
    # All API creds unset in env → must fall back to the derived cache.
    POLYMARKET_API_KEY = ""
    POLYMARKET_API_SECRET = ""
    POLYMARKET_API_PASSPHRASE = ""
    POLYMARKET_PASSPHRASE = ""
    CLOB_WS_URL = "wss://test/ws/user"
    USE_REAL_CLOB = True


_DERIVED = {"api_key": "dk", "api_secret": "ds", "passphrase": "dp"}


def test_effective_credentials_prefers_env():
    with patch.object(clob_pkg, "_derived", dict(_DERIVED)):
        assert clob_pkg.effective_credentials(_EnvSettings()) == ("envk", "envs", "envp")


def test_effective_credentials_falls_back_to_derived():
    with patch.object(clob_pkg, "_derived", dict(_DERIVED)):
        assert clob_pkg.effective_credentials(_DerivedOnlySettings()) == ("dk", "ds", "dp")


def test_effective_credentials_empty_when_nothing_set():
    with patch.object(clob_pkg, "_derived", None):
        assert clob_pkg.effective_credentials(_DerivedOnlySettings()) == ("", "", "")


class _FakeWS:
    def __init__(self):
        self.sent: list[str] = []

    async def send(self, frame):
        self.sent.append(frame)


def test_ws_subscribe_uses_derived_creds_when_env_empty():
    client = ClobWebSocketClient(settings=_DerivedOnlySettings())
    ws = _FakeWS()
    with patch.object(clob_pkg, "_derived", dict(_DERIVED)):
        asyncio.run(client._send_subscribe(ws, _DerivedOnlySettings()))
    frame = json.loads(ws.sent[0])
    assert frame["auth"]["apiKey"] == "dk"        # NOT "" — the bug
    assert frame["auth"]["secret"] == "ds"
    assert frame["auth"]["passphrase"] == "dp"
    assert frame["type"] == "user"
