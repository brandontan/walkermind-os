"""Hermetic tests for Lane 1 category-mapping fix.

Tests:
  - get_events_with_markets() annotates market dicts with event tag categories
  - _filter_markets_by_category() correctly matches dashboard categories on
    annotated market dicts (crypto, sports, politics, multi-tag events)
  - _fetch_markets_for_lib_strategies() uses get_events_with_markets()

No DB, no real HTTP. Gamma API patched at integration boundary.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from projects.polymarket.crusaderbot.integrations import polymarket as pm_module
from projects.polymarket.crusaderbot.services.signal_scan.signal_scan_job import (
    _filter_markets_by_category,
    _fetch_markets_for_lib_strategies,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _event(*, title: str, tags: list[str], markets: list[dict],
           category: str | None = None) -> dict:
    """Build a minimal Gamma event dict."""
    return {
        "id": title,
        "title": title,
        "category": category,
        "tags": [
            {"id": str(i), "label": t, "slug": t.lower().replace(" ", "-"),
             "forceShow": True}
            for i, t in enumerate(tags)
        ] + [{"id": "all", "label": "All", "slug": "all", "forceShow": False}],
        "markets": markets,
    }


def _market(question: str = "test?") -> dict:
    """Minimal Gamma market object (as returned inside event.markets)."""
    return {
        "id": question[:20],
        "conditionId": f"0x{question[:8]}",
        "question": question,
        "slug": question[:15].lower().replace(" ", "-"),
        "endDate": "2026-06-01T00:00:00Z",
        "outcomePrices": ["0.5", "0.5"],
        "liquidity": 10_000,
        "active": True,
        "closed": False,
    }


# ---------------------------------------------------------------------------
# get_events_with_markets() — annotation behaviour
# ---------------------------------------------------------------------------

def _run_get_events(events: list[dict]) -> list[dict]:
    """Invoke get_events_with_markets() with patched HTTP and cache."""
    async def _go():
        with (
            patch.object(pm_module, "_get_json", new=AsyncMock(return_value=events)),
            patch.object(pm_module, "get_cache", new=AsyncMock(return_value=None)),
            patch.object(pm_module, "set_cache", new=AsyncMock()),
        ):
            return await pm_module.get_events_with_markets(limit=10)
    return asyncio.run(_go())


def test_annotates_market_with_event_tags():
    """Each market in the output carries category derived from parent event tags."""
    events = [_event(title="BTC price", tags=["Crypto", "Finance"], markets=[_market("BTC $100k?")])]
    result = _run_get_events(events)
    assert len(result) == 1
    assert "crypto" in result[0]["category"]
    assert "finance" in result[0]["category"]


def test_all_tag_excluded_from_category():
    """The generic 'All' tag must not appear in the category string."""
    events = [_event(title="US Election", tags=["Politics"], markets=[_market("Biden wins?")])]
    result = _run_get_events(events)
    assert "all" not in result[0]["category"]
    assert "politics" in result[0]["category"]


def test_multi_market_event_all_annotated():
    """All markets within an event receive the same category annotation."""
    mkts = [_market(f"Q{i}?") for i in range(3)]
    events = [_event(title="NBA Finals", tags=["Sports"], markets=mkts)]
    result = _run_get_events(events)
    assert len(result) == 3
    for m in result:
        assert "sports" in m["category"]


def test_multi_event_flattens_correctly():
    """Markets from different events are all included in the output."""
    events = [
        _event(title="BTC $100k", tags=["Crypto"], markets=[_market("BTC?")]),
        _event(title="Trump policy", tags=["Politics"], markets=[_market("Trump?"), _market("Biden?")]),
    ]
    result = _run_get_events(events)
    assert len(result) == 3
    categories = [m["category"] for m in result]
    assert any("crypto" in c for c in categories)
    assert any("politics" in c for c in categories)


def test_fallback_to_event_category_when_no_tags():
    """When an event has no tags (only 'All'), fall back to event.category field."""
    event = {
        "id": "misc",
        "title": "Random event",
        "category": "Sports",
        "tags": [{"id": "all", "label": "All", "slug": "all", "forceShow": False}],
        "markets": [_market("test?")],
    }
    result = _run_get_events([event])
    assert len(result) == 1
    assert "sports" in result[0]["category"]


def test_empty_event_markets_skipped():
    """Events with no markets contribute zero market dicts to the output."""
    events = [
        _event(title="NoMarkets", tags=["Crypto"], markets=[]),
        _event(title="HasMarkets", tags=["Sports"], markets=[_market("Q?")]),
    ]
    result = _run_get_events(events)
    assert len(result) == 1
    assert "sports" in result[0]["category"]


def test_http_failure_returns_empty_list():
    """A network error in get_events_with_markets() returns [] gracefully."""
    async def _go():
        with (
            patch.object(pm_module, "_get_json", new=AsyncMock(side_effect=Exception("network"))),
            patch.object(pm_module, "get_cache", new=AsyncMock(return_value=None)),
            patch.object(pm_module, "set_cache", new=AsyncMock()),
        ):
            return await pm_module.get_events_with_markets(limit=10)
    result = asyncio.run(_go())
    assert result == []


# ---------------------------------------------------------------------------
# _filter_markets_by_category — with annotated markets (integration check)
# ---------------------------------------------------------------------------

def test_filter_crypto_matches_annotated_market():
    """Annotated market with 'crypto finance' category passes 'crypto' filter."""
    m = {**_market("BTC?"), "category": "crypto finance business"}
    assert _filter_markets_by_category([m], ["crypto"]) == [m]


def test_filter_sports_rejects_crypto_market():
    """'sports' filter rejects a market with 'crypto finance' category."""
    m = {**_market("BTC?"), "category": "crypto finance business"}
    assert _filter_markets_by_category([m], ["sports"]) == []


def test_filter_politics_matches_annotated_market():
    """'politics' filter matches a market annotated with 'politics world' category."""
    m = {**_market("Election?"), "category": "politics world 2026 predictions"}
    assert _filter_markets_by_category([m], ["politics"]) == [m]


def test_filter_multi_tag_event_matches_multiple_filters():
    """A market with 'crypto finance' matches either 'crypto' or 'finance' filter."""
    m = {**_market("ETH?"), "category": "crypto finance tech"}
    assert len(_filter_markets_by_category([m], ["crypto"])) == 1
    assert len(_filter_markets_by_category([m], ["finance"])) == 1
    assert len(_filter_markets_by_category([m], ["crypto", "sports"])) == 1


# ---------------------------------------------------------------------------
# _fetch_markets_for_lib_strategies — calls get_events_with_markets
# ---------------------------------------------------------------------------

def test_fetch_markets_calls_get_events_with_markets():
    """_fetch_markets_for_lib_strategies() must use get_events_with_markets()."""
    fake_markets = [{**_market("BTC?"), "category": "crypto"}]

    async def _go():
        with patch.object(
            pm_module, "get_events_with_markets",
            new=AsyncMock(return_value=fake_markets),
        ):
            return await _fetch_markets_for_lib_strategies()

    # Patch the _polymarket module reference inside signal_scan_job
    import projects.polymarket.crusaderbot.services.signal_scan.signal_scan_job as job_mod
    original = job_mod._polymarket
    job_mod._polymarket = pm_module
    try:
        result = asyncio.run(_go())
    finally:
        job_mod._polymarket = original

    assert result == fake_markets


def test_fetch_markets_returns_empty_on_failure():
    """_fetch_markets_for_lib_strategies() returns [] when get_events_with_markets fails."""
    async def _go():
        with patch.object(
            pm_module, "get_events_with_markets",
            new=AsyncMock(side_effect=Exception("fail")),
        ):
            return await _fetch_markets_for_lib_strategies()

    import projects.polymarket.crusaderbot.services.signal_scan.signal_scan_job as job_mod
    original = job_mod._polymarket
    job_mod._polymarket = pm_module
    try:
        result = asyncio.run(_go())
    finally:
        job_mod._polymarket = original

    assert result == []
