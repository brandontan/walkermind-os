"""WARP•R00T no-fake-data regression: copy-trade never fabricates price/liquidity.

The copy-trade monitor previously returned a hardcoded 0.50 price and 50_000
liquidity when a leader-trade payload omitted them — fabricated values that
booked a fake entry and could bypass the risk gate's liquidity floor. The
honest behaviour: extract returns None when absent, the monitor sources the
real live CLOB book (mid + two-sided depth), and SKIPS the mirror entirely if
there is no real interior two-sided mark. The legacy scan path likewise skips a
priceless leader trade instead of seeding 0.50.
"""
from __future__ import annotations

import asyncio

import pytest
from unittest.mock import AsyncMock, patch

from projects.polymarket.crusaderbot.services.copy_trade import monitor as cm


# --------------------------------------------------------------- extract helpers


def test_extract_price_returns_none_when_absent_or_non_interior():
    assert cm._extract_price({}, "yes") is None
    assert cm._extract_price({"price": "0.0"}, "yes") is None      # sentinel rejected
    assert cm._extract_price({"price": "1.0"}, "yes") is None      # sentinel rejected
    assert cm._extract_price({"price": "0.42"}, "yes") == pytest.approx(0.42)
    assert cm._extract_price({"avgPrice": "0.61"}, "no") == pytest.approx(0.61)


def test_extract_liquidity_returns_none_when_absent():
    assert cm._extract_liquidity({}) is None                       # no fabricated 50k
    assert cm._extract_liquidity({"liquidity": "1234"}) == pytest.approx(1234.0)
    assert cm._extract_liquidity({"volume": "9999"}) == pytest.approx(9999.0)


# ------------------------------------------------------------- live book resolver


def _run_book(book, token="tok"):
    async def _go():
        with patch.object(cm, "get_book", new=AsyncMock(return_value=book)):
            return await cm._live_book_mark_and_depth(token)
    return asyncio.run(_go())


def test_live_book_resolver_real_two_sided():
    book = {
        "bids": [{"price": "0.40", "size": "100"}],
        "asks": [{"price": "0.44", "size": "100"}],
    }
    mid, depth = _run_book(book)
    assert round(mid, 4) == 0.42       # (0.40 + 0.44) / 2
    assert depth and depth > 0


def test_live_book_resolver_rejects_degenerate():
    assert _run_book({"bids": [], "asks": [{"price": "0.4", "size": "1"}]}) == (None, None)
    assert _run_book({"bids": [{"price": "0.4", "size": "1"}], "asks": []}) == (None, None)
    # crossed (best_bid > best_ask)
    assert _run_book(
        {"bids": [{"price": "0.6", "size": "1"}], "asks": [{"price": "0.4", "size": "1"}]}
    ) == (None, None)
    # missing token short-circuits before any fetch
    assert _run_book({"bids": [{"price": "0.4", "size": "1"}],
                      "asks": [{"price": "0.5", "size": "1"}]}, token=None) == (None, None)


def test_live_book_resolver_fail_soft_on_fetch_error():
    async def _go():
        with patch.object(cm, "get_book", new=AsyncMock(side_effect=RuntimeError("boom"))):
            return await cm._live_book_mark_and_depth("tok")
    assert asyncio.run(_go()) == (None, None)
