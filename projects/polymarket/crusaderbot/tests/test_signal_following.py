"""Hermetic tests for the P3c signal-following strategy plane.

Coverage:
    * SignalFollowingStrategy — bootstrap idempotency, default_tp_sl, scan
                                empty path, scan happy path, scan expired,
                                evaluate_exit both triggers, defensive paths
    * signal_evaluator        — filter logic, size resolution, confidence
                                clamping, payload coercion, candidate build
    * SignalFeedService       — idempotent create_feed, publish_signal /
                                publish_exit input validation, subscribe
                                advisory-lock + result codes, unsubscribe
                                idempotency
    * Telegram handler        — Tier 2 gate, slug validator, MAX_SUB cap
                                surfacing, list / catalog / on / off paths
    * Keyboard helper         — signal_subs_list_kb shape

No DB, no broker, no Telegram network. Database access is patched via the
asyncpg pool acquire context manager so the strategy + service + handler
can be exercised end-to-end on the request boundary without spinning up
Postgres.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

from projects.polymarket.crusaderbot.domain.strategy import (
    StrategyRegistry,
    bootstrap_default_strategies,
)
from projects.polymarket.crusaderbot.domain.strategy.strategies.signal_following import (
    DEFAULT_SL_PCT,
    DEFAULT_TP_PCT,
    SignalFollowingStrategy,
)
from projects.polymarket.crusaderbot.domain.strategy.types import (
    ExitDecision,
    MarketFilters,
    SignalCandidate,
    UserContext,
)
from projects.polymarket.crusaderbot.services.signal_feed import (
    DEFAULT_CONFIDENCE,
    DEFAULT_TRADE_SIZE_USDC,
    MAX_SUBSCRIPTIONS_PER_USER,
    MIN_TRADE_SIZE_USDC,
)
from projects.polymarket.crusaderbot.services.signal_feed import (
    signal_evaluator as ev,
)
from projects.polymarket.crusaderbot.services.signal_feed import (
    signal_feed_service as svc,
)
from projects.polymarket.crusaderbot.bot.keyboards.signal_following import (
    signal_subs_list_kb,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_registry():
    StrategyRegistry._reset_for_tests()
    yield
    StrategyRegistry._reset_for_tests()


_USER_UUID = UUID("12345678-1234-5678-1234-567812345678")
_FEED_UUID = UUID("aabbccdd-1234-5678-1234-567812345678")
_PUB_UUID = UUID("ffeeddcc-1234-5678-1234-567812345678")


def _user_ctx(available: float = 1000.0,
              capital_pct: float = 0.10) -> UserContext:
    return UserContext(
        user_id=str(_USER_UUID),
        sub_account_id="sub_1",
        risk_profile="balanced",
        capital_allocation_pct=capital_pct,
        available_balance_usdc=available,
    )


def _market_filters(
    *,
    categories: list[str] | None = None,
    blacklist: list[str] | None = None,
) -> MarketFilters:
    return MarketFilters(
        categories=categories or [],
        min_liquidity=0.0,
        max_time_to_resolution_days=365,
        blacklisted_market_ids=blacklist or [],
    )


# ---------------------------------------------------------------------------
# Generic asyncpg fakes (mirrors the P3b copy_trade pattern).
# ---------------------------------------------------------------------------


class _FakeConn:
    def __init__(self,
                 fetch_results: list[list[dict]] | None = None,
                 fetchrow_results: list | None = None,
                 fetchval_results: list | None = None,
                 ) -> None:
        self._fetch_results = list(fetch_results or [])
        self._fetchrow_results = list(fetchrow_results or [])
        self._fetchval_results = list(fetchval_results or [])
        self.executes: list[tuple[str, tuple]] = []

    async def fetch(self, sql, *args):
        if not self._fetch_results:
            return []
        return self._fetch_results.pop(0)

    async def fetchrow(self, sql, *args):
        if not self._fetchrow_results:
            return None
        return self._fetchrow_results.pop(0)

    async def fetchval(self, sql, *args):
        if not self._fetchval_results:
            return 0
        return self._fetchval_results.pop(0)

    async def execute(self, sql, *args):
        self.executes.append((sql, args))
        return None


class _FakePool:
    def __init__(self, conn) -> None:
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _Ctx:
            async def __aenter__(self_inner):
                return conn

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        return _Ctx()


# ---------------------------------------------------------------------------
# Registry + strategy attributes
# ---------------------------------------------------------------------------


def test_signal_following_default_tp_sl_matches_spec():
    tp, sl = SignalFollowingStrategy().default_tp_sl()
    assert (tp, sl) == (DEFAULT_TP_PCT, DEFAULT_SL_PCT) == (0.20, 0.08)


def test_signal_following_strategy_attributes():
    assert SignalFollowingStrategy.name == "signal_following"
    assert SignalFollowingStrategy.version == "1.0.0"
    assert set(SignalFollowingStrategy.risk_profile_compatibility) == {
        "conservative", "balanced", "aggressive",
    }


def test_bootstrap_registers_both_strategies():
    reg = bootstrap_default_strategies()
    catalog = {c["name"] for c in reg.list_available()}
    assert {"copy_trade", "signal_following"} <= catalog
    sf = reg.get("signal_following")
    assert sf.name == "signal_following"
    assert sf.version == "1.0.0"


def test_bootstrap_is_idempotent_with_both_strategies():
    reg = bootstrap_default_strategies()
    bootstrap_default_strategies(reg)  # second call must not raise
    catalog = reg.list_available()
    assert sum(1 for c in catalog if c["name"] == "signal_following") == 1
    assert sum(1 for c in catalog if c["name"] == "copy_trade") == 1


# ---------------------------------------------------------------------------
# signal_evaluator — payload + helper coverage
# ---------------------------------------------------------------------------


def test_payload_dict_passthrough_when_dict():
    assert ev._payload_dict({"a": 1}) == {"a": 1}


def test_payload_dict_parses_json_string():
    assert ev._payload_dict('{"a": 1, "b": "x"}') == {"a": 1, "b": "x"}


def test_payload_dict_returns_empty_for_invalid_string():
    assert ev._payload_dict("not json") == {}


def test_payload_dict_returns_empty_for_non_object_json():
    assert ev._payload_dict('[1, 2, 3]') == {}


def test_payload_dict_returns_empty_for_none():
    assert ev._payload_dict(None) == {}


def test_passes_market_filters_default_permissive():
    assert ev._passes_market_filters("mkt_1", {}, _market_filters()) is True


def test_passes_market_filters_blacklist_blocks():
    f = _market_filters(blacklist=["mkt_blocked"])
    assert ev._passes_market_filters("mkt_blocked", {}, f) is False


def test_passes_market_filters_categories_intersect_pass():
    f = _market_filters(categories=["politics"])
    payload = {"categories": ["politics", "us"]}
    assert ev._passes_market_filters("mkt_1", payload, f) is True


def test_passes_market_filters_categories_no_overlap_fails():
    f = _market_filters(categories=["sports"])
    payload = {"categories": ["politics"]}
    assert ev._passes_market_filters("mkt_1", payload, f) is False


def test_passes_market_filters_categories_filter_set_payload_missing_skips():
    """Conservative skip — mirrors the P3b copy_trade behaviour when
    market metadata cannot satisfy an active category filter."""
    f = _market_filters(categories=["politics"])
    assert ev._passes_market_filters("mkt_1", {}, f) is False


def test_passes_market_filters_categories_payload_string_form():
    """Operators may publish a string `categories` field; coerced to a
    one-element set."""
    f = _market_filters(categories=["politics"])
    assert ev._passes_market_filters(
        "mkt_1", {"categories": "politics"}, f,
    ) is True


def test_resolve_size_from_payload_capped_by_allocation():
    user = _user_ctx(available=1000.0, capital_pct=0.10)
    out = ev._resolve_size_usdc({"size_usdc": 500.0}, user)
    # cap = 1000 * 0.10 = 100 — caps the operator's $500 suggestion.
    assert out == pytest.approx(100.0)


def test_resolve_size_uses_default_when_payload_missing():
    user = _user_ctx(available=1000.0, capital_pct=0.10)
    out = ev._resolve_size_usdc({}, user)
    # min(default $10, cap $100) = $10
    assert out == pytest.approx(DEFAULT_TRADE_SIZE_USDC)


def test_resolve_size_below_floor_returns_zero():
    # cap = 5 * 0.10 = 0.5 — below the $1 floor, must skip.
    user = _user_ctx(available=5.0, capital_pct=0.10)
    out = ev._resolve_size_usdc({"size_usdc": 50.0}, user)
    assert out == 0.0


def test_resolve_size_zero_allocation_returns_zero():
    user = _user_ctx(available=1000.0, capital_pct=0.0)
    out = ev._resolve_size_usdc({"size_usdc": 50.0}, user)
    assert out == 0.0


def test_resolve_size_zero_balance_returns_zero():
    user = _user_ctx(available=0.0, capital_pct=0.10)
    out = ev._resolve_size_usdc({"size_usdc": 50.0}, user)
    assert out == 0.0


def test_resolve_confidence_clamps_above_one():
    assert ev._resolve_confidence({"confidence": 1.5}) == 1.0


def test_resolve_confidence_clamps_below_zero():
    assert ev._resolve_confidence({"confidence": -0.5}) == 0.0


def test_resolve_confidence_default_when_missing():
    assert ev._resolve_confidence({}) == DEFAULT_CONFIDENCE


def test_resolve_confidence_default_when_invalid():
    assert ev._resolve_confidence({"confidence": "garbage"}) == DEFAULT_CONFIDENCE


# ---------------------------------------------------------------------------
# evaluate_publications_for_user — scan happy / no-subs / expired / dedup-paths
# ---------------------------------------------------------------------------


def _patch_evaluator_pool(conn: _FakeConn):
    return patch.object(ev, "get_pool", return_value=_FakePool(conn))


def _publication_row(
    *,
    pub_id: UUID = _PUB_UUID,
    feed_id: UUID = _FEED_UUID,
    market_id: str = "mkt_1",
    side: str = "YES",
    payload: dict | None = None,
    published_at: datetime | None = None,
    expires_at: datetime | None = None,
    exit_signal: bool = False,
    exit_published_at: datetime | None = None,
) -> dict:
    return {
        "id": pub_id,
        "feed_id": feed_id,
        "market_id": market_id,
        "side": side,
        "target_price": 0.55,
        "signal_type": "entry",
        "payload": payload if payload is not None else {},
        "exit_signal": exit_signal,
        "published_at": published_at or datetime.now(timezone.utc),
        "expires_at": expires_at,
        "exit_published_at": exit_published_at,
    }


def _subscription_row(
    *,
    feed_id: UUID = _FEED_UUID,
    subscribed_at: datetime | None = None,
) -> dict:
    return {
        "id": uuid4(),
        "feed_id": feed_id,
        "subscribed_at": subscribed_at or datetime.now(timezone.utc) - timedelta(days=1),
        "feed_status": "active",
    }


def test_evaluate_returns_empty_when_no_subscriptions():
    conn = _FakeConn(fetch_results=[[]])  # _load_active_subscriptions -> []
    with _patch_evaluator_pool(conn):
        out = asyncio.run(ev.evaluate_publications_for_user(
            user_context=_user_ctx(),
            market_filters=_market_filters(),
            strategy_name="signal_following",
        ))
    assert out == []


def test_evaluate_emits_candidate_for_active_publication():
    sub = _subscription_row()
    pub = _publication_row(payload={"size_usdc": 25.0, "confidence": 0.8})
    conn = _FakeConn(fetch_results=[[sub], [pub]])
    with _patch_evaluator_pool(conn):
        out = asyncio.run(ev.evaluate_publications_for_user(
            user_context=_user_ctx(),
            market_filters=_market_filters(),
            strategy_name="signal_following",
        ))
    assert len(out) == 1
    cand = out[0]
    assert isinstance(cand, SignalCandidate)
    assert cand.market_id == "mkt_1"
    assert cand.side == "YES"
    assert cand.confidence == pytest.approx(0.8)
    # cap = 1000 * 0.10 = 100; payload 25 < cap -> 25.
    assert cand.suggested_size_usdc == pytest.approx(25.0)
    assert cand.metadata["feed_id"] == str(_FEED_UUID)
    assert cand.metadata["publication_id"] == str(_PUB_UUID)
    assert cand.metadata["market_id"] == "mkt_1"
    assert cand.strategy_name == "signal_following"


def test_evaluate_skips_blacklisted_market():
    sub = _subscription_row()
    pub = _publication_row(market_id="mkt_blocked",
                            payload={"size_usdc": 25.0})
    conn = _FakeConn(fetch_results=[[sub], [pub]])
    with _patch_evaluator_pool(conn):
        out = asyncio.run(ev.evaluate_publications_for_user(
            user_context=_user_ctx(),
            market_filters=_market_filters(blacklist=["mkt_blocked"]),
            strategy_name="signal_following",
        ))
    assert out == []


def test_evaluate_skips_when_categories_filter_set_payload_missing():
    sub = _subscription_row()
    pub = _publication_row(payload={"size_usdc": 25.0})
    conn = _FakeConn(fetch_results=[[sub], [pub]])
    with _patch_evaluator_pool(conn):
        out = asyncio.run(ev.evaluate_publications_for_user(
            user_context=_user_ctx(),
            market_filters=_market_filters(categories=["politics"]),
            strategy_name="signal_following",
        ))
    assert out == []


def test_evaluate_skips_publication_with_invalid_side():
    sub = _subscription_row()
    pub = _publication_row(side="LONG", payload={"size_usdc": 25.0})
    conn = _FakeConn(fetch_results=[[sub], [pub]])
    with _patch_evaluator_pool(conn):
        out = asyncio.run(ev.evaluate_publications_for_user(
            user_context=_user_ctx(),
            market_filters=_market_filters(),
            strategy_name="signal_following",
        ))
    assert out == []


def test_evaluate_handles_publication_fetch_failure():
    """A DB hiccup on one feed must not crash the whole scan tick."""
    sub = _subscription_row()

    class _RaisingConn(_FakeConn):
        def __init__(self):
            super().__init__(fetch_results=[[sub]])
            self._call = 0

        async def fetch(self, sql, *args):
            self._call += 1
            if self._call == 1:
                return [sub]
            raise RuntimeError("boom")

    conn = _RaisingConn()
    with _patch_evaluator_pool(conn):
        out = asyncio.run(ev.evaluate_publications_for_user(
            user_context=_user_ctx(),
            market_filters=_market_filters(),
            strategy_name="signal_following",
        ))
    assert out == []


def test_evaluate_uses_default_size_when_payload_missing_size():
    sub = _subscription_row()
    pub = _publication_row(payload={})
    conn = _FakeConn(fetch_results=[[sub], [pub]])
    with _patch_evaluator_pool(conn):
        out = asyncio.run(ev.evaluate_publications_for_user(
            user_context=_user_ctx(available=1000.0, capital_pct=0.10),
            market_filters=_market_filters(),
            strategy_name="signal_following",
        ))
    assert len(out) == 1
    assert out[0].suggested_size_usdc == pytest.approx(DEFAULT_TRADE_SIZE_USDC)
    # Default confidence applied.
    assert out[0].confidence == pytest.approx(DEFAULT_CONFIDENCE)


def test_evaluate_synthesises_condition_id_from_market_id():
    sub = _subscription_row()
    pub = _publication_row(payload={"size_usdc": 25.0})
    conn = _FakeConn(fetch_results=[[sub], [pub]])
    with _patch_evaluator_pool(conn):
        out = asyncio.run(ev.evaluate_publications_for_user(
            user_context=_user_ctx(),
            market_filters=_market_filters(),
            strategy_name="signal_following",
        ))
    assert len(out) == 1
    # Payload had no condition_id — fall back to market_id.
    assert out[0].condition_id == "mkt_1"


def test_evaluate_uses_payload_condition_id_when_present():
    sub = _subscription_row()
    pub = _publication_row(
        payload={"size_usdc": 25.0, "condition_id": "0xcond_explicit"},
    )
    conn = _FakeConn(fetch_results=[[sub], [pub]])
    with _patch_evaluator_pool(conn):
        out = asyncio.run(ev.evaluate_publications_for_user(
            user_context=_user_ctx(),
            market_filters=_market_filters(),
            strategy_name="signal_following",
        ))
    assert out[0].condition_id == "0xcond_explicit"


# ---------------------------------------------------------------------------
# SignalFollowingStrategy.scan / evaluate_exit
# ---------------------------------------------------------------------------


def test_strategy_scan_swallows_evaluator_exception():
    """A scan failure must yield an empty list, never raise."""
    strat = SignalFollowingStrategy()

    async def boom(**kwargs):
        raise RuntimeError("evaluator down")

    with patch.object(
        ev, "evaluate_publications_for_user", side_effect=boom,
    ):
        out = asyncio.run(strat.scan(_market_filters(), _user_ctx()))
    assert out == []


def test_strategy_scan_delegates_to_evaluator():
    strat = SignalFollowingStrategy()
    expected = SignalCandidate(
        market_id="mkt_1",
        condition_id="mkt_1",
        side="YES",
        confidence=0.7,
        suggested_size_usdc=10.0,
        strategy_name="signal_following",
        signal_ts=datetime.now(timezone.utc),
        metadata={"feed_id": str(_FEED_UUID),
                  "publication_id": str(_PUB_UUID),
                  "market_id": "mkt_1"},
    )

    async def fake_eval(**kwargs):
        assert kwargs["strategy_name"] == "signal_following"
        return [expected]

    # Patch the symbol that signal_following.py imported, not the source
    # module — function references are bound at import time.
    from projects.polymarket.crusaderbot.domain.strategy.strategies import (
        signal_following as sf_mod,
    )
    with patch.object(
        sf_mod, "evaluate_publications_for_user", side_effect=fake_eval,
    ):
        out = asyncio.run(strat.scan(_market_filters(), _user_ctx()))
    assert out == [expected]


def _patch_strategy_pool(conn: _FakeConn):
    """Patch the get_pool used inside signal_following.py for evaluate_exit."""
    from projects.polymarket.crusaderbot.domain.strategy.strategies import (
        signal_following as sf_mod,
    )
    return patch.object(sf_mod, "get_pool", return_value=_FakePool(conn))


def test_evaluate_exit_holds_when_no_feed_id_in_metadata():
    strat = SignalFollowingStrategy()
    pos = {"metadata": {}, "market_id": "mkt_1"}
    out = asyncio.run(strat.evaluate_exit(pos))
    assert out == ExitDecision(should_exit=False, reason="hold")


def test_evaluate_exit_holds_when_no_market_id():
    strat = SignalFollowingStrategy()
    pos = {"metadata": {"feed_id": str(_FEED_UUID)}}
    out = asyncio.run(strat.evaluate_exit(pos))
    assert out == ExitDecision(should_exit=False, reason="hold")


def test_evaluate_exit_emits_strategy_exit_when_publication_retired():
    """Trigger (a): the originating publication has exit_published_at set.

    First fetchrow is the origin lookup — when exit_published_at is set on
    the origin row, the function short-circuits before the later
    exit_signal lookup.
    """
    strat = SignalFollowingStrategy()
    now = datetime.now(timezone.utc)
    conn = _FakeConn(fetchrow_results=[
        {"published_at": now - timedelta(hours=1),
         "exit_published_at": now},
    ])
    pos = {
        "metadata": {
            "feed_id": str(_FEED_UUID),
            "publication_id": str(_PUB_UUID),
            "market_id": "mkt_1",
        },
    }
    with _patch_strategy_pool(conn):
        out = asyncio.run(strat.evaluate_exit(pos))
    assert out.should_exit is True
    assert out.reason == "strategy_exit"
    assert out.metadata["reason"] == "signal_exit_published"
    assert out.metadata["feed_id"] == str(_FEED_UUID)


def test_evaluate_exit_emits_strategy_exit_when_separate_exit_signal():
    """Trigger (b): a later publication on same feed+market has exit_signal=TRUE.

    Path: no publication_id in metadata, so anchor falls back to
    position.opened_at; the later-exit-signal lookup returns a row.
    """
    strat = SignalFollowingStrategy()
    now = datetime.now(timezone.utc)
    conn = _FakeConn(fetchrow_results=[{"?column?": 1}])
    pos = {
        "metadata": {
            "feed_id": str(_FEED_UUID),
            # no publication_id — anchor must come from position timestamps
            "market_id": "mkt_1",
        },
        "opened_at": now - timedelta(hours=1),
    }
    with _patch_strategy_pool(conn):
        out = asyncio.run(strat.evaluate_exit(pos))
    assert out.should_exit is True
    assert out.reason == "strategy_exit"


def test_evaluate_exit_ignores_stale_exit_signal_published_before_origin():
    """Re-entry safety: an exit_signal row published BEFORE the originating
    entry must NOT retire the new position. The query bounds the lookup
    by `published_at > anchor`, so a stale exit row from a previous trade
    cycle is filtered out at the SQL boundary; the test asserts the hold
    path when that filtered query returns no rows."""
    strat = SignalFollowingStrategy()
    now = datetime.now(timezone.utc)
    conn = _FakeConn(fetchrow_results=[
        # origin: published 1h ago, no exit_published_at
        {"published_at": now - timedelta(hours=1),
         "exit_published_at": None},
        # exit_signal lookup returns None — any stale rows from before
        # the origin's published_at are filtered out by `published_at > $3`.
        None,
    ])
    pos = {
        "metadata": {
            "feed_id": str(_FEED_UUID),
            "publication_id": str(_PUB_UUID),
            "market_id": "mkt_1",
        },
    }
    with _patch_strategy_pool(conn):
        out = asyncio.run(strat.evaluate_exit(pos))
    assert out.should_exit is False
    assert out.reason == "hold"


def test_evaluate_exit_holds_when_no_anchor_available():
    """Without publication_id and without position timestamps, the
    evaluator cannot distinguish stale from fresh exits — hold."""
    strat = SignalFollowingStrategy()
    conn = _FakeConn()  # no fetchrow expected; hold short-circuits.
    pos = {
        "metadata": {
            "feed_id": str(_FEED_UUID),
            "market_id": "mkt_1",
        },
        # no opened_at, no created_at
    }
    with _patch_strategy_pool(conn):
        out = asyncio.run(strat.evaluate_exit(pos))
    assert out.should_exit is False
    assert out.reason == "hold"


def test_evaluate_exit_holds_when_no_exit_row_found():
    """Origin lookup returns row without exit_published_at, and the
    exit_signal lookup returns None."""
    strat = SignalFollowingStrategy()
    now = datetime.now(timezone.utc)
    conn = _FakeConn(fetchrow_results=[
        {"published_at": now - timedelta(hours=1),
         "exit_published_at": None},
        None,
    ])
    pos = {
        "metadata": {
            "feed_id": str(_FEED_UUID),
            "publication_id": str(_PUB_UUID),
            "market_id": "mkt_1",
        },
    }
    with _patch_strategy_pool(conn):
        out = asyncio.run(strat.evaluate_exit(pos))
    assert out == ExitDecision(should_exit=False, reason="hold")


def test_evaluate_exit_holds_on_db_error():
    """A transient DB error must hold rather than flip the position."""
    strat = SignalFollowingStrategy()

    class _BoomConn(_FakeConn):
        async def fetchrow(self, sql, *args):
            raise RuntimeError("db down")

    pos = {
        "metadata": {
            "feed_id": str(_FEED_UUID),
            "publication_id": str(_PUB_UUID),
            "market_id": "mkt_1",
        },
    }
    with _patch_strategy_pool(_BoomConn()):
        out = asyncio.run(strat.evaluate_exit(pos))
    assert out.should_exit is False
    assert out.reason == "hold"


# ---------------------------------------------------------------------------
# SignalFeedService — idempotency + input validation + advisory lock
# ---------------------------------------------------------------------------


class _AtomicConn:
    """asyncpg.Connection stand-in supporting `transaction()` + a scripted
    sequence of fetchrow / fetchval responses keyed by SQL substring."""

    def __init__(self, *,
                 feed_row=None,
                 existing_sub_row=None,
                 active_count: int = 0,
                 unsub_returning=None,
                 ) -> None:
        self.sql_log: list[tuple[str, str, tuple]] = []
        self._feed_row = feed_row
        self._existing_sub_row = existing_sub_row
        self._active_count = active_count
        self._unsub_returning = unsub_returning
        self.in_transaction = False

    def transaction(self):
        conn = self

        class _T:
            async def __aenter__(self_inner):
                conn.in_transaction = True
                conn.sql_log.append(("BEGIN", "", ()))
                return self_inner

            async def __aexit__(self_inner, exc_type, exc, tb):
                conn.in_transaction = False
                conn.sql_log.append(
                    ("COMMIT" if exc is None else "ROLLBACK", "", ()),
                )
                return False

        return _T()

    async def execute(self, sql, *args):
        self.sql_log.append(("execute", sql, args))
        return None

    async def fetchrow(self, sql, *args):
        self.sql_log.append(("fetchrow", sql, args))
        if "FROM signal_feeds" in sql and "WHERE id" in sql:
            return self._feed_row
        if "FROM signal_feeds" in sql and "WHERE slug" in sql:
            return self._feed_row
        if "FROM user_signal_subscriptions" in sql \
                and "WHERE user_id" in sql and "feed_id" in sql:
            return self._existing_sub_row
        if "UPDATE user_signal_subscriptions" in sql \
                and "RETURNING id" in sql:
            return self._unsub_returning
        if "INSERT INTO signal_feeds" in sql and "RETURNING" in sql:
            return self._feed_row or {"id": uuid4(), "name": "x",
                                       "slug": "x", "operator_id": uuid4(),
                                       "status": "active",
                                       "description": None,
                                       "subscriber_count": 0,
                                       "created_at": datetime.now(timezone.utc),
                                       "updated_at": datetime.now(timezone.utc)}
        if "INSERT INTO signal_publications" in sql:
            return {"id": uuid4(), "feed_id": uuid4(),
                    "market_id": "mkt_1", "side": "YES",
                    "target_price": None, "signal_type": "entry",
                    "payload": {}, "exit_signal": False,
                    "published_at": datetime.now(timezone.utc),
                    "expires_at": None, "exit_published_at": None}
        return None

    async def fetchval(self, sql, *args):
        self.sql_log.append(("fetchval", sql, args))
        if "COUNT(*)" in sql and "FROM user_signal_subscriptions" in sql:
            return self._active_count
        return 0

    async def fetch(self, sql, *args):
        self.sql_log.append(("fetch", sql, args))
        return []


class _AtomicPool:
    def __init__(self, conn) -> None:
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _Ctx:
            async def __aenter__(self_inner):
                return conn

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        return _Ctx()


def _patch_svc_pool(conn: _AtomicConn):
    return patch.object(svc, "get_pool", return_value=_AtomicPool(conn))


def test_create_feed_returns_existing_when_slug_exists():
    """Idempotent — re-calling with same slug must NOT issue an INSERT."""
    existing = {
        "id": _FEED_UUID, "name": "Alpha", "slug": "alpha",
        "operator_id": uuid4(), "status": "active",
        "description": None, "subscriber_count": 0,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    conn = _AtomicConn(feed_row=existing)
    with _patch_svc_pool(conn):
        out = asyncio.run(svc.create_feed(
            name="Alpha", slug="alpha", operator_id=uuid4(),
        ))
    assert out["id"] == _FEED_UUID
    insert_calls = [
        e for e in conn.sql_log
        if e[0] == "fetchrow" and "INSERT INTO signal_feeds" in e[1]
    ]
    assert insert_calls == []


def test_create_feed_inserts_when_slug_missing():
    conn = _AtomicConn(feed_row=None)
    with _patch_svc_pool(conn):
        out = asyncio.run(svc.create_feed(
            name="Alpha", slug="alpha-new", operator_id=uuid4(),
        ))
    assert out["slug"] in {"alpha-new", "x"} or "id" in out
    insert_calls = [
        e for e in conn.sql_log
        if e[0] == "fetchrow" and "INSERT INTO signal_feeds" in e[1]
    ]
    assert len(insert_calls) == 1


def test_create_feed_rejects_empty_slug():
    with pytest.raises(ValueError):
        asyncio.run(svc.create_feed(
            name="x", slug="", operator_id=uuid4(),
        ))


def test_publish_signal_validates_side():
    with pytest.raises(ValueError):
        asyncio.run(svc.publish_signal(
            feed_id=_FEED_UUID, market_id="mkt_1", side="LONG",
        ))


def test_publish_signal_validates_market_id():
    with pytest.raises(ValueError):
        asyncio.run(svc.publish_signal(
            feed_id=_FEED_UUID, market_id="", side="YES",
        ))


def test_publish_signal_validates_feed_id():
    with pytest.raises(ValueError):
        asyncio.run(svc.publish_signal(
            feed_id="not-a-uuid", market_id="mkt_1", side="YES",
        ))


def test_publish_exit_validates_market_id():
    with pytest.raises(ValueError):
        asyncio.run(svc.publish_exit(feed_id=_FEED_UUID, market_id=""))


def test_subscribe_returns_unknown_feed():
    conn = _AtomicConn(feed_row=None)
    with _patch_svc_pool(conn):
        result = asyncio.run(svc.subscribe(
            user_id=_USER_UUID, feed_id=_FEED_UUID,
        ))
    assert result == "unknown_feed"


def test_subscribe_returns_feed_inactive():
    conn = _AtomicConn(feed_row={"status": "paused"})
    with _patch_svc_pool(conn):
        result = asyncio.run(svc.subscribe(
            user_id=_USER_UUID, feed_id=_FEED_UUID,
        ))
    assert result == "feed_inactive"


def test_subscribe_returns_exists_when_already_active():
    conn = _AtomicConn(
        feed_row={"status": "active"},
        existing_sub_row={"id": uuid4()},
    )
    with _patch_svc_pool(conn):
        result = asyncio.run(svc.subscribe(
            user_id=_USER_UUID, feed_id=_FEED_UUID,
        ))
    assert result == "exists"


def test_subscribe_returns_cap_exceeded_at_or_above_cap():
    conn = _AtomicConn(
        feed_row={"status": "active"},
        existing_sub_row=None,
        active_count=MAX_SUBSCRIPTIONS_PER_USER,
    )
    with _patch_svc_pool(conn):
        result = asyncio.run(svc.subscribe(
            user_id=_USER_UUID, feed_id=_FEED_UUID,
        ))
    assert result == "cap_exceeded"
    # No INSERT should have run.
    inserts = [
        e for e in conn.sql_log
        if e[0] == "execute"
        and "INSERT INTO user_signal_subscriptions" in e[1]
    ]
    assert inserts == []


def test_subscribe_returns_subscribed_under_cap_with_advisory_lock():
    conn = _AtomicConn(
        feed_row={"status": "active"},
        existing_sub_row=None,
        active_count=2,
    )
    with _patch_svc_pool(conn):
        result = asyncio.run(svc.subscribe(
            user_id=_USER_UUID, feed_id=_FEED_UUID,
        ))
    assert result == "subscribed"
    # BEGIN and COMMIT must wrap the work.
    kinds = [e[0] for e in conn.sql_log]
    assert kinds[0] == "BEGIN"
    assert kinds[-1] == "COMMIT"
    # Advisory lock keyed on str(user_id).
    advisory = [
        e for e in conn.sql_log
        if e[0] == "execute" and "pg_advisory_xact_lock" in e[1]
    ]
    assert len(advisory) == 1
    assert advisory[0][2] == (str(_USER_UUID),)
    # subscriber_count incremented.
    bumps = [
        e for e in conn.sql_log
        if e[0] == "execute"
        and "subscriber_count = subscriber_count + 1" in e[1]
    ]
    assert len(bumps) == 1


def test_unsubscribe_returns_false_when_no_active_row():
    conn = _AtomicConn(unsub_returning=None)
    with _patch_svc_pool(conn):
        flipped = asyncio.run(svc.unsubscribe(
            user_id=_USER_UUID, feed_id=_FEED_UUID,
        ))
    assert flipped is False


def test_unsubscribe_returns_true_and_decrements_count():
    conn = _AtomicConn(unsub_returning={"id": uuid4()})
    with _patch_svc_pool(conn):
        flipped = asyncio.run(svc.unsubscribe(
            user_id=_USER_UUID, feed_id=_FEED_UUID,
        ))
    assert flipped is True
    decs = [
        e for e in conn.sql_log
        if e[0] == "execute"
        and "subscriber_count - 1" in e[1]
    ]
    assert len(decs) == 1


# ---------------------------------------------------------------------------
# /signals Telegram handler — Tier gate + slug validation + cap surfacing
# ---------------------------------------------------------------------------


from projects.polymarket.crusaderbot.bot.handlers import (
    signal_following as sf_handler,
)
from projects.polymarket.crusaderbot.bot.tier import Tier


def _fake_update_message(text: str = "/signals"):
    """Build a minimal Update-like object with a text message."""
    reply = AsyncMock()
    msg = SimpleNamespace(text=text, reply_text=reply)
    user = SimpleNamespace(id=42, username="u")
    return SimpleNamespace(
        message=msg,
        effective_user=user,
        callback_query=None,
    ), reply


def _fake_ctx(args: list[str] | None = None):
    return SimpleNamespace(args=list(args or []))


def test_normalise_slug_accepts_lowercase_alnum_dash_underscore():
    assert sf_handler._normalise_slug("alpha-feed") == "alpha-feed"
    assert sf_handler._normalise_slug("ALPHA_feed") == "alpha_feed"
    assert sf_handler._normalise_slug("Bad Slug") is None
    assert sf_handler._normalise_slug("") is None
    assert sf_handler._normalise_slug("a") is None  # min len 2


def test_normalise_slug_accepts_max_length_50():
    s = "a" + "b" * 49  # 50 chars total
    assert sf_handler._normalise_slug(s) == s


def test_normalise_slug_rejects_above_max_length():
    s = "a" + "b" * 50  # 51 chars total
    assert sf_handler._normalise_slug(s) is None


def test_signal_callback_data_under_telegram_64byte_limit():
    """Telegram caps inline-keyboard callback_data at 64 bytes. With the
    "signals:off:" prefix at 12 bytes, slugs must be <= 50 chars to keep
    the round-trip under the ceiling."""
    max_slug = "a" + "b" * 49  # 50 chars
    kb = signal_subs_list_kb([(max_slug, "Alpha")])
    cb = kb.inline_keyboard[0][0].callback_data
    assert len(cb.encode("utf-8")) <= 64


def test_create_feed_rejects_slug_above_max_length():
    too_long = "a" + "b" * 50  # 51 chars
    with pytest.raises(ValueError):
        asyncio.run(svc.create_feed(
            name="x", slug=too_long, operator_id=uuid4(),
        ))


def test_create_feed_rejects_uppercase_slug():
    """Operators must provide canonical lowercase slugs — the handler
    never queries by uppercase, so admitting `Alpha` would persist a feed
    that users cannot subscribe to."""
    with pytest.raises(ValueError):
        asyncio.run(svc.create_feed(
            name="X", slug="Alpha", operator_id=uuid4(),
        ))


def test_create_feed_rejects_single_char_slug():
    """Slug regex requires 2-50 chars; single char fails the {1,49} tail."""
    with pytest.raises(ValueError):
        asyncio.run(svc.create_feed(
            name="X", slug="x", operator_id=uuid4(),
        ))


def test_create_feed_rejects_dot_slug():
    """`.` is outside the allowed character class — bot lookups would
    reject the slug at validation time."""
    with pytest.raises(ValueError):
        asyncio.run(svc.create_feed(
            name="X", slug="alpha.feed", operator_id=uuid4(),
        ))


def test_create_feed_rejects_non_ascii_slug():
    """Non-ASCII slugs violate both the character class AND the
    char-count == byte-count assumption that keeps callback_data under
    Telegram's 64-byte ceiling."""
    with pytest.raises(ValueError):
        asyncio.run(svc.create_feed(
            name="X", slug="café", operator_id=uuid4(),
        ))


