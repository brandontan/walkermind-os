"""Unit tests — multi-asset RTDS crypto oracle + price_to_beat capture.

WARP-62, Chunk 1/4 (foundation). Network is fully stubbed: a fake WebSocket
replays canned RTDS frames via the injected ``connect_factory``, so no socket is
ever opened. Covers all three symbols (BTC/ETH/SOL), the stale-feed path, frame
parsing/containment, lifecycle, and flag-gating.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from projects.polymarket.crusaderbot import config as crusaderbot_config
from projects.polymarket.crusaderbot.domain.strategy.oracle import (
    OracleConfigError,
    OracleDisabledError,
    PolymarketRTDSOracle,
    get_price_to_beat,
    normalize_symbol,
    oracle_from_settings,
    parse_symbols,
)

_SYMBOLS = ["btc/usd", "eth/usd", "sol/usd"]


def _frame(symbol: str, value: Any) -> str:
    return json.dumps(
        {"topic": "crypto_prices", "type": "update",
         "payload": {"symbol": symbol, "value": value, "timestamp": 1}}
    )


class _FakeWS:
    """Async-iterable fake socket: replays frames, then stays open until closed."""

    def __init__(self, frames: list[str]) -> None:
        self.frames = list(frames)
        self.sent: list[str] = []
        self._closed = asyncio.Event()

    async def send(self, data: str) -> None:
        self.sent.append(data)

    async def close(self) -> None:
        self._closed.set()

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        for f in self.frames:
            yield f
        await self._closed.wait()


def _oracle(ws: _FakeWS, **over: Any) -> PolymarketRTDSOracle:
    async def factory(url: str) -> _FakeWS:
        return ws

    kwargs: dict[str, Any] = dict(
        ws_url="wss://ws-live-data.polymarket.com",
        symbols=_SYMBOLS,
        staleness_sec=10.0,
        connect_factory=factory,
    )
    kwargs.update(over)
    return PolymarketRTDSOracle(**kwargs)


# ---------------------------------------------------------------------
# Symbol helpers
# ---------------------------------------------------------------------


def test_normalize_symbol_forms():
    assert normalize_symbol("BTC") == "btc/usd"
    assert normalize_symbol("eth/usd") == "eth/usd"
    assert normalize_symbol("SOL-USD") == "sol/usd"
    assert normalize_symbol(" Btc ") == "btc/usd"


def test_parse_symbols_csv_dedup_order():
    assert parse_symbols("btc/usd, eth/usd ,btc/usd, sol") == [
        "btc/usd", "eth/usd", "sol/usd",
    ]
    assert parse_symbols(["BTC", "ETH"]) == ["btc/usd", "eth/usd"]


# ---------------------------------------------------------------------
# Frame parsing (no network)
# ---------------------------------------------------------------------


def test_parse_tick_all_three_symbols():
    oracle = _oracle(_FakeWS([]))
    assert oracle._parse_tick({"payload": {"symbol": "btc/usd", "value": 104250.5}}) == ("btc/usd", 104250.5)
    assert oracle._parse_tick({"payload": {"asset": "ETH/USD", "price": 3850.0}}) == ("eth/usd", 3850.0)
    assert oracle._parse_tick({"symbol": "sol", "p": 168.25}) == ("sol/usd", 168.25)


def test_parse_tick_rejects_unconfigured_and_bad_price():
    oracle = _oracle(_FakeWS([]))
    assert oracle._parse_tick({"payload": {"symbol": "doge/usd", "value": 0.4}}) is None
    assert oracle._parse_tick({"payload": {"symbol": "btc/usd", "value": "x"}}) is None
    assert oracle._parse_tick({"payload": {"symbol": "btc/usd", "value": 0}}) is None
    assert oracle._parse_tick({"payload": {"symbol": "btc/usd", "value": float("nan")}}) is None
    assert oracle._parse_tick({"payload": {"symbol": "btc/usd"}}) is None
    assert oracle._parse_tick({"noise": 1}) is None


def test_handle_message_bad_frame_is_contained():
    oracle = _oracle(_FakeWS([]))
    oracle._handle_message("not json{{{")  # must not raise
    oracle._handle_message(b"\x00\x01")
    assert oracle.get_price("btc") is None


# ---------------------------------------------------------------------
# Staleness (injectable clock)
# ---------------------------------------------------------------------


def test_get_price_fresh_then_stale():
    now = [1000.0]
    oracle = _oracle(_FakeWS([]), clock=lambda: now[0], staleness_sec=5.0)
    oracle._handle_message(_frame("btc/usd", 104000.0))
    assert oracle.get_price("btc") == 104000.0
    assert oracle.is_stale("btc") is False
    now[0] = 1006.0  # 6s elapsed > 5s threshold
    assert oracle.get_price("btc") is None  # never returns the stale value
    assert oracle.is_stale("btc") is True


def test_unknown_symbol_is_stale_and_none():
    oracle = _oracle(_FakeWS([]))
    assert oracle.get_price("eth") is None
    assert oracle.is_stale("eth") is True


# ---------------------------------------------------------------------
# Lifecycle over the fake socket (all 3 symbols)
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_populates_all_symbols_and_subscribes():
    ws = _FakeWS([
        _frame("btc/usd", 104250.5),
        _frame("eth/usd", 3850.0),
        _frame("sol/usd", 168.25),
    ])
    oracle = _oracle(ws)
    await oracle.start()
    assert await oracle.wait_connected(timeout=2.0)
    for _ in range(20):  # let the read loop drain the canned frames
        await asyncio.sleep(0)
    assert oracle.get_price("btc") == pytest.approx(104250.5)
    assert oracle.get_price("eth") == pytest.approx(3850.0)
    assert oracle.get_price("sol") == pytest.approx(168.25)
    # Subscribe frame was sent for the configured symbols.
    assert ws.sent
    sub = json.loads(ws.sent[0])
    subbed = {s["symbol"] for s in sub["subscriptions"]}
    assert subbed == set(_SYMBOLS)
    await oracle.stop()


@pytest.mark.asyncio
async def test_stop_is_safe_without_start():
    oracle = _oracle(_FakeWS([]))
    await oracle.stop()  # must not raise


# ---------------------------------------------------------------------
# Construction guards
# ---------------------------------------------------------------------


def test_construction_requires_url_and_symbols():
    with pytest.raises(OracleConfigError):
        PolymarketRTDSOracle(ws_url="", symbols=_SYMBOLS)
    with pytest.raises(OracleConfigError):
        PolymarketRTDSOracle(ws_url="wss://x", symbols=[])


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


def test_oracle_from_settings_blocked_when_flag_off(monkeypatch):
    _set_required_env(monkeypatch)
    with pytest.raises(OracleDisabledError):
        oracle_from_settings()


def test_oracle_from_settings_builds_multi_asset_when_enabled(monkeypatch):
    _set_required_env(monkeypatch)
    monkeypatch.setenv("ORACLE_ENABLED", "true")
    oracle = oracle_from_settings()
    assert isinstance(oracle, PolymarketRTDSOracle)
    # Default symbol map is multi-asset (BTC/ETH/SOL) — not BTC-only.
    assert oracle.symbols == _SYMBOLS


def test_oracle_from_settings_honours_symbol_map(monkeypatch):
    _set_required_env(monkeypatch)
    monkeypatch.setenv("ORACLE_ENABLED", "true")
    monkeypatch.setenv("ORACLE_SYMBOLS", "btc/usd,eth/usd")
    oracle = oracle_from_settings()
    assert oracle.symbols == ["btc/usd", "eth/usd"]


# ---------------------------------------------------------------------
# price_to_beat capture (unchanged behaviour)
# ---------------------------------------------------------------------


def test_price_to_beat_explicit_and_text_and_none():
    assert get_price_to_beat({"priceToBeat": "104250.5"}) == pytest.approx(104250.5)
    assert get_price_to_beat(
        {"question": "Will Bitcoin close above $104,250.50 this candle?"}
    ) == pytest.approx(104250.5)
    assert get_price_to_beat({"slug": "btc-updown-5m-1771511700"}) is None
    assert get_price_to_beat({"priceToBeat": 2.5}) is None  # out of band
