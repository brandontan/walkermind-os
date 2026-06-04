"""Unit tests — Chainlink BTC/USD oracle client + price_to_beat capture.

WARP-62, Chunk 1/4 (foundation). Network is fully stubbed: a fake transport
returns canned Data Streams reports, and ``fullReport`` payloads are built by
ABI-encoding a known benchmark price so decoding is verified by round-trip.
No live HTTP, no strategy wiring.
"""
from __future__ import annotations

import hashlib
import hmac
from typing import Any

import pytest
from eth_abi import encode as abi_encode

from projects.polymarket.crusaderbot import config as crusaderbot_config
from projects.polymarket.crusaderbot.domain.strategy.oracle import (
    ChainlinkDataStreamsClient,
    OracleConfigError,
    OracleDisabledError,
    OracleUnavailableError,
    build_hmac_signature,
    client_from_settings,
    decode_benchmark_price,
    get_price_to_beat,
)
from projects.polymarket.crusaderbot.domain.strategy.oracle import chainlink as cl

_FEED_ID = "0x00037da06d56d083fe599397a4769a042d63aa73dc4ef57709d31e9971a5b439"
_PRICE_SCALE = 10**18


# ---------------------------------------------------------------------
# Helpers — build a valid ABI-encoded fullReport for a given price.
# ---------------------------------------------------------------------


def _encode_full_report(price_usd: float) -> str:
    raw_price = int(round(price_usd * _PRICE_SCALE))
    blob = abi_encode(
        ["bytes32", "uint32", "uint32", "uint192", "uint192", "uint32",
         "int192", "int192", "int192"],
        [bytes.fromhex(_FEED_ID[2:]), 100, 110, 0, 0, 200,
         raw_price, raw_price - 5, raw_price + 5],
    )
    envelope = abi_encode(
        ["bytes32[3]", "bytes", "bytes32[]", "bytes32[]", "bytes32"],
        [[b"\x00" * 32] * 3, blob, [], [], b"\x00" * 32],
    )
    return "0x" + envelope.hex()


def _report(price_usd: float) -> dict[str, Any]:
    return {
        "report": {
            "feedID": _FEED_ID,
            "validFromTimestamp": 100,
            "observationsTimestamp": 110,
            "fullReport": _encode_full_report(price_usd),
        }
    }


def _stub_transport(payload: Any):
    captured: dict[str, Any] = {}

    async def _transport(url: str, headers: dict[str, str], timeout: float) -> Any:
        captured["url"] = url
        captured["headers"] = headers
        captured["timeout"] = timeout
        if isinstance(payload, Exception):
            raise payload
        return payload

    return _transport, captured


def _client(payload: Any, **over: Any) -> tuple[ChainlinkDataStreamsClient, dict]:
    transport, captured = _stub_transport(payload)
    kwargs: dict[str, Any] = dict(
        api_url="https://api.example.test",
        api_key="ck",
        api_secret="cs",
        feed_id=_FEED_ID,
        timeout=4.0,
        transport=transport,
    )
    kwargs.update(over)
    return ChainlinkDataStreamsClient(**kwargs), captured


# ---------------------------------------------------------------------
# HMAC signing
# ---------------------------------------------------------------------


def test_hmac_signature_matches_reference():
    sig = build_hmac_signature(
        method="get",
        path="/api/v1/reports/latest?feedID=" + _FEED_ID,
        body=b"",
        api_key="ck",
        api_secret="cs",
        timestamp_ms=1_700_000_000_000,
    )
    body_hash = hashlib.sha256(b"").hexdigest()
    msg = f"GET /api/v1/reports/latest?feedID={_FEED_ID} {body_hash} ck 1700000000000"
    expected = hmac.new(b"cs", msg.encode(), hashlib.sha256).hexdigest()
    assert sig == expected


def test_signed_request_headers_present(monkeypatch):
    monkeypatch.setattr(cl, "_now_ms", lambda: 1_700_000_000_000)
    client, _ = _client(_report(104_250.0))
    url, headers = client._signed_request()
    assert url.endswith(f"/api/v1/reports/latest?feedID={_FEED_ID}")
    assert headers["Authorization"] == "ck"
    assert headers["X-Authorization-Timestamp"] == "1700000000000"
    assert headers["X-Authorization-Signature-SHA256"]


# ---------------------------------------------------------------------
# Report decoding
# ---------------------------------------------------------------------


def test_decode_benchmark_price_round_trip():
    price = decode_benchmark_price(_encode_full_report(104_250.5))
    assert price == pytest.approx(104_250.5, rel=1e-9)


