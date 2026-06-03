"""Hermetic tests for the preset-aware WebTrader market feed.

The /market-feed endpoint must reflect the user's active-preset CATEGORY:
crypto presets → up/down candle markets, weather → weather markets per city,
other → in-category markets. Regression guard for the bug where the scanner
showed BTC/ETH while the weather preset was active.

No DB, no network — pool access patched via asyncpg context-manager fakes.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest

from projects.polymarket.crusaderbot.webtrader.backend import router as r


class _Conn:
    """Single fake conn: fetchrow → active_preset + selected_assets, fetch → rows."""

    def __init__(
        self, preset: str | None, rows: list[dict], assets: list[str] | None = None
    ) -> None:
        self._preset = preset
        self._rows = rows
        self._assets = assets
        self.queries: list[str] = []
        self.fetch_args: list[tuple] = []

    async def fetchrow(self, sql, *a):
        self.queries.append(sql)
        return {"active_preset": self._preset, "selected_assets": self._assets}

    async def fetch(self, sql, *a):
        self.queries.append(sql)
        self.fetch_args.append(a)
        return self._rows


class _Pool:
    def __init__(self, conn: _Conn) -> None:
        self._c = conn

    def acquire(self):
        c = self._c

        class _Ctx:
            async def __aenter__(self_inner):
                return c

            async def __aexit__(self_inner, *a):
                return False

        return _Ctx()


def _wx_row(question: str, price: float = 0.6) -> dict:
    return {
        "question": question,
        "slug": "wx",
        "yes_price": price,
        "liquidity_usdc": 1000.0,
        "resolution_at": datetime.now(timezone.utc) + timedelta(hours=3),
    }


def _patch(conn: _Conn):
    return patch.object(r, "get_pool", return_value=_Pool(conn))


def _user() -> dict:
    return {"user_id": str(uuid4())}


# ── pure helpers ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("question,code", [
    ("Will the high temperature in New York City exceed 90F?", "NYC"),
    ("Highest temperature in Los Angeles tomorrow", "LA"),
    ("Will it be the hottest day in Chicago?", "CHI"),
    ("Bitcoin above $100k by July?", "WX"),  # no city → fallback
])
def test_weather_asset_code(question, code):
    assert r._weather_asset_code(question) == code


@pytest.mark.parametrize("question,code", [
    # Codex P2: short aliases ("la", "kl") must NOT match inside other city
    # names — word-boundary matching keeps Dallas=DAL, Kuala Lumpur=KUL.
    ("Will the high temperature in Dallas exceed 100F?", "DAL"),
    ("Highest temperature in Kuala Lumpur tomorrow", "KUL"),
])
def test_weather_asset_code_word_boundary(question, code):
    assert r._weather_asset_code(question) == code


@pytest.mark.parametrize("prob,lean", [(0.7, "UP"), (0.3, "DOWN"), (0.5, "EVEN")])
def test_lean_from_prob(prob, lean):
    assert r._lean_from_prob(prob) == lean


@pytest.mark.parametrize("slug,question,code", [
    # Regression: every Polymarket question slugs "will-the-…" — the raw first
    # token "WILL" rendered for every row. Skip filler → first meaningful token.
    ("will-the-lakers-beat-the-celtics-2026", "Will the Lakers beat the Celtics?", "LAKERS"),
    ("will-trump-win-2024", "Will Trump win?", "TRUMP"),
    ("", "Will the Chiefs win the game?", "CHIEFS"),  # slug empty → from question
    ("", "Will, the Lakers, again?", "LAKERS"),       # punctuation stripped from tokens
    ("", "", "MKT"),                                  # nothing usable → fallback
])
def test_short_market_code(slug, question, code):
    assert r._short_market_code(slug, question) == code


# ── dispatch ──────────────────────────────────────────────────────────────
def test_weather_preset_returns_weather_rows():
    rows = [_wx_row("High temp in New York City?"), _wx_row("High temp in Chicago?")]
    conn = _Conn("weather_monitor", rows)
    with _patch(conn):
        feed = asyncio.run(r.get_market_feed(_user()))
    assert {f.asset for f in feed} == {"NYC", "CHI"}
    assert any("category = 'Weather'" in q for q in conn.queries)
    assert not any("updown" in q for q in conn.queries)  # never the crypto query


def test_weather_preset_dedups_per_city():
    rows = [_wx_row("High temp in New York City bucket A?"),
            _wx_row("High temp in New York City bucket B?")]
    conn = _Conn("weather_monitor", rows)
    with _patch(conn):
        feed = asyncio.run(r.get_market_feed(_user()))
    assert len(feed) == 1 and feed[0].asset == "NYC"


def test_crypto_preset_uses_updown_query():
    conn = _Conn("close_sweep", [])
    with _patch(conn):
        feed = asyncio.run(r.get_market_feed(_user()))
    assert feed == []
    assert any("updown" in q for q in conn.queries)


def test_no_preset_defaults_to_crypto():
    conn = _Conn(None, [])
    with _patch(conn):
        asyncio.run(r.get_market_feed(_user()))
    assert any("updown" in q for q in conn.queries)


def test_sports_preset_uses_live_gamma_feed():
    # Playbook now sources the REAL upcoming sports board from Polymarket Gamma,
    # decoupled from the narrow trade-window DB sync (WARP/ROOT/dashboard-ux). It
    # must NOT fall back to the crypto updown query or the DB category query.
    r._SPORTS_FEED_CACHE.update({"at": 0.0, "items": []})
    r._SPORTS_FEED_IN_PROGRESS.clear()
    gamma = [
        {
            "slug": "nfl-buf-kc-2026",
            "question": "Will the Bills beat the Chiefs?",
            "category": "Sports, NFL",
            "outcomePrices": ["0.55", "0.45"],
            "liquidity": 25000.0,
            "gameStartTime": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
        },
        {
            "slug": "nba-lal-bos-2026",
            "question": "Will the Lakers beat the Celtics?",
            "category": "Sports, NBA",
            "outcomePrices": ["0.40", "0.60"],
            "liquidity": 12000.0,
            "endDate": (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat(),
        },
        # Past event — excluded (already started/closed).
        {
            "slug": "mlb-nyy-bos-2025",
            "question": "Old game",
            "category": "Sports, MLB",
            "outcomePrices": ["0.50", "0.50"],
            "liquidity": 5000.0,
            "endDate": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        },
        # Non-sports — excluded by category filter.
        {
            "slug": "scotus-ruling-2026",
            "question": "SCOTUS ruling?",
            "category": "Politics",
            "outcomePrices": ["0.50", "0.50"],
            "liquidity": 9000.0,
            "endDate": (datetime.now(timezone.utc) + timedelta(days=10)).isoformat(),
        },
    ]

    async def _fake_gamma(limit: int = 200):
        return gamma

    conn = _Conn("playbook", [])
    with _patch(conn), patch.object(r._polymarket, "get_events_with_markets", _fake_gamma):
        feed = asyncio.run(r.get_market_feed(_user()))
    # Only upcoming sports markets, nearest-event first (NBA 5h before NFL 2d).
    assert [f.asset for f in feed] == ["NBA", "NFL"]
    assert not any("updown" in q for q in conn.queries)         # never the crypto query
    assert not any("category ILIKE" in q for q in conn.queries)  # not the DB category feed


# ── crypto coin scoping (selected_assets) ─────────────────────────────────
def _crypto_row(asset: str, price: float = 0.6) -> dict:
    return {
        "asset": asset,
        "yes_price": price,
        "liquidity_usdc": 100.0,
        "resolution_at": datetime.now(timezone.utc) + timedelta(hours=1),
    }


def test_crypto_feed_scopes_to_selected_assets():
    # User picked BTC/ETH/SOL → ANY($1) param is exactly their lowercased set.
    conn = _Conn("candle_auto", [], assets=["BTC", "ETH", "SOL"])
    with _patch(conn):
        asyncio.run(r.get_market_feed(_user()))
    assert any("ANY($1" in q for q in conn.queries)
    assert conn.fetch_args[0][0] == ["btc", "eth", "sol"]


def test_crypto_feed_defaults_to_btc_eth_without_selection():
    conn = _Conn("candle_auto", [], assets=None)
    with _patch(conn):
        asyncio.run(r.get_market_feed(_user()))
    assert conn.fetch_args[0][0] == ["btc", "eth"]  # _DEFAULT_CRYPTO_SHORT_ASSETS


def test_crypto_feed_returns_selection_order():
    # DB yields sol/btc/eth; the feed must come back in the selected order.
    conn = _Conn(
        "candle_auto",
        [_crypto_row("sol"), _crypto_row("btc"), _crypto_row("eth")],
        assets=["BTC", "ETH", "SOL"],
    )
    with _patch(conn):
        feed = asyncio.run(r.get_market_feed(_user()))
    assert [f.asset for f in feed] == ["BTC", "ETH", "SOL"]
