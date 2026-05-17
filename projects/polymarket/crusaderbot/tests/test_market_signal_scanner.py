"""Hermetic tests for market_signal_scanner — edge scoring and market filters.

Covers: demo path signal conditions (edge_bps threshold, price range, liquidity).
No DB, no HTTP, no broker. Pool + Gamma API + settings patched at module boundary.
"""
from __future__ import annotations

import asyncio
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from projects.polymarket.crusaderbot.jobs import market_signal_scanner as scanner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_CFG = SimpleNamespace(
    SCANNER_EDGE_MIN_PRICE=0.05,
    SCANNER_EDGE_MAX_PRICE=0.95,
    SCANNER_MIN_EDGE_BPS=200,
    SCANNER_MIN_CONFIDENCE=0.55,
    SCANNER_EDGE_DEVIATION_PCT=0.05,
    SCANNER_MIN_LIQUIDITY=5_000.0,
)


def _make_market(*, liquidity: float, yes_price: float = 0.30) -> dict:
    return {
        "conditionId": "mkt-test-001",
        "question": "Will Austria win the 2026 FIFA World Cup?",
        "liquidity": liquidity,
        "outcomePrices": [str(yes_price), str(round(1.0 - yes_price, 4))],
        "closed": False,
        "resolved": False,
    }


def _make_pool():
    """Fake asyncpg pool that satisfies the demo-feed active check."""
    conn = MagicMock()
    conn.fetchrow = AsyncMock(
        return_value={
            "id": "feed-demo",
            "feed_name": "DEMO",
            "is_active": True,
        }
    )
    conn.fetchval = AsyncMock(return_value=False)  # _already_published → False
    conn.execute = AsyncMock()
    conn.transaction = MagicMock(return_value=_ctx_mgr())
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_acquire_ctx(conn))
    return pool


def _ctx_mgr():
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=None)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _acquire_ctx(conn):
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _run(market: dict, cfg=None) -> list:
    """Run one scanner tick with a single market. Returns list of _publish calls."""
    published_calls: list = []

    async def _fake_publish(*args, **kwargs):
        published_calls.append(args)

    async def _fake_already_published(*args, **kwargs):
        return False

    async def _fake_heisenberg():
        return 0, 0

    pool = _make_pool()
    with (
        patch.object(scanner, "get_settings", return_value=(cfg or _FAKE_CFG)),
        patch.object(scanner, "get_pool", return_value=pool),
        patch.object(
            scanner.polymarket,
            "get_markets",
            new=AsyncMock(return_value=[market]),
        ),
        patch.object(scanner, "_publish", side_effect=_fake_publish),
        patch.object(
            scanner, "_already_published", side_effect=_fake_already_published
        ),
        patch.object(
            scanner, "_run_heisenberg_signals", side_effect=_fake_heisenberg
        ),
    ):
        asyncio.run(scanner.run_job())

    return published_calls


# ---------------------------------------------------------------------------
# Tests — market pool filters
# ---------------------------------------------------------------------------


def test_demo_skips_markets_below_min_liquidity():
    """Markets below SCANNER_MIN_LIQUIDITY (5_000) must produce no signal."""
    low_liq_market = _make_market(liquidity=4_999, yes_price=0.30)
    assert _run(low_liq_market) == []


def test_demo_includes_markets_at_min_liquidity():
    """Markets at exactly SCANNER_MIN_LIQUIDITY (5_000) pass the filter."""
    market = _make_market(liquidity=5_000, yes_price=0.30)
    # YES=0.30 → edge_bps=2000 ≥ 200 → should publish
    assert len(_run(market)) == 1


def test_demo_rejects_near_resolved_markets():
    """Markets with YES price below SCANNER_EDGE_MIN_PRICE (0.05) are excluded."""
    near_resolved = _make_market(liquidity=50_000, yes_price=0.01)
    assert _run(near_resolved) == []


def test_demo_rejects_near_resolved_markets_high():
    """Markets with YES price above SCANNER_EDGE_MAX_PRICE (0.95) are excluded."""
    near_resolved = _make_market(liquidity=50_000, yes_price=0.97)
    assert _run(near_resolved) == []


def test_demo_rejects_insufficient_edge():
    """Markets with edge below MIN_EDGE_BPS (200 bps = 2%) are skipped."""
    # YES=0.49 → edge = abs(0.49 - 0.50) = 0.01 → edge_bps = 100 < 200
    low_edge_market = _make_market(liquidity=20_000, yes_price=0.49)
    assert _run(low_edge_market) == []


def test_demo_scans_mid_priced_markets():
    """Markets with valid mid-range prices generate signals when edge ≥ MIN_EDGE_BPS."""
    # YES=0.30 → edge = 0.20 → edge_bps = 2000 ≥ 200 → APPROVED
    mid_market = _make_market(liquidity=15_000, yes_price=0.30)
    calls = _run(mid_market)
    assert len(calls) == 1


def test_demo_side_is_yes_when_yes_price_below_fair():
    """YES price below 0.50 → YES signal (underpriced YES)."""
    market = _make_market(liquidity=20_000, yes_price=0.30)
    calls = _run(market)
    assert len(calls) == 1
    # args: (feed_id, market_id, side, price, sig_type, payload, is_demo)
    assert calls[0][2] == "YES"


def test_demo_side_is_no_when_yes_price_above_fair():
    """YES price above 0.50 → NO signal (underpriced NO)."""
    market = _make_market(liquidity=20_000, yes_price=0.72)
    calls = _run(market)
    assert len(calls) == 1
    assert calls[0][2] == "NO"


def test_demo_edge_bps_logged_in_payload():
    """Published payload includes edge_bps for monitoring."""
    market = _make_market(liquidity=20_000, yes_price=0.30)
    calls = _run(market)
    assert len(calls) == 1
    payload = calls[0][5]
    assert "edge_bps" in payload
    assert payload["edge_bps"] == 2000  # abs(0.30 - 0.50) * 10_000


# ---------------------------------------------------------------------------
# Tests — backward compat
# ---------------------------------------------------------------------------


def test_min_liquidity_constant_is_10k():
    """Regression guard: module-level MIN_LIQUIDITY constant preserved at 10_000."""
    assert scanner.MIN_LIQUIDITY == 10_000.0


def test_edge_price_threshold_constant_preserved():
    """Regression guard: EDGE_PRICE_THRESHOLD constant still exists for test mocks."""
    assert scanner.EDGE_PRICE_THRESHOLD == 0.15