def test_create_feed_rejects_slug_starting_with_dash():
    """Regex requires the first character to be alphanumeric."""
    with pytest.raises(ValueError):
        asyncio.run(svc.create_feed(
            name="X", slug="-alpha", operator_id=uuid4(),
        ))


def test_handler_and_service_share_slug_pattern():
    """Single-source-of-truth check: the handler regex compiles from the
    service's SLUG_PATTERN, so any future widening at the service layer
    is automatically picked up by the bot."""
    from projects.polymarket.crusaderbot.services.signal_feed import (
        SLUG_PATTERN as service_pattern,
    )
    assert sf_handler._SLUG_RE.pattern == service_pattern


def test_escape_md_escapes_legacy_v1_metachars():
    assert sf_handler._escape_md("Alpha_Beta") == r"Alpha\_Beta"
    assert sf_handler._escape_md("X*Y") == r"X\*Y"
    assert sf_handler._escape_md("[link](u)") == r"\[link](u)"
    assert sf_handler._escape_md("a`b") == "a\\`b"


def test_escape_md_escapes_backslash_first():
    """Backslash must be doubled before the metacharacter loop runs,
    otherwise an escape sequence inserted by the loop would itself be
    re-escaped on a later pass."""
    assert sf_handler._escape_md(r"a\b") == r"a\\b"


