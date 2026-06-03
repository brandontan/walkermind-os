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
    """Single fake conn: fetchrow → active_preset, fetch → market rows."""

    def __init__(self, preset: str | None, rows: list[dict]) -> None:
        self._preset = preset
        self._rows = rows
        self.queries: list[str] = []

    async def fetchrow(self, sql, *a):
        self.queries.append(sql)
        return {"active_preset": self._preset}

    async def fetch(self, sql, *a):
        self.queries.append(sql)
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


def test_sports_preset_uses_category_query():
    conn = _Conn("playbook", [])
    with _patch(conn):
        asyncio.run(r.get_market_feed(_user()))
    # generic in-category branch (ILIKE), not the crypto updown query
    assert any("category ILIKE" in q for q in conn.queries)
    assert not any("updown" in q for q in conn.queries)
