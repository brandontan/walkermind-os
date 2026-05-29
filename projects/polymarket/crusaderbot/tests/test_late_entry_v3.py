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
    force_exit_at_rem_sec_for,
    resolve_per_trade_ceiling,
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
                  equity: float = 0.0, mpt_mode: str = "auto",
                  mpt_usdc: float | None = None, mpt_pct: float | None = None) -> UserContext:
    return UserContext(
        user_id="u1",
        sub_account_id="s1",
        risk_profile="balanced",
        capital_allocation_pct=alloc,
        available_balance_usdc=available,
        equity_usdc=equity,
        selected_timeframe="5m",
        selected_assets=("BTC",),
        max_per_trade_mode=mpt_mode,
        max_per_trade_usdc=mpt_usdc,
        max_per_trade_pct=mpt_pct,
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


def test_resolve_per_trade_ceiling_modes():
    # auto / unknown -> system $25 default
    assert resolve_per_trade_ceiling(1000.0, "auto", None, None) == 25.0
    assert resolve_per_trade_ceiling(1000.0, None, 999, 0.5) == 25.0
    # fixed clamps to [$1, $500]
    assert resolve_per_trade_ceiling(1000.0, "fixed", 50.0, None) == 50.0
    assert resolve_per_trade_ceiling(1000.0, "fixed", 9999.0, None) == 500.0
    assert resolve_per_trade_ceiling(1000.0, "fixed", 0.1, None) == 1.0
    # pct -> equity x pct, pct clamped to [0.5%, 10%]
    assert resolve_per_trade_ceiling(1000.0, "pct", None, 0.05) == pytest.approx(50.0)
    assert resolve_per_trade_ceiling(1000.0, "pct", None, 0.50) == pytest.approx(100.0)  # capped 10%
    assert resolve_per_trade_ceiling(1000.0, "pct", None, 0.001) == pytest.approx(5.0)   # floored 0.5%


def test_user_fixed_cap_limits_trade_size():
    """mode='fixed' max_usdc=$10 caps the trade even though natural size is larger."""
    strat = LateEntryV3Strategy()
    ctx = _make_context(equity=10_000.0, alloc=0.5, mpt_mode="fixed", mpt_usdc=10.0)
    with patch(_MARKETS_PATCH, new=AsyncMock(return_value=[_make_market()])), \
         patch(_BOOK_PATCH, new=AsyncMock(side_effect=_book_side_effect(0.65, 0.20))):
        cands = _run(strat.scan(_make_filters(), ctx))
    assert len(cands) == 1 and cands[0].suggested_size_usdc == pytest.approx(10.0)


def test_user_pct_cap_limits_trade_size():
    """mode='pct' 0.5% of $10k equity = $50 ceiling; natural $200 -> capped $50."""
    strat = LateEntryV3Strategy()
    ctx = _make_context(equity=10_000.0, alloc=0.5, mpt_mode="pct", mpt_pct=0.005)
    with patch(_MARKETS_PATCH, new=AsyncMock(return_value=[_make_market()])), \
         patch(_BOOK_PATCH, new=AsyncMock(side_effect=_book_side_effect(0.65, 0.20))):
        cands = _run(strat.scan(_make_filters(), ctx))
    assert len(cands) == 1 and cands[0].suggested_size_usdc == pytest.approx(50.0)


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


# ---------------------------------------------------------------------------
# effective_daily_loss + drawdown gate threshold (risk constants / gate layer)
# ---------------------------------------------------------------------------


def test_effective_daily_loss_uses_most_restrictive():
    from projects.polymarket.crusaderbot.domain.risk.constants import effective_daily_loss
    # profile cap is -500, user override -300 → -300 is stricter (less negative)
    assert effective_daily_loss("balanced", -300.0) == -300.0
    # user sets looser (-800) → profile -500 wins
    assert effective_daily_loss("balanced", -800.0) == -500.0
    # no override → profile default
    assert effective_daily_loss("balanced") == -500.0
    # hard stop floor: system -2000 never loosens beyond profile
    assert effective_daily_loss("conservative", -50.0) == -50.0


def test_max_drawdown_breached_respects_user_threshold():
    """Unit-test the threshold logic in isolation (no DB)."""
    from decimal import Decimal
    from projects.polymarket.crusaderbot.domain.risk import constants as K

    def _would_breach(deposits, balance, user_pct):
        if deposits <= 0:
            return False
        threshold = K.MAX_DRAWDOWN_HALT
        if user_pct is not None and 0 < user_pct < threshold:
            threshold = user_pct
        drawdown = (deposits - balance) / deposits
        return drawdown >= Decimal(str(threshold))

    deposits = Decimal("1000")
    balance_6pct_dd = Decimal("940")   # 6% drawdown
    balance_9pct_dd = Decimal("910")   # 9% drawdown

    # System 8% → 6% does not breach, 9% does
    assert not _would_breach(deposits, balance_6pct_dd, None)
    assert _would_breach(deposits, balance_9pct_dd, None)

    # User sets 5% halt → 6% now breaches
    assert _would_breach(deposits, balance_6pct_dd, 0.05)

    # User sets 10% (looser than system 8%) → system 8% still applies, 6% ok
    assert not _would_breach(deposits, balance_6pct_dd, 0.10)


# ---------------------------------------------------------------------------
# safe_close: min_entry_sec floor gate
# ---------------------------------------------------------------------------


def test_safe_close_skips_when_inside_min_entry_sec():
    """safe_close must not enter when seconds_left < 30 (final 30s off-limits)."""
    strat = LateEntryV3Strategy()
    # 55s < entry_window_sec=60 → passes outer gate; 10s < min_entry_sec=30 → must reject
    m = _make_market(seconds_to_close=10.0)
    with patch(_MARKETS_PATCH, new=AsyncMock(return_value=[m])), \
         patch(_BOOK_PATCH, new=AsyncMock(side_effect=_book_side_effect(0.65, 0.25))):
        cands = _run(strat.scan(
            _make_filters(), _make_context(),
            min_ask_diff=0.08,
            entry_window_sec=60.0,
            fav_price_min=0.60,
            fav_price_max=0.70,
            min_entry_sec=30.0,
        ))
    assert cands == [], "entry inside min_entry_sec should be rejected"


def test_safe_close_enters_within_valid_window():
    """safe_close must enter when 30 <= seconds_left <= 60."""
    strat = LateEntryV3Strategy()
    # 45s is inside the 30–60s window for safe_close
    m = _make_market(seconds_to_close=45.0)
    with patch(_MARKETS_PATCH, new=AsyncMock(return_value=[m])), \
         patch(_BOOK_PATCH, new=AsyncMock(side_effect=_book_side_effect(0.65, 0.25))):
        cands = _run(strat.scan(
            _make_filters(), _make_context(),
            min_ask_diff=0.08,
            entry_window_sec=60.0,
            fav_price_min=0.60,
            fav_price_max=0.70,
            min_entry_sec=30.0,
        ))
    assert len(cands) == 1
    assert cands[0].side == "YES"          # favored (majority) side
    assert cands[0].metadata["underdog_mode"] is False


# ---------------------------------------------------------------------------
# flip_hunter: underdog_mode — enter cheap side 0.26–0.35
# ---------------------------------------------------------------------------


def test_flip_hunter_enters_cheap_side():
    """flip_hunter must enter the LOW-probability side (0.26–0.35), not the favored side."""
    strat = LateEntryV3Strategy()
    # YES is favored (0.70 ask), NO is cheap (0.30 ask) — underdog_mode enters NO
    m = _make_market(seconds_to_close=90.0)
    with patch(_MARKETS_PATCH, new=AsyncMock(return_value=[m])), \
         patch(_BOOK_PATCH, new=AsyncMock(side_effect=_book_side_effect(0.70, 0.30))):
        cands = _run(strat.scan(
            _make_filters(), _make_context(),
            min_ask_diff=0.05,
            entry_window_sec=140.0,
            fav_price_min=0.26,
            fav_price_max=0.36,
            underdog_mode=True,
        ))
    assert len(cands) == 1
    assert cands[0].side == "NO"           # cheap side entered, NOT the majority YES
    assert cands[0].metadata["underdog_mode"] is True
    assert cands[0].metadata["entry_price"] == pytest.approx(0.30, abs=0.001)


def test_flip_hunter_skips_when_cheap_side_outside_range():
    """flip_hunter must skip when cheap side price is outside [0.26, 0.36)."""
    strat = LateEntryV3Strategy()
    # NO is cheap at 0.20 — below the 0.26 floor
    m = _make_market(seconds_to_close=90.0)
    with patch(_MARKETS_PATCH, new=AsyncMock(return_value=[m])), \
         patch(_BOOK_PATCH, new=AsyncMock(side_effect=_book_side_effect(0.75, 0.20))):
        cands = _run(strat.scan(
            _make_filters(), _make_context(),
            min_ask_diff=0.05,
            entry_window_sec=140.0,
            fav_price_min=0.26,
            fav_price_max=0.36,
            underdog_mode=True,
        ))
    assert cands == [], "cheap side below 0.26 floor should be rejected"


def test_flip_hunter_does_not_affect_standard_mode():
    """underdog_mode=False (default) must still enter the favored side — no regression."""
    strat = LateEntryV3Strategy()
    m = _make_market(seconds_to_close=20.0)
    with patch(_MARKETS_PATCH, new=AsyncMock(return_value=[m])), \
         patch(_BOOK_PATCH, new=AsyncMock(side_effect=_book_side_effect(0.65, 0.25))):
        cands = _run(strat.scan(
            _make_filters(), _make_context(),
            min_ask_diff=0.05,
            entry_window_sec=35.0,
            fav_price_min=0.55,
            fav_price_max=0.70,
            underdog_mode=False,
        ))
    assert len(cands) == 1
    assert cands[0].side == "YES"          # favored side, unchanged behaviour


# ---------------------------------------------------------------------------
# Candidate metadata carries the price band so _process_candidate can
# re-validate the live fill price (fill-time band re-check guard).
# ---------------------------------------------------------------------------


def test_candidate_metadata_carries_fav_price_band_standard_mode():
    """Standard mode must emit fav_price_min/max in metadata for fill-time re-check."""
    strat = LateEntryV3Strategy()
    m = _make_market(seconds_to_close=20.0)
    with patch(_MARKETS_PATCH, new=AsyncMock(return_value=[m])), \
         patch(_BOOK_PATCH, new=AsyncMock(side_effect=_book_side_effect(0.65, 0.25))):
        cands = _run(strat.scan(
            _make_filters(), _make_context(),
            min_ask_diff=0.05,
            entry_window_sec=35.0,
            fav_price_min=0.55,
            fav_price_max=0.70,
            underdog_mode=False,
        ))
    assert len(cands) == 1
    md = cands[0].metadata
    assert md["fav_price_min"] == pytest.approx(0.55, abs=1e-9)
    assert md["fav_price_max"] == pytest.approx(0.70, abs=1e-9)


def test_candidate_metadata_carries_fav_price_band_underdog_mode():
    """flip_hunter underdog mode must also emit the band for fill-time re-check."""
    strat = LateEntryV3Strategy()
    m = _make_market(seconds_to_close=90.0)
    with patch(_MARKETS_PATCH, new=AsyncMock(return_value=[m])), \
         patch(_BOOK_PATCH, new=AsyncMock(side_effect=_book_side_effect(0.70, 0.30))):
        cands = _run(strat.scan(
            _make_filters(), _make_context(),
            min_ask_diff=0.05,
            entry_window_sec=140.0,
            fav_price_min=0.26,
            fav_price_max=0.36,
            underdog_mode=True,
        ))
    assert len(cands) == 1
    md = cands[0].metadata
    assert md["fav_price_min"] == pytest.approx(0.26, abs=1e-9)
    assert md["fav_price_max"] == pytest.approx(0.36, abs=1e-9)
    assert md["underdog_mode"] is True


# ---------------------------------------------------------------------------
# Kreo-style fixed-time exit (force_exit_at_rem_sec)
# ---------------------------------------------------------------------------


def test_candidate_metadata_carries_force_exit_at_rem_sec():
    """When the scan caller passes force_exit_at_rem_sec, the candidate carries it."""
    strat = LateEntryV3Strategy()
    m = _make_market(seconds_to_close=45.0)
    with patch(_MARKETS_PATCH, new=AsyncMock(return_value=[m])), \
         patch(_BOOK_PATCH, new=AsyncMock(side_effect=_book_side_effect(0.65, 0.25))):
        cands = _run(strat.scan(
            _make_filters(), _make_context(),
            min_ask_diff=0.05,
            entry_window_sec=60.0,
            fav_price_min=0.60,
            fav_price_max=0.70,
            min_entry_sec=30.0,
            force_exit_at_rem_sec=30.0,
        ))
    assert len(cands) == 1
    assert cands[0].metadata["force_exit_at_rem_sec"] == pytest.approx(30.0, abs=1e-9)


def test_candidate_metadata_force_exit_none_when_not_passed():
    """Backward compat: omitting force_exit_at_rem_sec leaves metadata key None."""
    strat = LateEntryV3Strategy()
    m = _make_market(seconds_to_close=20.0)
    with patch(_MARKETS_PATCH, new=AsyncMock(return_value=[m])), \
         patch(_BOOK_PATCH, new=AsyncMock(side_effect=_book_side_effect(0.65, 0.25))):
        cands = _run(strat.scan(
            _make_filters(), _make_context(),
            min_ask_diff=0.05,
            entry_window_sec=35.0,
            fav_price_min=0.55,
            fav_price_max=0.70,
        ))
    assert len(cands) == 1
    assert cands[0].metadata["force_exit_at_rem_sec"] is None


def test_evaluate_exit_fires_force_exit_when_rem_le_threshold():
    """evaluate_exit must fire strategy_exit when seconds_to_close ≤ force_exit_at_rem_sec."""
    strat = LateEntryV3Strategy()
    decision = _run(strat.evaluate_exit({
        "current_price": 0.65,  # well above flip-stop
        "force_exit_at_rem_sec": 30.0,
        "seconds_to_close": 28.0,   # below threshold
    }))
    assert decision.should_exit is True
    assert decision.reason == "strategy_exit"
    assert decision.metadata.get("trigger") == "fixed_time_exit"


def test_evaluate_exit_fires_force_exit_at_exact_threshold():
    """Threshold is inclusive (≤): exit fires when seconds_to_close == force_exit_at_rem_sec."""
    strat = LateEntryV3Strategy()
    decision = _run(strat.evaluate_exit({
        "current_price": 0.65,
        "force_exit_at_rem_sec": 30.0,
        "seconds_to_close": 30.0,
    }))
    assert decision.should_exit is True


def test_evaluate_exit_no_force_exit_when_rem_above_threshold():
    """evaluate_exit must not fire when seconds_to_close > force_exit_at_rem_sec."""
    strat = LateEntryV3Strategy()
    decision = _run(strat.evaluate_exit({
        "current_price": 0.65,   # above flip-stop, no exit reason here
        "force_exit_at_rem_sec": 30.0,
        "seconds_to_close": 45.0,
    }))
    assert decision.should_exit is False


def test_evaluate_exit_no_force_exit_when_metadata_missing():
    """Backward compat: positions without force_exit_at_rem_sec keep flip-stop only."""
    strat = LateEntryV3Strategy()
    # No force_exit_at_rem_sec / seconds_to_close keys — must NOT raise + must NOT exit.
    decision = _run(strat.evaluate_exit({"current_price": 0.65}))
    assert decision.should_exit is False
    assert decision.reason == "hold"


def test_evaluate_exit_flip_stop_still_fires_after_force_exit_gate():
    """Flip-stop preserved: with force-exit gate not triggered, flip-stop still works."""
    strat = LateEntryV3Strategy()
    # rem above force threshold (no time-based exit) but price below flip-stop
    decision = _run(strat.evaluate_exit({
        "current_price": 0.05,   # below default FLIP_STOP_PRICE module fallback (0.48)
        "force_exit_at_rem_sec": 30.0,
        "seconds_to_close": 60.0,
    }))
    assert decision.should_exit is True
    assert decision.reason == "strategy_exit"
    assert decision.metadata.get("trigger") == "flip_stop"


def test_evaluate_exit_force_exit_takes_precedence_over_flip_stop():
    """When both conditions fire, force-exit wins (it runs first)."""
    strat = LateEntryV3Strategy()
    decision = _run(strat.evaluate_exit({
        "current_price": 0.05,   # would trigger flip-stop
        "force_exit_at_rem_sec": 30.0,
        "seconds_to_close": 20.0,  # would also trigger force-exit
    }))
    assert decision.should_exit is True
    assert decision.metadata.get("trigger") == "fixed_time_exit"


# ---------------------------------------------------------------------------
# force_exit_at_rem_sec_for(preset, timeframe) — central preset → exit lookup
# ---------------------------------------------------------------------------


def test_force_exit_lookup_safe_close_30s_either_tf():
    """Kreo Safe Close exits at rem=30s for both 5m and 15m (elapsed 270 / 870)."""
    assert force_exit_at_rem_sec_for("safe_close", "5m") == pytest.approx(30.0)
    assert force_exit_at_rem_sec_for("safe_close", "15m") == pytest.approx(30.0)


def test_force_exit_lookup_flip_hunter_5m_returns_160():
    """Kreo Early Flip Hunter 5m exits at rem=160s (elapsed 140s)."""
    assert force_exit_at_rem_sec_for("flip_hunter", "5m") == pytest.approx(160.0)


def test_force_exit_lookup_flip_hunter_15m_returns_480():
    """Kreo Early Flip Hunter 15m exits at rem=480s (elapsed 420s)."""
    assert force_exit_at_rem_sec_for("flip_hunter", "15m") == pytest.approx(480.0)


def test_force_exit_lookup_close_sweep_returns_8s():
    """close_sweep now force-exits ~8s before resolution (Kreo "exit at 299s")."""
    assert force_exit_at_rem_sec_for("close_sweep", "5m") == 8.0
    assert force_exit_at_rem_sec_for("close_sweep", "15m") == 8.0


def test_force_exit_lookup_unknown_preset_returns_none():
    """Unknown preset / None preset must not raise — returns None (no exit rule)."""
    assert force_exit_at_rem_sec_for(None, "5m") is None
    assert force_exit_at_rem_sec_for("nonexistent_preset", "5m") is None


def test_force_exit_lookup_flip_hunter_defaults_to_5m_for_missing_tf():
    """Missing timeframe defaults to 5m mapping (safe default for crypto candle scanner)."""
    assert force_exit_at_rem_sec_for("flip_hunter", None) == pytest.approx(160.0)
