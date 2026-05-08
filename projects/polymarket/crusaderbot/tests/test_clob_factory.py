"""Tests for the CLOB factory and MockClobClient.

Covers the paper-safe default branch (no env, no secrets, no network),
the explicit-real branch (raises when creds are missing), and the mock
client's deterministic behaviour.
"""
from __future__ import annotations

import pytest

from projects.polymarket.crusaderbot.config import Settings
from projects.polymarket.crusaderbot.integrations.clob import (
    ClobAdapter,
    ClobConfigError,
    MockClobClient,
    get_clob_client,
)


# Per-test asyncio marks — half of this file's tests are sync (factory
# wiring) and half are async (mock-client behaviour). A module-level mark
# would warn on every sync test.


def _settings(**overrides):
    """Build a Settings instance with the project's required env stubbed.

    Tests should not need a real .env; we stub each REQUIRED_ENV_VARS
    field with a sentinel value so Settings(...) constructs cleanly.
    """
    base = {
        "TELEGRAM_BOT_TOKEN": "stub",
        "OPERATOR_CHAT_ID": 1,
        "DATABASE_URL": "postgresql://stub/stub",
        "POLYGON_RPC_URL": "https://stub",
        "ALCHEMY_POLYGON_WS_URL": "wss://stub",
        "WALLET_HD_SEED": "stub",
        "WALLET_ENCRYPTION_KEY": "stub",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


# --- Factory --------------------------------------------------------


def test_factory_returns_mock_when_use_real_clob_false():
    s = _settings(USE_REAL_CLOB=False)
    client = get_clob_client(s)
    assert isinstance(client, MockClobClient)


def test_factory_returns_mock_with_no_polymarket_creds():
    """Default branch must work in CI without any Polymarket secrets —
    that's the whole point of the paper-safe default.
    """
    s = _settings()  # no USE_REAL_CLOB override -> default False
    client = get_clob_client(s)
    assert isinstance(client, MockClobClient)


def test_factory_raises_when_use_real_clob_true_but_creds_missing():
    s = _settings(USE_REAL_CLOB=True)
    with pytest.raises(ClobConfigError) as exc:
        get_clob_client(s)
    msg = str(exc.value)
    assert "POLYMARKET_API_KEY" in msg
    assert "POLYMARKET_API_SECRET" in msg
    assert "POLYMARKET_API_PASSPHRASE" in msg
    assert "POLYMARKET_PRIVATE_KEY" in msg


def test_factory_returns_real_adapter_when_creds_complete():
    import base64

    secret = base64.urlsafe_b64encode(b"x" * 32).decode()
    s = _settings(
        USE_REAL_CLOB=True,
        POLYMARKET_API_KEY="k",
        POLYMARKET_API_SECRET=secret,
        POLYMARKET_API_PASSPHRASE="pp",
        POLYMARKET_PRIVATE_KEY="0x" + ("aa" * 32),
    )
    client = get_clob_client(s)
    assert isinstance(client, ClobAdapter)
    assert client.signature_type == 2  # default
    assert client.has_builder_credentials is False


def test_factory_accepts_legacy_passphrase_name():
    """The new env name is POLYMARKET_API_PASSPHRASE, but legacy
    deployments still set POLYMARKET_PASSPHRASE — the factory must
    accept either so a re-deploy doesn't require renaming the secret.
    """
    import base64

    secret = base64.urlsafe_b64encode(b"x" * 32).decode()
    s = _settings(
        USE_REAL_CLOB=True,
        POLYMARKET_API_KEY="k",
        POLYMARKET_API_SECRET=secret,
        POLYMARKET_PASSPHRASE="pp-legacy",  # legacy only
        POLYMARKET_PRIVATE_KEY="0x" + ("aa" * 32),
    )
    client = get_clob_client(s)
    assert isinstance(client, ClobAdapter)


def test_factory_picks_up_builder_creds_when_set():
    import base64

    secret = base64.urlsafe_b64encode(b"x" * 32).decode()
    s = _settings(
        USE_REAL_CLOB=True,
        POLYMARKET_API_KEY="k",
        POLYMARKET_API_SECRET=secret,
        POLYMARKET_API_PASSPHRASE="pp",
        POLYMARKET_PRIVATE_KEY="0x" + ("aa" * 32),
        POLYMARKET_BUILDER_API_KEY="bk",
        POLYMARKET_BUILDER_API_SECRET=secret,
        POLYMARKET_BUILDER_PASSPHRASE="bp",
    )
    client = get_clob_client(s)
    assert isinstance(client, ClobAdapter)
    assert client.has_builder_credentials is True


# --- Mock client ----------------------------------------------------


@pytest.mark.asyncio
async def test_mock_post_order_returns_well_formed_response():
    m = MockClobClient()
    out = await m.post_order(token_id="T", side="BUY", price=0.5, size=10)
    assert out["status"] == "matched"
    assert out["tokenID"] == "T"
    assert out["side"] == "BUY"
    assert out["_mock"] is True
    assert out["orderID"]


@pytest.mark.asyncio
async def test_mock_orders_are_deterministic_per_invocation():
    m1 = MockClobClient(deterministic=True)
    m2 = MockClobClient(deterministic=True)
    a = await m1.post_order(token_id="T", side="BUY", price=0.5, size=10)
    b = await m2.post_order(token_id="T", side="BUY", price=0.5, size=10)
    assert a["orderID"] == b["orderID"]


@pytest.mark.asyncio
async def test_mock_cancel_round_trip():
    m = MockClobClient()
    placed = await m.post_order(
        token_id="T", side="BUY", price=0.5, size=10,
    )
    cancelled = await m.cancel_order(placed["orderID"])
    assert placed["orderID"] in cancelled["canceled"]
    # second cancel reports not_found, never crashes
    again = await m.cancel_order(placed["orderID"])
    assert again["canceled"] == []


@pytest.mark.asyncio
async def test_mock_cancel_all_returns_active_ids():
    m = MockClobClient()
    a = await m.post_order(token_id="T", side="BUY", price=0.5, size=10)
    b = await m.post_order(token_id="T", side="SELL", price=0.6, size=5)
    out = await m.cancel_all()
    assert set(out["canceled"]) == {a["orderID"], b["orderID"]}
    assert m.open_orders() == []


@pytest.mark.asyncio
async def test_mock_aclose_is_idempotent():
    m = MockClobClient()
    await m.aclose()
    await m.aclose()  # must not raise


def test_mock_does_not_create_an_httpx_client():
    """Hard rule: MockClobClient MUST NOT instantiate any network client."""
    import httpx

    m = MockClobClient()
    for attr in vars(m).values():
        assert not isinstance(attr, httpx.AsyncClient)
        assert not isinstance(attr, httpx.Client)
