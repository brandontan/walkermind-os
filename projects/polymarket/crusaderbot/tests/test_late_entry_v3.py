"""Hermetic tests for LateEntryV3Strategy.

Coverage:
    * Implements the BaseStrategy contract + registered by bootstrap
    * Present in STRATEGY_AVAILABILITY (else risk gate step 4 rejects it)
    * Enters the favored (higher-ask) side when all gates pass
    * Side selection: higher YES ask -> YES, higher NO ask -> NO
    * Gates: entry window (<=35s), ask-diff (>=0.05), spread (<=1.05),
      favored-price cap (<0.70 — fav>=0.70 is a net-loss zone)
    * BUG 1: market_id equals conditionId (not Gamma UUID)
    * BUG 3: active=False on candle (updown) slug does NOT skip the market
    * Empty / errored market data + empty orderbooks return [] / skip
    * default_tp_sl() == (0.15, 0.08)
    * evaluate_exit() flip-stop: exit at <=0.48, hold above

No network, no DB, no broker. Polymarket API calls are patched with AsyncMock.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from projects.polymarket.crusaderbot.domain.risk.constants import STRATEGY_AVAILABILITY
from projects.polymarket.crusaderbot.domain.strategy import (
    StrategyRegistry,
    bootstrap_default_strategies,
)
from projects.polymarket.crusaderbot.domain.strategy.base import BaseStrategy
from projects.polymarket.crusaderbot.domain.strategy.strategies.late_entry_v3 import (
    DEFAULT_SL_PCT,
    DEFAULT_TP_PCT,
    FLIP_STOP_PRICE,
    LateEntryV3Strategy,
    suggested_trade_size,
)
from projects.polymarket.crusaderbot.domain.strategy.types import (
    ExitDecision,
    MarketFilters,
    SignalCandidate,
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


@pytest.fixture(autouse=True)
def _reset_registry():
    StrategyRegistry._reset_for_tests()
    yield
    StrategyRegistry._reset_for_tests()


def _make_filters(*, blacklisted: list[str] | None = None) -> MarketFilters:
    return MarketFilters(
        categories=[],
        min_liquidity=0.0,
        max_time_to_resolution_days=365,
        blacklisted_market_ids=blacklisted or [],
    )


def _make_context(*, available: float = 1000.0, alloc: float = 0.5,
                  equity: float = 0.0) -> UserContext:
    return UserContext(
        user_id="u1",
        sub_account_id="s1",
        risk_profile="balanced",
        capital_allocation_pct=alloc,
        available_balance_usdc=available,
        equity_usdc=equity,
        selected_timeframe="5m",
        selected_assets=("BTC",),
    )


def _make_market(
    *,
    market_id: str = "m1",
    condition_id: str = "c1",
    seconds_to_close: float = 20.0,
    active: bool = True,
    closed: bool = False,
) -> dict:
    end = datetime.now(timezone.utc) + timedelta(seconds=seconds_to_close)
    return {
        "id": market_id,
        "conditionId": condition_id,
        # slug carries the BTC asset token + 5m timeframe so is_short_crypto_market passes.
        "slug": "btc-updown-5m-1779249900",
        "question": "BTC 5 minute up or down?",
        "active": active,
        "closed": closed,
        "acceptingOrders": True,
        "clobTokenIds": ["yes_tok", "no_tok"],
        "endDate": end.isoformat().replace("+00:00", "Z"),
    }


def _book(asks_price: float | None) -> dict:
    if asks_price is None:
        return {"bids": [], "asks": []}
    return {"bids": [{"price": "0.10", "size": "5"}],
            "asks": [{"price": str(asks_price), "size": "5"}]}


def _book_side_effect(yes_ask: float | None, no_ask: float | None):
    async def _inner(token_id: str) -> dict:
        if token_id == "yes_tok":
            return _book(yes_ask)
        if token_id == "no_tok":
            return _book(no_ask)
        return {"bids": [], "asks": []}
    return _inner


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Contract / registration
# ---------------------------------------------------------------------------


def test_implements_base_strategy_contract():
    strat = LateEntryV3Strategy()
    assert isinstance(strat, BaseStrategy)
    assert strat.name == "late_entry_v3"
    assert strat.version == "1.0.0"
    assert strat.default_tp_sl() == (DEFAULT_TP_PCT, DEFAULT_SL_PCT) == (0.15, 0.08)


def test_registered_by_bootstrap():
    reg = bootstrap_default_strategies()
    assert isinstance(reg.get("late_entry_v3"), LateEntryV3Strategy)


def test_present_in_strategy_availability():
    # Risk gate step 4 rejects unknown_strategy otherwise.
    assert "late_entry_v3" in STRATEGY_AVAILABILITY
    assert "balanced" in STRATEGY_AVAILABILITY["late_entry_v3"]


# ---------------------------------------------------------------------------
# scan(): entry + side selection + gates
# ---------------------------------------------------------------------------


def test_enters_favored_yes_side():
    strat = LateEntryV3Strategy()
    with patch(_MARKETS_PATCH, new=AsyncMock(return_value=[_make_market()])), \
         patch(_BOOK_PATCH, new=AsyncMock(side_effect=_book_side_effect(0.65, 0.20))):
        cands = _run(strat.scan(_make_filters(), _make_context()))
    assert len(cands) == 1
    c = cands[0]
    assert isinstance(c, SignalCandidate)
    assert c.side == "YES"
    assert c.strategy_name == "late_entry_v3"
    assert c.suggested_size_usdc > 0.0
    assert c.metadata["fav_price"] == pytest.approx(0.65)


def test_enters_favored_no_side():
    strat = LateEntryV3Strategy()
    with patch(_MARKETS_PATCH, new=AsyncMock(return_value=[_make_market()])), \
         patch(_BOOK_PATCH, new=AsyncMock(side_effect=_book_side_effect(0.20, 0.65))):
        cands = _run(strat.scan(_make_filters(), _make_context()))
    assert len(cands) == 1
    assert cands[0].side == "NO"


def test_skips_when_ask_diff_below_threshold():
    strat = LateEntryV3Strategy()
    # diff 0.02 < MIN_ASK_DIFF 0.05 (near coin-flip candle)
    with patch(_MARKETS_PATCH, new=AsyncMock(return_value=[_make_market()])), \
         patch(_BOOK_PATCH, new=AsyncMock(side_effect=_book_side_effect(0.52, 0.50))):
        cands = _run(strat.scan(_make_filters(), _make_context()))
    assert cands == []


def test_enters_on_small_real_lean():
    """A ~5c lean (0.55 vs 0.50) now qualifies (was filtered by the old 0.30 gate)."""
    strat = LateEntryV3Strategy()
    with patch(_MARKETS_PATCH, new=AsyncMock(return_value=[_make_market()])), \
         patch(_BOOK_PATCH, new=AsyncMock(side_effect=_book_side_effect(0.55, 0.50))):
        cands = _run(strat.scan(_make_filters(), _make_context()))
    assert len(cands) == 1 and cands[0].side == "YES"


def test_best_ask_uses_lowest_price_regardless_of_order():
    """CLOB returns asks DESCENDING; _best_ask must return the lowest price."""
    from projects.polymarket.crusaderbot.domain.strategy.strategies.late_entry_v3 import _best_ask
    book = {"asks": [{"price": "0.99", "size": "9"},
                     {"price": "0.51", "size": "9"},
                     {"price": "0.74", "size": "9"}]}
    assert _best_ask(book) == 0.51
    assert _best_ask({"asks": []}) is None


def test_skips_when_favored_price_too_high():
    strat = LateEntryV3Strategy()
    # fav 0.95 >= FAV_PRICE_MAX 0.70 (no_ask 0.05 keeps spread valid, diff valid)
    with patch(_MARKETS_PATCH, new=AsyncMock(return_value=[_make_market()])), \
         patch(_BOOK_PATCH, new=AsyncMock(side_effect=_book_side_effect(0.95, 0.05))):
        cands = _run(strat.scan(_make_filters(), _make_context()))
    assert cands == []


def test_skips_when_favored_price_just_above_cap():
    """fav 0.72 >= FAV_PRICE_MAX 0.70 is rejected — the new net-loss-zone cap."""
    strat = LateEntryV3Strategy()
    with patch(_MARKETS_PATCH, new=AsyncMock(return_value=[_make_market()])), \
         patch(_BOOK_PATCH, new=AsyncMock(side_effect=_book_side_effect(0.72, 0.20))):
        cands = _run(strat.scan(_make_filters(), _make_context()))
    assert cands == []


def test_enters_just_below_cap():
    """fav 0.68 < FAV_PRICE_MAX 0.70 still enters — top of the valid band."""
    strat = LateEntryV3Strategy()
    with patch(_MARKETS_PATCH, new=AsyncMock(return_value=[_make_market()])), \
         patch(_BOOK_PATCH, new=AsyncMock(side_effect=_book_side_effect(0.68, 0.20))):
        cands = _run(strat.scan(_make_filters(), _make_context()))
    assert len(cands) == 1 and cands[0].metadata["fav_price"] == pytest.approx(0.68)


def test_suggested_trade_size_floor_and_cap():
    """Per-trade = base x CAP% x 4%, clamped to [$1, $25]. CAP% is NOT the trade size."""
    # $1000 equity x 60% x 4% = $24 (under the $25 cap)
    assert suggested_trade_size(1000.0, 0.60) == pytest.approx(24.0)
    # huge pool -> hard-capped at $25
    assert suggested_trade_size(100_000.0, 0.60) == 25.0
    # tiny pool -> floored at $1
    assert suggested_trade_size(5.0, 0.20) == 1.0


def test_sizes_off_equity_not_free_balance():
    """Sizing uses equity (balance + open value), not idle cash."""
    strat = LateEntryV3Strategy()
    # equity 10000 -> 10000 x 0.5 x 0.04 = 200 -> capped 25; free balance only 10
    ctx = _make_context(available=10.0, alloc=0.5, equity=10_000.0)
    with patch(_MARKETS_PATCH, new=AsyncMock(return_value=[_make_market()])), \
         patch(_BOOK_PATCH, new=AsyncMock(side_effect=_book_side_effect(0.65, 0.20))):
        cands = _run(strat.scan(_make_filters(), ctx))
    assert len(cands) == 1
    assert cands[0].suggested_size_usdc == pytest.approx(25.0)


def test_skips_when_spread_too_wide():
    strat = LateEntryV3Strategy()
    # yes 0.90 + no 0.55 = 1.45 > MAX_SPREAD 1.05 (diff 0.35 ok, fav 0.90 ok)
    with patch(_MARKETS_PATCH, new=AsyncMock(return_value=[_make_market()])), \
         patch(_BOOK_PATCH, new=AsyncMock(side_effect=_book_side_effect(0.90, 0.55))):
        cands = _run(strat.scan(_make_filters(), _make_context()))
    assert cands == []


def test_skips_outside_entry_window():
    strat = LateEntryV3Strategy()
    far = _make_market(seconds_to_close=600.0)  # > 240s
    with patch(_MARKETS_PATCH, new=AsyncMock(return_value=[far])), \
         patch(_BOOK_PATCH, new=AsyncMock(side_effect=_book_side_effect(0.70, 0.20))):
        cands = _run(strat.scan(_make_filters(), _make_context()))
    assert cands == []


def test_skips_when_book_empty():
    strat = LateEntryV3Strategy()
    with patch(_MARKETS_PATCH, new=AsyncMock(return_value=[_make_market()])), \
         patch(_BOOK_PATCH, new=AsyncMock(side_effect=_book_side_effect(None, 0.20))):
        cands = _run(strat.scan(_make_filters(), _make_context()))
    assert cands == []


def test_blacklisted_market_skipped():
    strat = LateEntryV3Strategy()
    with patch(_MARKETS_PATCH, new=AsyncMock(return_value=[_make_market()])), \
         patch(_BOOK_PATCH, new=AsyncMock(side_effect=_book_side_effect(0.70, 0.20))):
        cands = _run(strat.scan(_make_filters(blacklisted=["c1"]), _make_context()))
    assert cands == []


def test_market_id_uses_condition_id():
    """BUG 1: SignalCandidate.market_id must equal conditionId (markets table PK).

    Gamma's 'id' field is a separate UUID. _load_market() keys on conditionId —
    using the UUID caused every candidate to be skipped as 'skipped_market_not_synced'.
    """
    strat = LateEntryV3Strategy()
    m = _make_market(market_id="gamma-uuid-irrelevant", condition_id="0xdeadbeef")
    with patch(_MARKETS_PATCH, new=AsyncMock(return_value=[m])), \
         patch(_BOOK_PATCH, new=AsyncMock(side_effect=_book_side_effect(0.65, 0.20))):
        cands = _run(strat.scan(_make_filters(), _make_context()))
    assert len(cands) == 1
    assert cands[0].market_id == "0xdeadbeef"    # conditionId, not Gamma UUID
    assert cands[0].condition_id == "0xdeadbeef"


def test_candle_market_active_false_not_skipped():
    """BUG 3: active=False on a candle (updown slug) must not reject the market.

    Polymarket sets active=False on candle markets before resolution while the
    CLOB book still has liquidity. The active gate is skipped for candle slugs.
    """
    strat = LateEntryV3Strategy()
    m = _make_market(active=False)
    assert "updown" in m["slug"], "fixture must use an updown candle slug"
    with patch(_MARKETS_PATCH, new=AsyncMock(return_value=[m])), \
         patch(_BOOK_PATCH, new=AsyncMock(side_effect=_book_side_effect(0.65, 0.20))):
        cands = _run(strat.scan(_make_filters(), _make_context()))
    assert len(cands) == 1, "active=False candle should still produce a candidate"


def test_non_candle_market_active_false_is_skipped():
    """Non-candle markets with active=False are still rejected (unchanged behaviour)."""
    strat = LateEntryV3Strategy()
    m = _make_market(active=False)
    m["slug"] = "us-election-winner-2026"  # no "updown" → not a candle
    with patch(_MARKETS_PATCH, new=AsyncMock(return_value=[m])), \
         patch(_BOOK_PATCH, new=AsyncMock(side_effect=_book_side_effect(0.70, 0.20))):
        cands = _run(strat.scan(_make_filters(), _make_context()))
    assert cands == []


def test_empty_markets_returns_empty():
    strat = LateEntryV3Strategy()
    with patch(_MARKETS_PATCH, new=AsyncMock(return_value=[])):
        cands = _run(strat.scan(_make_filters(), _make_context()))
    assert cands == []


def test_market_fetch_error_returns_empty():
    strat = LateEntryV3Strategy()
    with patch(_MARKETS_PATCH, new=AsyncMock(side_effect=RuntimeError("boom"))):
        cands = _run(strat.scan(_make_filters(), _make_context()))
    assert cands == []


# ---------------------------------------------------------------------------
# evaluate_exit(): flip-stop
# ---------------------------------------------------------------------------


def test_evaluate_exit_flips_at_threshold():
    strat = LateEntryV3Strategy()
    d = _run(strat.evaluate_exit({"current_price": FLIP_STOP_PRICE}))
    assert isinstance(d, ExitDecision)
    assert d.should_exit
    assert d.reason == "strategy_exit"


def test_evaluate_exit_holds_above_threshold():
    strat = LateEntryV3Strategy()
    d = _run(strat.evaluate_exit({"current_price": 0.60}))
    assert not d.should_exit
    assert d.reason == "hold"


def test_evaluate_exit_holds_when_price_missing():
    strat = LateEntryV3Strategy()
    d = _run(strat.evaluate_exit({}))
    assert not d.should_exit
    assert d.reason == "hold"
