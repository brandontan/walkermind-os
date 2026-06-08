"""Option 3 (smart-strike-real-edge) — late_entry_v3 stamps a measured GROSS edge.

When the advisory oracle computes a positive fair-value edge for the ENTERED side,
late_entry_v3 stamps ``metadata["slippage_gross_edge_bps"]`` = that edge in bps. The
LIVE step-14b slippage gate consumes it as the slippage-of-edge denominator ONLY in
real-edge mode (SMART_STRIKE_REQUIRE_MEASURED_EDGE ON); it is inert in the cap-only
default and in paper. These tests pin the strategy-side stamping (the gate consumption
+ threading are covered in test_smart_strike_cell_cap_binding + test_slippage_gate).

Invariant asserted (no fair-value re-derivation): the stamped bps equals the entry
side's oracle edge (oracle_edge_up for YES / oracle_edge_down for NO) × 10_000.

Hermetic — pm.get_crypto_window_markets + pm.get_book are AsyncMock-patched; the
oracle is a pure in-test OracleEdgeConfig (lambdas), no network/DB.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from projects.polymarket.crusaderbot.domain.strategy.strategies.late_entry_v3 import (
    LateEntryV3Strategy,
    OracleEdgeConfig,
)
from projects.polymarket.crusaderbot.domain.strategy.types import (
    MarketFilters,
    UserContext,
)

_MARKETS_PATCH = (
    "projects.polymarket.crusaderbot.domain.strategy.strategies"
    ".late_entry_v3.pm.get_crypto_window_markets"
)
_BOOK_PATCH = (
    "projects.polymarket.crusaderbot.domain.strategy.strategies"
    ".late_entry_v3.pm.get_book"
)


def _filters() -> MarketFilters:
    return MarketFilters(
        categories=[], min_liquidity=0.0,
        max_time_to_resolution_days=365, blacklisted_market_ids=[],
    )


def _ctx() -> UserContext:
    return UserContext(
        user_id="u1", sub_account_id="s1", risk_profile="balanced",
        capital_allocation_pct=0.5, available_balance_usdc=1000.0, equity_usdc=0.0,
        selected_timeframe="5m", selected_assets=("BTC",),
        max_per_trade_mode="auto", max_per_trade_usdc=None, max_per_trade_pct=None,
    )


def _market() -> dict:
    end = datetime.now(timezone.utc) + timedelta(seconds=20.0)
    return {
        "id": "m1", "conditionId": "c1",
        "slug": "btc-updown-5m-1779249900",
        "question": "BTC 5 minute up or down?",
        "active": True, "closed": False, "acceptingOrders": True,
        "clobTokenIds": ["yes_tok", "no_tok"],
        "endDate": end.isoformat().replace("+00:00", "Z"),
    }


def _book(ask: float) -> dict:
    return {"bids": [{"price": "0.10", "size": "5"}],
            "asks": [{"price": str(ask), "size": "5"}]}


def _books(yes_ask: float, no_ask: float):
    async def _inner(token_id: str) -> dict:
        if token_id == "yes_tok":
            return _book(yes_ask)
        if token_id == "no_tok":
            return _book(no_ask)
        return {"bids": [], "asks": []}
    return _inner


def _oracle_cfg(oracle_now: float) -> OracleEdgeConfig:
    # Tiny sigma → near-deterministic fair value (≈1.0 when now>ptb, ≈0.0 when now<ptb)
    # so the entered side has a clearly positive edge and the test is stable.
    return OracleEdgeConfig(
        enabled=True,
        price_provider=lambda symbol: oracle_now,
        price_at_provider=lambda symbol, epoch, tolerance_sec=2.0: 100.0,
        sigma_map={"btc": 1e-9},
        min_dist=0.0, max_dist=1.0, min_edge=0.0,
    )


def _run(coro):
    return asyncio.run(coro)


def test_stamps_entry_side_edge_for_favored_yes():
    # Favored YES (0.55 vs 0.20), oracle now > price_to_beat → fair_up≈1 → edge_up>0.
    strat = LateEntryV3Strategy()
    with patch(_MARKETS_PATCH, new=AsyncMock(return_value=[_market()])), \
         patch(_BOOK_PATCH, new=AsyncMock(side_effect=_books(0.55, 0.20))):
        cands = _run(strat.scan(_filters(), _ctx(), edge_cfg=_oracle_cfg(100.5)))
    assert len(cands) == 1
    md = cands[0].metadata
    assert cands[0].side == "YES"
    assert md.get("oracle_edge_status") == "computed"
    assert md["slippage_gross_edge_bps"] is not None
    assert md["slippage_gross_edge_bps"] > 0.0
    # Invariant: stamped bps == entry-side (YES → edge_up) oracle edge × 10_000.
    assert md["slippage_gross_edge_bps"] == pytest.approx(md["oracle_edge_up"] * 10_000.0)


def test_stamps_entry_side_edge_for_favored_no():
    # Favored NO (0.55 vs 0.20 on NO), oracle now < price_to_beat → fair_up≈0 → edge_down>0.
    strat = LateEntryV3Strategy()
    with patch(_MARKETS_PATCH, new=AsyncMock(return_value=[_market()])), \
         patch(_BOOK_PATCH, new=AsyncMock(side_effect=_books(0.20, 0.55))):
        cands = _run(strat.scan(_filters(), _ctx(), edge_cfg=_oracle_cfg(99.5)))
    assert len(cands) == 1
    md = cands[0].metadata
    assert cands[0].side == "NO"
    assert md["slippage_gross_edge_bps"] is not None
    assert md["slippage_gross_edge_bps"] > 0.0
    # Invariant: stamped bps == entry-side (NO → edge_down) oracle edge × 10_000.
    assert md["slippage_gross_edge_bps"] == pytest.approx(md["oracle_edge_down"] * 10_000.0)


def test_no_oracle_no_stamp():
    # No edge_cfg → oracle never computes → no measured edge stamped (cap-only / HALT
    # by SMART_STRIKE_REQUIRE_MEASURED_EDGE governs at the gate).
    strat = LateEntryV3Strategy()
    with patch(_MARKETS_PATCH, new=AsyncMock(return_value=[_market()])), \
         patch(_BOOK_PATCH, new=AsyncMock(side_effect=_books(0.55, 0.20))):
        cands = _run(strat.scan(_filters(), _ctx()))
    assert len(cands) == 1
    assert cands[0].metadata["slippage_gross_edge_bps"] is None


def test_no_stamp_when_entry_side_edge_not_positive():
    # Favored YES but oracle now < price_to_beat → fair_up≈0 → edge_up<0 → NOT stamped
    # (a non-positive edge is treated as no measured edge).
    strat = LateEntryV3Strategy()
    with patch(_MARKETS_PATCH, new=AsyncMock(return_value=[_market()])), \
         patch(_BOOK_PATCH, new=AsyncMock(side_effect=_books(0.55, 0.20))):
        cands = _run(strat.scan(_filters(), _ctx(), edge_cfg=_oracle_cfg(99.5)))
    assert len(cands) == 1
    assert cands[0].side == "YES"
    assert cands[0].metadata["slippage_gross_edge_bps"] is None