def test_escape_md_handles_none_and_empty():
    assert sf_handler._escape_md(None) == ""
    assert sf_handler._escape_md("") == ""


def test_signals_catalog_escapes_feed_name_and_description():
    """Operator-supplied feed_name + description must not break the
    Markdown reply with stray metacharacters."""
    update, reply = _fake_update_message()
    ctx = _fake_ctx(["catalog"])
    user_ok = {"id": uuid4(), "access_tier": Tier.ALLOWLISTED}
    feeds = [{
        "id": _FEED_UUID, "name": "Alpha_Beta", "slug": "alpha",
        "operator_id": uuid4(), "status": "active",
        "description": "Has [brackets] and *stars*",
        "subscriber_count": 3,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }]
    with patch.object(sf_handler, "upsert_user", return_value=user_ok), \
         patch.object(sf_handler, "list_active_feeds", return_value=feeds):
        asyncio.run(sf_handler.signals_command(update, ctx))
    text = reply.call_args[0][0]
    assert r"Alpha\_Beta" in text
    assert r"\[brackets]" in text
    assert r"\*stars\*" in text


def test_signals_list_escapes_feed_name():
    update, reply = _fake_update_message()
    ctx = _fake_ctx(["list"])
    user_ok = {"id": uuid4(), "access_tier": Tier.ALLOWLISTED}
    subs = [{
        "feed_slug": "alpha", "feed_name": "Alpha_Beta",
        "subscribed_at": datetime.now(timezone.utc),
    }]
    with patch.object(sf_handler, "upsert_user", return_value=user_ok), \
         patch.object(sf_handler, "list_user_subscriptions",
                       return_value=subs):
        asyncio.run(sf_handler.signals_command(update, ctx))
    text = reply.call_args[0][0]
    assert r"Alpha\_Beta" in text


