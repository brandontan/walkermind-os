"""Hermetic tests for crypto candle market resolution + settlement.

Root cause covered:
    * Gamma's singular ``conditionId`` filter is IGNORED (returns the default
      market list), so get_market must use ``condition_ids`` AND validate the
      returned row's conditionId — otherwise resolution settled against the
      wrong market and candle positions never closed.
    * Candle up/down markets are not indexed under /markets; they resolve only
      via /events?slug=, with ``outcomePrices`` arriving as a JSON STRING.

No network, no DB, no broker — HTTP + cache + pool are patched.
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from projects.polymarket.crusaderbot.integrations import polymarket as pm
from projects.polymarket.crusaderbot.services.redeem import redeem_router


def _run(coro):
    return asyncio.run(coro)


_GET_JSON = "projects.polymarket.crusaderbot.integrations.polymarket._get_json"
_GET_CACHE = "projects.polymarket.crusaderbot.integrations.polymarket.get_cache"
_SET_CACHE = "projects.polymarket.crusaderbot.integrations.polymarket.set_cache"


# ---------------------------------------------------------------------------
# get_market — condition_ids param + conditionId validation
# ---------------------------------------------------------------------------


def test_get_market_returns_matching_conditionid():
    rows = [{"conditionId": "0xabc", "slug": "real", "closed": True}]
    with patch(_GET_CACHE, new=AsyncMock(return_value=None)), \
         patch(_SET_CACHE, new=AsyncMock()), \
         patch(_GET_JSON, new=AsyncMock(return_value=rows)) as gj:
        out = _run(pm.get_market("0xabc"))
    assert out is not None and out["conditionId"] == "0xabc"
    # Must query the plural condition_ids filter, never the ignored singular form.
    _, kwargs = gj.call_args
    assert kwargs["params"] == {"condition_ids": "0xabc"}


def test_get_market_rejects_mismatched_conditionid():
    # Gamma ignored the filter and returned an unrelated default market.
    rows = [{"conditionId": "0xWRONG", "slug": "rihanna", "closed": False}]
    with patch(_GET_CACHE, new=AsyncMock(return_value=None)), \
         patch(_SET_CACHE, new=AsyncMock()), \
         patch(_GET_JSON, new=AsyncMock(return_value=rows)):
        out = _run(pm.get_market("0xabc"))
    assert out is None


def test_get_market_none_when_empty():
    with patch(_GET_CACHE, new=AsyncMock(return_value=None)), \
         patch(_SET_CACHE, new=AsyncMock()), \
         patch(_GET_JSON, new=AsyncMock(return_value=[])):
        assert _run(pm.get_market("0xabc")) is None


# ---------------------------------------------------------------------------
# get_event_market_by_slug — candle markets live under /events
# ---------------------------------------------------------------------------


def test_get_event_market_by_slug_returns_nested_market():
    slug = "btc-updown-5m-1779623700"
    events = [{"markets": [{"slug": slug, "closed": True,
                            "outcomePrices": '["1", "0"]',
                            "conditionId": "0xea59"}]}]
    with patch(_GET_JSON, new=AsyncMock(return_value=events)):
        out = _run(pm.get_event_market_by_slug(slug))
    assert out is not None and out["slug"] == slug and out["closed"] is True


def test_get_event_market_by_slug_none_when_absent():
    with patch(_GET_JSON, new=AsyncMock(return_value=[])):
        assert _run(pm.get_event_market_by_slug("missing")) is None
    assert _run(pm.get_event_market_by_slug("")) is None


# ---------------------------------------------------------------------------
# _coerce_outcome_prices — JSON-string or list
# ---------------------------------------------------------------------------


def test_coerce_outcome_prices_handles_json_string_and_list():
    assert redeem_router._coerce_outcome_prices('["1", "0"]') == [1.0, 0.0]
    assert redeem_router._coerce_outcome_prices(["0.4", "0.6"]) == [0.4, 0.6]
    assert redeem_router._coerce_outcome_prices("garbage") == []
    assert redeem_router._coerce_outcome_prices(None) == []


# ---------------------------------------------------------------------------
# _process_market_resolution — candle settlement via slug fallback
# ---------------------------------------------------------------------------


class _Conn:
    def __init__(self, rows: list[dict]):
        self._rows = rows
        self.executed: list[str] = []

    async def fetch(self, query, *args):
        return self._rows

    async def execute(self, query, *args):
        self.executed.append(query)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    def transaction(self):
        return self


class _Pool:
    def __init__(self, conn: _Conn):
        self._conn = conn

    def acquire(self):
        return self._conn


def _candle(condition_id: str, prices: str = '["1", "0"]') -> dict:
    return {"closed": True, "conditionId": condition_id, "outcomePrices": prices}


def test_candle_winner_enqueued_and_market_resolved():
    pos = {"id": uuid4(), "user_id": uuid4(), "market_id": "mkt-1", "side": "yes",
           "size_usdc": "5", "entry_price": "0.55", "status": "open",
           "redeemed": False, "telegram_user_id": 1, "auto_redeem_mode": "hourly",
           "condition_id": "mkt-1"}
    conn = _Conn([pos])
    with patch.object(redeem_router.polymarket, "get_market", new=AsyncMock(return_value=None)), \
         patch.object(redeem_router.polymarket, "get_event_market_by_slug",
                      new=AsyncMock(return_value=_candle("mkt-1"))), \
         patch.object(redeem_router, "get_pool", return_value=_Pool(conn)), \
         patch.object(redeem_router, "_enqueue_redeem", new=AsyncMock(return_value=None)) as enq, \
         patch.object(redeem_router, "settle_losing_position", new=AsyncMock()) as lose:
        _run(redeem_router._process_market_resolution("mkt-1", "btc-updown-5m-1"))
    enq.assert_awaited_once()
    lose.assert_not_called()
    assert any("resolved=TRUE" in q for q in conn.executed)


def test_candle_loser_settled_inline():
    pos = {"id": uuid4(), "user_id": uuid4(), "market_id": "mkt-1", "side": "no",
           "size_usdc": "5", "entry_price": "0.55", "status": "open",
           "redeemed": False, "telegram_user_id": 1, "auto_redeem_mode": "hourly",
           "condition_id": "mkt-1"}
    conn = _Conn([pos])
    with patch.object(redeem_router.polymarket, "get_market", new=AsyncMock(return_value=None)), \
         patch.object(redeem_router.polymarket, "get_event_market_by_slug",
                      new=AsyncMock(return_value=_candle("mkt-1"))), \
         patch.object(redeem_router, "get_pool", return_value=_Pool(conn)), \
         patch.object(redeem_router, "_enqueue_redeem", new=AsyncMock(return_value=None)) as enq, \
         patch.object(redeem_router, "settle_losing_position", new=AsyncMock()) as lose:
        _run(redeem_router._process_market_resolution("mkt-1", "btc-updown-5m-1"))
    lose.assert_awaited_once()
    enq.assert_not_called()
    assert any("resolved=TRUE" in q for q in conn.executed)


def test_candle_conditionid_mismatch_routes_to_pending():
    # Event lookup returns a market whose conditionId does NOT match -> never settle.
    with patch.object(redeem_router.polymarket, "get_market", new=AsyncMock(return_value=None)), \
         patch.object(redeem_router.polymarket, "get_event_market_by_slug",
                      new=AsyncMock(return_value=_candle("0xWRONG"))), \
         patch.object(redeem_router, "_mark_pending_settlement", new=AsyncMock()) as mark, \
         patch.object(redeem_router, "settle_losing_position", new=AsyncMock()) as lose:
        _run(redeem_router._process_market_resolution("mkt-1", "btc-updown-5m-1"))
    mark.assert_awaited_once_with("mkt-1")
    lose.assert_not_called()
