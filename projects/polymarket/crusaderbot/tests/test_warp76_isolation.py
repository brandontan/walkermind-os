"""WARP-76 H4 — multi-user isolation: /signals/recent leak fix.

The audit (reports/forge/isolation-audit.md) found exactly one cross-user leak:
the WebTrader ``GET /signals/recent`` endpoint returned EVERY feed's signal
publications to EVERY authenticated user, regardless of which feeds the user had
subscribed to. The fix scopes the query to the caller's active
``user_signal_subscriptions``.

These tests pin the fix two ways, hermetically (no real DB):
1. SQL contract — the executed query joins user_signal_subscriptions on the
   caller's user_id and only active subscriptions/feeds.
2. Cross-user leakage — with a fake conn that honours the user_id parameter
   against an in-memory feed→subscriber map, user A never receives user B's
   feed signals and vice-versa.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest


_UID_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_UID_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


class _RecordingConn:
    """Captures the SQL + args of the last fetch; returns canned rows."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []
        self.sql: str = ""
        self.args: tuple = ()

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        self.sql = sql
        self.args = args
        return self.rows


class _SubscriptionAwareConn:
    """Fake conn that emulates the subscription JOIN: returns only the
    publications whose feed is actively subscribed by the user_id in $1."""

    def __init__(self, *, publications, subscriptions) -> None:
        # publications: list of dicts incl. feed_id + the SELECTed columns
        # subscriptions: {feed_id: user_id} for ACTIVE subscriptions
        self._pubs = publications
        self._subs = subscriptions

    async def fetch(self, _sql: str, *args: Any) -> list[dict[str, Any]]:
        user_id = str(args[0])
        return [
            {k: v for k, v in p.items() if k != "feed_id"}
            for p in self._pubs
            if self._subs.get(p["feed_id"]) == user_id
        ]


class _Acquire:
    def __init__(self, conn) -> None:
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *_a: Any) -> bool:
        return False


class _Pool:
    def __init__(self, conn) -> None:
        self._conn = conn

    def acquire(self) -> _Acquire:
        return _Acquire(self._conn)


def _router():
    return pytest.importorskip(
        "projects.polymarket.crusaderbot.webtrader.backend.router"
    )


@pytest.mark.asyncio
async def test_signals_recent_sql_is_user_scoped(monkeypatch) -> None:
    rmod = _router()
    conn = _RecordingConn(rows=[])
    monkeypatch.setattr(rmod, "get_pool", lambda: _Pool(conn))

    await rmod.get_recent_signals(user={"user_id": _UID_A}, limit=10)

    sql = " ".join(conn.sql.split())  # normalise whitespace
    # Must scope to the caller's active subscriptions — no bare feed-wide read.
    assert "user_signal_subscriptions" in sql
    assert "s.user_id = $1::uuid" in sql
    assert "s.unsubscribed_at IS NULL" in sql
    # The caller's id is the first bound parameter (never another user's).
    assert conn.args[0] == _UID_A


@pytest.mark.asyncio
async def test_signals_recent_clamps_negative_limit(monkeypatch) -> None:
    rmod = _router()
    conn = _RecordingConn(rows=[])
    monkeypatch.setattr(rmod, "get_pool", lambda: _Pool(conn))
    # A negative limit must clamp to >= 1 (a negative SQL LIMIT errors in Postgres).
    await rmod.get_recent_signals(user={"user_id": _UID_A}, limit=-5)
    assert conn.args[1] == 1


@pytest.mark.asyncio
async def test_signals_recent_no_cross_user_leak(monkeypatch) -> None:
    rmod = _router()
    now = datetime.now(timezone.utc)
    publications = [
        {"feed_id": "feed-X", "market_id": "mX", "side": "yes",
         "target_price": 0.6, "signal_type": "entry", "published_at": now,
         "market_question": "X?"},
        {"feed_id": "feed-Y", "market_id": "mY", "side": "no",
         "target_price": 0.4, "signal_type": "entry", "published_at": now,
         "market_question": "Y?"},
    ]
    subscriptions = {"feed-X": _UID_A, "feed-Y": _UID_B}
    conn = _SubscriptionAwareConn(publications=publications, subscriptions=subscriptions)
    monkeypatch.setattr(rmod, "get_pool", lambda: _Pool(conn))

    a_signals = await rmod.get_recent_signals(user={"user_id": _UID_A}, limit=10)
    b_signals = await rmod.get_recent_signals(user={"user_id": _UID_B}, limit=10)

    a_markets = {s["market_id"] for s in a_signals}
    b_markets = {s["market_id"] for s in b_signals}
    assert a_markets == {"mX"}, "user A must see only their subscribed feed"
    assert b_markets == {"mY"}, "user B must see only their subscribed feed"
    # Hard isolation: no overlap, no leak of the other user's feed signal.
    assert a_markets.isdisjoint(b_markets)
