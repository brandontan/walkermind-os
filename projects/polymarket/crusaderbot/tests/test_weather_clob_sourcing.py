"""Hermetic tests for weather real-CLOB price sourcing.

WARP/ROOT/strategy-real-clob-sourcing — owner directive: no fake data. The
weather feed previously emitted Gamma's 0.50/0.50 placeholder price + $0
liquidity, so the strategy rejected genuinely-priced markets at the >0.45 price
gate. fetch_weather_markets now prices each market from the real CLOB book (or
the real Gamma price when present) and SKIPS any market it cannot price
honestly — it must never emit a fabricated 0.50.

No network: the CLOB book fetch is injected.
"""
from __future__ import annotations

import asyncio

from projects.polymarket.crusaderbot.strategies.weather.market import (
    _book_quote,
    _build_weather_markets,
    _extract_yes_token,
    _parse_gamma_outcomes,
)


# --------------------------------------------------------------------------- _book_quote


def test_book_quote_two_sided():
    book = {
        "bids": [{"price": "0.40", "size": "100"}, {"price": "0.42", "size": "50"}],
        "asks": [{"price": "0.43", "size": "60"}, {"price": "0.45", "size": "10"}],
    }
    mid, spread, depth = _book_quote(book)
    assert round(mid, 4) == 0.425          # (0.42 best bid + 0.43 best ask)/2
    assert round(spread, 4) == 0.01        # 0.43 - 0.42
    assert depth > 0


def test_book_quote_one_sided_or_empty_returns_none():
    assert _book_quote({"bids": [], "asks": [{"price": "0.4", "size": "1"}]}) == (None, None, 0.0)
    assert _book_quote({"bids": [{"price": "0.4", "size": "1"}], "asks": []}) == (None, None, 0.0)
    assert _book_quote({}) == (None, None, 0.0)
    assert _book_quote(None) == (None, None, 0.0)


def test_book_quote_crossed_or_degenerate_rejected():
    # best_bid > best_ask (crossed) -> not a usable quote
    crossed = {"bids": [{"price": "0.6", "size": "1"}], "asks": [{"price": "0.4", "size": "1"}]}
    assert _book_quote(crossed) == (None, None, 0.0)


# --------------------------------------------------------------------------- gamma price parse


def test_parse_gamma_outcomes_real_vs_placeholder():
    assert _parse_gamma_outcomes({"outcomePrices": ["0.42", "0.58"]}) == (0.42, 0.58)
    # 0.50/0.50 placeholder -> no real price
    assert _parse_gamma_outcomes({"outcomePrices": ["0.5", "0.5"]}) == (None, None)
    # JSON-string form
    assert _parse_gamma_outcomes({"outcomePrices": "[\"0.3\", \"0.7\"]"}) == (0.3, 0.7)
    # missing / malformed
    assert _parse_gamma_outcomes({}) == (None, None)
    assert _parse_gamma_outcomes({"outcomePrices": ["x"]}) == (None, None)


def test_extract_yes_token():
    assert _extract_yes_token({"clobTokenIds": ["tokA", "tokB"]}) == "tokA"
    assert _extract_yes_token({"clobTokenIds": "[\"tokA\", \"tokB\"]"}) == "tokA"
    assert _extract_yes_token({}) is None


# --------------------------------------------------------------------------- _build_weather_markets


def _q(city, deg):
    return f"Will the highest temperature in {city} be {deg}°C or higher"


def test_build_skips_unpriceable_never_emits_fake_050():
    # Real Gamma price -> kept, no book fetch needed.
    real_gamma = {"id": "1", "question": _q("Tokyo", 30), "outcomePrices": ["0.42", "0.58"],
                  "clobTokenIds": ["t1", "t1b"], "endDate": "2026-06-05T00:00:00Z"}
    # Placeholder + real CLOB book -> priced from the book.
    placeholder_book = {"id": "2", "question": _q("Jeddah", 37), "outcomePrices": ["0.5", "0.5"],
                        "clobTokenIds": ["t2", "t2b"], "endDate": "2026-06-05T00:00:00Z"}
    # Placeholder + empty book -> SKIPPED (no fake 0.50).
    placeholder_nobook = {"id": "3", "question": _q("Karachi", 28), "outcomePrices": ["0.5", "0.5"],
                          "clobTokenIds": ["t3", "t3b"], "endDate": "2026-06-05T00:00:00Z"}
    # Not a weather market -> skipped.
    not_weather = {"id": "4", "question": "Will BTC be above 100k", "outcomePrices": ["0.3", "0.7"],
                   "clobTokenIds": ["t4", "t4b"]}

    books = {
        "t2": {"bids": [{"price": "0.40", "size": "100"}], "asks": [{"price": "0.44", "size": "100"}]},
        "t3": {"bids": [], "asks": []},
    }

    async def fake_book(token):
        return books.get(token, {"bids": [], "asks": []})

    rows = [real_gamma, placeholder_book, placeholder_nobook, not_weather]
    out = asyncio.run(_build_weather_markets(rows, None, fake_book))

    by_id = {m.market_id: m for m in out}
    assert set(by_id) == {"1", "2"}                 # 3 (no book) + 4 (non-weather) dropped
    assert by_id["1"].yes_price == 0.42             # real Gamma price preserved
    assert round(by_id["2"].yes_price, 4) == 0.42   # (0.40+0.44)/2 from the CLOB book
    assert round(by_id["2"].no_price, 4) == 0.58
    # The core invariant: no emitted market carries the fabricated 0.50 placeholder.
    assert all(abs(m.yes_price - 0.5) > 1e-9 for m in out)


def test_build_respects_city_filter():
    rows = [
        {"id": "1", "question": _q("Tokyo", 30), "outcomePrices": ["0.42", "0.58"], "clobTokenIds": ["t1", "t1b"]},
        {"id": "2", "question": _q("Jeddah", 37), "outcomePrices": ["0.42", "0.58"], "clobTokenIds": ["t2", "t2b"]},
    ]

    async def fake_book(token):
        return {"bids": [], "asks": []}

    out = asyncio.run(_build_weather_markets(rows, "tokyo", fake_book))
    assert [m.market_id for m in out] == ["1"]
