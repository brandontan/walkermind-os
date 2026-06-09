"""Incident hardening for the 2026-05-29 candle-sync silent outage.

get_crypto_window_markets fed the close_sweep/safe_close/flip_hunter scanner.
A persistent /events fetch failure made it return [] while logging only at
DEBUG, so the bot placed zero candle trades for ~14h with no operator signal.
These tests pin: (1) errors now surface at WARNING, (2) the all-empty-due-to-
errors case is logged loudly, (3) the cache TTL was widened to ease polling,
(4) the happy path still returns markets tagged category=crypto.
"""
from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock

from projects.polymarket.crusaderbot.integrations import polymarket as pm


def test_cache_ttl_widened_to_reduce_events_polling():
    assert pm._CRYPTO_WINDOW_CACHE_TTL >= 45


def test_error_path_logs_warning_not_debug():
    src = inspect.getsource(pm.get_crypto_window_markets)
    assert 'log.warning(' in src and "slug fetch failed" in src
    # the old silent debug line must be gone
    assert 'log.debug("get_crypto_window_markets failed"' not in src
    assert "all candle fetches failed" in src  # loud all-empty signal


def test_all_fetch_errors_returns_empty(monkeypatch):
    monkeypatch.setattr(pm, "get_cache", AsyncMock(return_value=None))
    monkeypatch.setattr(pm, "set_cache", AsyncMock(return_value=None))

    async def boom(url, params=None):
        raise RuntimeError("429 rate limited")
    monkeypatch.setattr(pm, "_get_json", boom)

    out = asyncio.run(pm.get_crypto_window_markets("5m", ["btc"], include_next=False))
    assert out == []


def test_success_returns_crypto_tagged_markets(monkeypatch):
    monkeypatch.setattr(pm, "get_cache", AsyncMock(return_value=None))
    monkeypatch.setattr(pm, "set_cache", AsyncMock(return_value=None))

    async def ok(url, params=None):
        return [{"markets": [{"id": "m1", "conditionId": "c1"}]}]
    monkeypatch.setattr(pm, "_get_json", ok)

    out = asyncio.run(pm.get_crypto_window_markets("5m", ["btc"], include_next=False))
    assert out and out[0]["category"] == "crypto" and out[0]["id"] == "m1"