def test_signals_command_blocked_for_tier_below_2():
    update, reply = _fake_update_message()
    ctx = _fake_ctx()
    user_below = {"id": uuid4(), "access_tier": Tier.BROWSE}
    with patch.object(sf_handler, "upsert_user",
                       return_value=user_below):
        asyncio.run(sf_handler.signals_command(update, ctx))
    reply.assert_called_once()
    text = reply.call_args[0][0]
    assert "Tier 2" in text


def test_signals_command_no_args_shows_usage():
    update, reply = _fake_update_message()
    ctx = _fake_ctx()
    user_ok = {"id": uuid4(), "access_tier": Tier.ALLOWLISTED}
    with patch.object(sf_handler, "upsert_user", return_value=user_ok):
        asyncio.run(sf_handler.signals_command(update, ctx))
    reply.assert_called_once()
    assert "/signals" in reply.call_args[0][0]
    assert str(MAX_SUBSCRIPTIONS_PER_USER) in reply.call_args[0][0]


def test_signals_on_invalid_slug_message():
    update, reply = _fake_update_message()
    ctx = _fake_ctx(["on", "Bad Slug!"])
    user_ok = {"id": uuid4(), "access_tier": Tier.ALLOWLISTED}
    with patch.object(sf_handler, "upsert_user", return_value=user_ok):
        asyncio.run(sf_handler.signals_command(update, ctx))
    reply.assert_called_once()
    assert "Invalid feed slug" in reply.call_args[0][0]