def test_decode_rejects_bad_hex():
    with pytest.raises(OracleUnavailableError):
        decode_benchmark_price("0xZZZZ")


def test_decode_rejects_garbage_blob():
    with pytest.raises(OracleUnavailableError):
        decode_benchmark_price("0x" + "00" * 8)


# ---------------------------------------------------------------------
# Client fetch + price read (stubbed transport — no network)
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_btc_price_returns_live_value():
    client, captured = _client(_report(98_765.25))
    price = await client.get_btc_price()
    assert price == pytest.approx(98_765.25, rel=1e-9)
    assert captured["timeout"] == 4.0


@pytest.mark.asyncio
async def test_fetch_raises_when_full_report_missing():
    client, _ = _client({"report": {"feedID": _FEED_ID}})
    with pytest.raises(OracleUnavailableError):
        await client.fetch_latest_report()


@pytest.mark.asyncio
async def test_fetch_raises_on_transport_error():
    client, _ = _client(RuntimeError("boom"))
    with pytest.raises(OracleUnavailableError):
        await client.get_btc_price()


@pytest.mark.asyncio
async def test_non_positive_price_raises():
    client, _ = _client(_report(0.0))
    with pytest.raises(OracleUnavailableError):
        await client.get_btc_price()


def test_missing_credentials_raises():
    with pytest.raises(OracleConfigError):
        ChainlinkDataStreamsClient(
            api_url="x", api_key="", api_secret="", feed_id=_FEED_ID
        )
    with pytest.raises(OracleConfigError):
        ChainlinkDataStreamsClient(
            api_url="x", api_key="k", api_secret="s", feed_id=""
        )


# ---------------------------------------------------------------------
# Feature-flag gating (default OFF)
# ---------------------------------------------------------------------


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("OPERATOR_CHAT_ID", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("WALLET_HD_SEED", "seed")
    monkeypatch.setenv("WALLET_ENCRYPTION_KEY", "k")
    monkeypatch.setenv("POLYGON_RPC_URL", "https://rpc")
    monkeypatch.setenv("ALCHEMY_POLYGON_WS_URL", "wss://ws")


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    crusaderbot_config.get_settings.cache_clear()
    yield
    crusaderbot_config.get_settings.cache_clear()


def test_client_from_settings_blocked_when_flag_off(monkeypatch):
    _set_required_env(monkeypatch)
    # ORACLE_ENABLED defaults to False -> runtime entrypoint refuses.
    with pytest.raises(OracleDisabledError):
        client_from_settings()


def test_client_from_settings_needs_credentials_when_enabled(monkeypatch):
    _set_required_env(monkeypatch)
    monkeypatch.setenv("ORACLE_ENABLED", "true")
    with pytest.raises(OracleConfigError):
        client_from_settings()


def test_client_from_settings_builds_when_enabled_with_creds(monkeypatch):
    _set_required_env(monkeypatch)
    monkeypatch.setenv("ORACLE_ENABLED", "true")
    monkeypatch.setenv("CHAINLINK_DATASTREAMS_API_KEY", "ck")
    monkeypatch.setenv("CHAINLINK_DATASTREAMS_API_SECRET", "cs")
    client = client_from_settings()
    assert isinstance(client, ChainlinkDataStreamsClient)
    assert client._feed_id == _FEED_ID


# ---------------------------------------------------------------------
# price_to_beat capture
# ---------------------------------------------------------------------


def test_price_to_beat_explicit_field():
    assert get_price_to_beat({"priceToBeat": "104250.5"}) == pytest.approx(104_250.5)
    assert get_price_to_beat({"strikePrice": 99000}) == pytest.approx(99_000.0)


def test_price_to_beat_from_question_text():
    market = {"question": "Will Bitcoin close above $104,250.50 this candle?"}
    assert get_price_to_beat(market) == pytest.approx(104_250.5)


def test_price_to_beat_none_when_absent():
    assert get_price_to_beat({"slug": "btc-updown-5m-1771511700"}) is None
    assert get_price_to_beat({}) is None
    assert get_price_to_beat(None) is None  # type: ignore[arg-type]


def test_price_to_beat_rejects_out_of_band():
    # A percentage / small number is not a plausible BTC/USD level.
    assert get_price_to_beat({"priceToBeat": 2.5}) is None
    # Explicit field absent, text has only a tiny figure -> None.
    assert get_price_to_beat({"question": "Up 5% in $3?"}) is None


def test_price_to_beat_explicit_field_wins_over_text():
    market = {"openPrice": 100_000, "question": "noise $999999999999 noise"}
    assert get_price_to_beat(market) == pytest.approx(100_000.0)
