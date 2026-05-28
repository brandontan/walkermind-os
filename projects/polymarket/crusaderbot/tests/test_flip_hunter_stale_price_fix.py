"""Regression: flip-hunter Gamma-fallback stale-price bug.

Root cause (2026-05-28): get_live_market_price's Gamma `outcomePrices`
fallback returned sub-cent values (0.505 / 0.515) that are not on the
Polymarket CLOB 0.01 tick. Fresh 5m crypto candle markets opened with
these seed/midpoint values and Flip Hunter's early-window scan fired
identical trades across BTC/ETH/SOL/XRP/DOGE/BNB simultaneously — 72/86
positions @ exactly 0.505. The synthetic TP fill (entry × 1.15) closed
them at the identical 0.58075 for fake +$0.50 wins on the paper wallet.

Fix: reject sub-cent prices in two layers:
  1. `integrations.polymarket.get_live_market_price` — Gamma fallback
     never returns a sub-cent value.
  2. `services.signal_scan.signal_scan_job._process_candidate` —
     belt-and-suspenders: any non-tick live price skips the trade
     (`outcome="skipped_sub_cent_price"`).
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from projects.polymarket.crusaderbot.integrations import polymarket as pm


# ---------------------------------------------------------------------
# Layer 1 — get_live_market_price rejects sub-cent Gamma fallback
# ---------------------------------------------------------------------

def _run(coro):
    return asyncio.run(coro)


def _cache_clear():
    # No persistent cache mock — patch get_cache/set_cache directly.
    pass


@pytest.fixture
def _patch_cache_miss(monkeypatch):
    """Force cache miss + benign cache writes so _get_json runs."""
    async def _miss(key):
        return None

    async def _set(key, val, ttl=30):
        return None

    monkeypatch.setattr(pm, "get_cache", _miss)
    monkeypatch.setattr(pm, "set_cache", _set)


def test_gamma_fallback_rejects_sub_cent_yes(_patch_cache_miss, monkeypatch):
    """Gamma outcomePrices ["0.505","0.495"] must return None (sub-cent)."""
    market_id = "0xabc"
    market_data = {
        "conditionId": market_id,
        "tokens": [{"token_id": "tok_yes"}, {"token_id": "tok_no"}],
        "outcomePrices": '["0.505","0.495"]',
    }

    async def _get_json(url, params=None, timeout=5.0):
        # Gamma /markets returns market_data; CLOB /price returns the
        # empty-book sentinel so the helper falls through to Gamma.
        if "gamma" in url or "/markets" in url:
            return [market_data]
        if "/price" in url:
            return {"price": "1.0"}  # empty-ask sentinel
        return {}

    monkeypatch.setattr(pm, "_get_json", _get_json)

    price = _run(pm.get_live_market_price(market_id, "yes"))
    assert price is None, (
        f"Sub-cent Gamma fallback (0.505) must be rejected, got {price}. "
        "Regression: flip_hunter would trade on stale seed prices."
    )


def test_gamma_fallback_rejects_sub_cent_no(_patch_cache_miss, monkeypatch):
    """Same guard on the NO side — 0.515 outcomePrices for NO must reject."""
    market_id = "0xabc"
    market_data = {
        "conditionId": market_id,
        "tokens": [{"token_id": "tok_yes"}, {"token_id": "tok_no"}],
        "outcomePrices": '["0.485","0.515"]',
    }

    async def _get_json(url, params=None, timeout=5.0):
        if "/markets" in url:
            return [market_data]
        if "/price" in url:
            return {"price": "1.0"}
        return {}

    monkeypatch.setattr(pm, "_get_json", _get_json)
    assert _run(pm.get_live_market_price(market_id, "no")) is None


def test_gamma_fallback_accepts_tick_aligned_price(_patch_cache_miss, monkeypatch):
    """A Gamma outcomePrice that IS on the 1¢ tick (0.51) must still flow through."""
    market_id = "0xabc"
    market_data = {
        "conditionId": market_id,
        "tokens": [{"token_id": "tok_yes"}, {"token_id": "tok_no"}],
        "outcomePrices": '["0.510","0.490"]',
    }

    async def _get_json(url, params=None, timeout=5.0):
        if "/markets" in url:
            return [market_data]
        if "/price" in url:
            return {"price": "1.0"}
        return {}

    monkeypatch.setattr(pm, "_get_json", _get_json)
    price = _run(pm.get_live_market_price(market_id, "yes"))
    assert price == pytest.approx(0.510, abs=1e-9)


def test_clob_real_price_short_circuits_gamma(_patch_cache_miss, monkeypatch):
    """When CLOB /price returns a strictly-interior real value, the helper
    returns it without ever falling through to the Gamma path. Sub-cent
    rejection therefore does NOT block real CLOB activity.
    """
    market_id = "0xabc"
    market_data = {
        "conditionId": market_id,
        "tokens": [{"token_id": "tok_yes"}, {"token_id": "tok_no"}],
        "outcomePrices": '["0.505","0.495"]',  # would be rejected if we fell through
    }

    async def _get_json(url, params=None, timeout=5.0):
        if "/markets" in url:
            return [market_data]
        if "/price" in url:
            return {"price": "0.62"}  # real CLOB ask
        return {}

    monkeypatch.setattr(pm, "_get_json", _get_json)
    assert _run(pm.get_live_market_price(market_id, "yes")) == pytest.approx(0.62)


# ---------------------------------------------------------------------
# Layer 2 — signal_scan_job._process_candidate skip on sub-cent price
# ---------------------------------------------------------------------

def test_signal_scan_job_has_sub_cent_guard():
    """Source-level pin: _process_candidate must contain the
    `skipped_sub_cent_price` outcome path so a future edit that drops
    the guard fails this test.
    """
    import inspect
    from projects.polymarket.crusaderbot.services.signal_scan import (
        signal_scan_job as ssj,
    )
    src = inspect.getsource(ssj._process_candidate)
    assert "skipped_sub_cent_price" in src, (
        "Regression: _process_candidate lost its sub-cent guard — "
        "flip_hunter would re-fire on stale Gamma seed prices."
    )
    # The check must compare against the 0.01 tick.
    assert "100" in src and ("round" in src or "abs(" in src), (
        "Regression: sub-cent guard logic is missing the tick comparison."
    )


# ---------------------------------------------------------------------
# Mathematical fingerprint of the bug
# ---------------------------------------------------------------------

@pytest.mark.parametrize("sub_cent", [0.505, 0.515, 0.525, 0.575, 0.625])
def test_sub_cent_detection(sub_cent):
    """The check used in both layers: abs(price*100 - round(price*100)) > 1e-6
    detects any value that is not a whole cent.
    """
    cents = sub_cent * 100.0
    assert abs(cents - round(cents)) > 1e-6


@pytest.mark.parametrize("tick", [0.50, 0.51, 0.52, 0.60, 0.95])
def test_tick_aligned_passes(tick):
    """Whole-cent values must NOT trigger the sub-cent guard."""
    cents = tick * 100.0
    assert abs(cents - round(cents)) <= 1e-6