def test_signals_on_unknown_feed_message():
    update, reply = _fake_update_message()
    ctx = _fake_ctx(["on", "alpha"])
    user_ok = {"id": uuid4(), "access_tier": Tier.ALLOWLISTED}
    with patch.object(sf_handler, "upsert_user", return_value=user_ok), \
         patch.object(sf_handler, "get_feed_by_slug", return_value=None):
        asyncio.run(sf_handler.signals_command(update, ctx))
    reply.assert_called_once()
    assert "No feed" in reply.call_args[0][0]


def test_signals_on_cap_exceeded_message():
    update, reply = _fake_update_message()
    ctx = _fake_ctx(["on", "alpha"])
    user_ok = {"id": uuid4(), "access_tier": Tier.ALLOWLISTED}
    feed = {"id": _FEED_UUID, "name": "Alpha", "slug": "alpha",
            "status": "active"}
    with patch.object(sf_handler, "upsert_user", return_value=user_ok), \
         patch.object(sf_handler, "get_feed_by_slug", return_value=feed), \
         patch.object(sf_handler, "subscribe", return_value="cap_exceeded"):
        asyncio.run(sf_handler.signals_command(update, ctx))
    reply.assert_called_once()
    text = reply.call_args[0][0]
    assert str(MAX_SUBSCRIPTIONS_PER_USER) in text


