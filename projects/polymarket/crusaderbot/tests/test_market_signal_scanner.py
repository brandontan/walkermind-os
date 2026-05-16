"""Hermetic tests for market_signal_scanner — MIN_LIQUIDITY filter.

Covers: demo path skips markets below the raised MIN_LIQUIDITY floor.
No DB, no HTTP, no broker. Pool + Gamma API patched at module boundary.
"""
from __future__ import annotations

import asyncio
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from projects.polymarket.crusaderbot.jobs import market_signal_scanner as scanner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_market(*, liquidity: float, yes_price: float = 0.04) -> dict:
    return {
        "conditionId": "mkt-test-001",
        "question": "Will Austria win the 2026 FIFA World Cup?",
        "liquidity": liquidity,
        "outcomePrices": [str(yes_price), str(1 - yes_price)],
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_demo_skips_markets_below_min_liquidity():
    """Markets with liquidity=5_000 must be filtered out — no signal published."""
    low_liq_market = _make_market(liquidity=5_000, yes_price=0.04)

    published_calls: list = []

    async def _fake_publish(*args, **kwargs):
        published_calls.append(args)

    async def _fake_already_published(*args, **kwargs):
        return False

    async def _fake_heisenberg():
        return 0, 0

    pool = _make_pool()
    # Patch pool, Gamma API (polymarket.get_markets), and publish helpers
    with (
        patch.object(scanner, "get_pool", return_value=pool),
        patch.object(
            scanner.polymarket,
            "get_markets",
            new=AsyncMock(return_value=[low_liq_market]),
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

    assert published_calls == [], (
        f"Expected no signals for liquidity=5_000 < MIN_LIQUIDITY="
        f"{scanner.MIN_LIQUIDITY}, but got {len(published_calls)} publish call(s)"
    )


def test_min_liquidity_constant_is_10k():
    """Regression guard: MIN_LIQUIDITY must equal 10_000 after the fix."""
    assert scanner.MIN_LIQUIDITY == 10_000.0
