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
    SCANNER_EDGE_MIN_PRICE=0.15,
    SCANNER_EDGE_MAX_PRICE=0.85,
    SCANNER_MIN_EDGE_BPS=200,
    SCANNER_MIN_CONFIDENCE=0.55,
    SCANNER_EDGE_DEVIATION_PCT=0.05,
    SCANNER_MIN_LIQUIDITY=5_000.0,
    SCANNER_MARKET_FETCH_LIMIT=500,
    SCANNER_MAX_RESOLUTION_DAYS=30,
    SCANNER_DEMO_FEED_ENABLED=False,
)


def _make_market(
    *,
    liquidity: float,
    yes_price: float = 0.30,
    day_change: float = 0.20,
    hour_change: float = 0.0,
) -> dict:
    return {
        "conditionId": "mkt-test-001",
        "question": "Will Austria win the 2026 FIFA World Cup?",
        "liquidity": liquidity,
        "outcomePrices": [str(yes_price), str(round(1.0 - yes_price, 4))],
        "closed": False,
        "resolved": False,
        "oneDayPriceChange": day_change,
        "oneHourPriceChange": hour_change if hour_change != 0.0 else None,
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
            scanner._ops_kill_switch, "is_active", new=AsyncMock(return_value=False)
        ),
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
    """Markets with no recent price movement (zero momentum) are rejected."""
    # YES=0.49, both price changes zero → edge = 0 → edge_bps = 0 < 200
    no_change_market = _make_market(liquidity=20_000, yes_price=0.49, day_change=0.0, hour_change=0.0)
    assert _run(no_change_market) == []


def test_demo_scans_mid_priced_markets():
    """Active mid-range markets (≥ 2% daily momentum) generate signals."""
    # YES=0.30, day_change=0.10 → edge = 0.10 → edge_bps = 1000 ≥ 200 → APPROVED
    mid_market = _make_market(liquidity=15_000, yes_price=0.30, day_change=0.10)
    calls = _run(mid_market)
    assert len(calls) == 1


def test_demo_side_follows_upward_momentum():
    """Positive price momentum → YES signal."""
    market = _make_market(liquidity=20_000, yes_price=0.30, day_change=0.08, hour_change=0.03)
    calls = _run(market)
    assert len(calls) == 1
    # args: (feed_id, market_id, side, price, sig_type, payload, is_demo)
    assert calls[0][2] == "YES"


def test_demo_side_follows_downward_momentum():
    """Negative price momentum → NO signal."""
    market = _make_market(liquidity=20_000, yes_price=0.72, day_change=-0.08, hour_change=-0.03)
    calls = _run(market)
    assert len(calls) == 1
    assert calls[0][2] == "NO"


def test_demo_edge_bps_logged_in_payload():
    """Published payload includes edge_bps derived from momentum, not distance-from-0.5."""
    # day_change=0.20, hour_change=None → edge = max(0.20, 0) = 0.20 → 2000 bps
    market = _make_market(liquidity=20_000, yes_price=0.30, day_change=0.20)
    calls = _run(market)
    assert len(calls) == 1
    payload = calls[0][5]
    assert "edge_bps" in payload
    assert payload["edge_bps"] == 2000  # max(abs(0.20), abs(0)*1.5) * 10_000


# ---------------------------------------------------------------------------
# Tests — feed routing (real vs demo)
# ---------------------------------------------------------------------------


def test_production_routes_to_live_feed_with_is_demo_false():
    """Default (SCANNER_DEMO_FEED_ENABLED off) publishes real markets to the
    LIVE feed with is_demo=False so paper users trade officially-resolvable
    markets."""
    market = _make_market(liquidity=20_000, yes_price=0.30)
    calls = _run(market)  # _FAKE_CFG has the flag off
    assert len(calls) == 1
    assert calls[0][0] == scanner.LIVE_FEED_ID  # feed_id
    assert calls[0][6] is False                  # is_demo


def test_demo_flag_routes_to_demo_feed_with_is_demo_true():
    """SCANNER_DEMO_FEED_ENABLED on (hermetic tests / dev) publishes synthetic
    is_demo=True rows to the demo feed."""
    cfg = SimpleNamespace(**{**vars(_FAKE_CFG), "SCANNER_DEMO_FEED_ENABLED": True})
    market = _make_market(liquidity=20_000, yes_price=0.30)
    calls = _run(market, cfg=cfg)
    assert len(calls) == 1
    assert calls[0][0] == scanner.DEMO_FEED_ID   # feed_id
    assert calls[0][6] is True                   # is_demo


# ---------------------------------------------------------------------------
# Tests — tighter price range (Lane 3 longshot guard)
# ---------------------------------------------------------------------------


def test_demo_rejects_longshot_price_below_015():
    """YES price below 0.15 (extreme longshot) is rejected with tightened range."""
    extreme_low = _make_market(liquidity=50_000, yes_price=0.10, day_change=0.30)
    assert _run(extreme_low) == []


def test_demo_rejects_near_certain_price_above_085():
    """YES price above 0.85 (near-certain) is rejected with tightened range."""
    near_certain = _make_market(liquidity=50_000, yes_price=0.90, day_change=0.30)
    assert _run(near_certain) == []


def test_demo_near_fair_passes_with_momentum():
    """A market near 0.50 YES but with strong 24h momentum is approved."""
    # Old formula: abs(0.49 - 0.5) = 0.01 → 100 bps → rejected
    # New formula: day_change=0.15 → 1500 bps → approved
    near_fair = _make_market(liquidity=20_000, yes_price=0.49, day_change=0.15)
    calls = _run(near_fair)
    assert len(calls) == 1


def test_demo_side_prefers_hourly_over_daily_when_nonzero():
    """1h signal used for side when nonzero (fresher); 1d signal as fallback."""
    # day_change negative but hour_change positive → follows 1h → YES
    market = _make_market(liquidity=20_000, yes_price=0.40, day_change=-0.05, hour_change=0.04)
    calls = _run(market)
    assert len(calls) == 1
    assert calls[0][2] == "YES"


def test_demo_side_falls_back_to_daily_when_no_hourly():
    """Negative 1d momentum with no 1h data → NO signal."""
    market = _make_market(liquidity=20_000, yes_price=0.40, day_change=-0.10, hour_change=0.0)
    calls = _run(market)
    assert len(calls) == 1
    assert calls[0][2] == "NO"


# ---------------------------------------------------------------------------
# Tests — backward compat
# ---------------------------------------------------------------------------


def test_min_liquidity_constant_is_10k():
    """Regression guard: module-level MIN_LIQUIDITY constant preserved at 10_000."""
    assert scanner.MIN_LIQUIDITY == 10_000.0


def test_edge_price_threshold_constant_preserved():
    """Regression guard: EDGE_PRICE_THRESHOLD constant still exists for test mocks."""
    assert scanner.EDGE_PRICE_THRESHOLD == 0.15