def test_signals_on_subscribed_message():
    update, reply = _fake_update_message()
    ctx = _fake_ctx(["on", "alpha"])
    user_ok = {"id": uuid4(), "access_tier": Tier.ALLOWLISTED}
    feed = {"id": _FEED_UUID, "name": "Alpha", "slug": "alpha",
            "status": "active"}
    with patch.object(sf_handler, "upsert_user", return_value=user_ok), \
         patch.object(sf_handler, "get_feed_by_slug", return_value=feed), \
         patch.object(sf_handler, "subscribe", return_value="subscribed"):
        asyncio.run(sf_handler.signals_command(update, ctx))
    assert "Subscribed" in reply.call_args[0][0]


def test_signals_off_unsubscribed_message():
    update, reply = _fake_update_message()
    ctx = _fake_ctx(["off", "alpha"])
    user_ok = {"id": uuid4(), "access_tier": Tier.ALLOWLISTED}
    feed = {"id": _FEED_UUID, "name": "Alpha", "slug": "alpha",
            "status": "active"}
    with patch.object(sf_handler, "upsert_user", return_value=user_ok), \
         patch.object(sf_handler, "get_feed_by_slug", return_value=feed), \
         patch.object(sf_handler, "unsubscribe", return_value=True):
        asyncio.run(sf_handler.signals_command(update, ctx))
    assert "Unsubscribed" in reply.call_args[0][0]


def test_signals_list_no_subs_message():
    update, reply = _fake_update_message()
    ctx = _fake_ctx(["list"])
    user_ok = {"id": uuid4(), "access_tier": Tier.ALLOWLISTED}
    with patch.object(sf_handler, "upsert_user", return_value=user_ok), \
         patch.object(sf_handler, "list_user_subscriptions",
                       return_value=[]):
        asyncio.run(sf_handler.signals_command(update, ctx))
    assert "No active signal subscriptions" in reply.call_args[0][0]


def test_signals_list_with_subs_attaches_keyboard():
    update, reply = _fake_update_message()
    ctx = _fake_ctx(["list"])
    user_ok = {"id": uuid4(), "access_tier": Tier.ALLOWLISTED}
    subs = [{
        "feed_slug": "alpha", "feed_name": "Alpha",
        "subscribed_at": datetime.now(timezone.utc),
    }]
    with patch.object(sf_handler, "upsert_user", return_value=user_ok), \
         patch.object(sf_handler, "list_user_subscriptions",
                       return_value=subs):
        asyncio.run(sf_handler.signals_command(update, ctx))
    kwargs = reply.call_args.kwargs
    assert kwargs.get("reply_markup") is not None


def test_signal_subs_list_kb_one_row_per_subscription():
    kb = signal_subs_list_kb([("alpha", "Alpha"), ("beta", "Beta")])
    assert len(kb.inline_keyboard) == 2
    assert kb.inline_keyboard[0][0].callback_data == "signals:off:alpha"
    assert kb.inline_keyboard[1][0].callback_data == "signals:off:beta"


def test_signal_subs_list_kb_empty_when_no_entries():
    kb = signal_subs_list_kb([])
    assert list(kb.inline_keyboard) == []
