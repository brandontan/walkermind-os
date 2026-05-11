"""Hermetic tests for MomentumReversalStrategy (issue #975).

Coverage:
    * MomentumReversalStrategy implements BaseStrategy contract
    * Strategy is registered by bootstrap_default_strategies()
    * Empty / invalid market data returns [], not exception
    * Closed / inactive / non-accepting markets are ignored
    * Held / blacklisted markets are ignored
    * Drop threshold filter works
    * Liquidity filter works (MarketFilters.min_liquidity respected)
    * Volume filter works
    * YES price min/max filter works
    * Confidence sorting works
    * default_tp_sl() returns explicit positive decimals
    * No execution / risk / live guard behavior changes

No network, no DB, no broker. Polymarket API calls are patched with
unittest.mock.AsyncMock throughout.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from projects.polymarket.crusaderbot.domain.strategy import (
    StrategyRegistry,
    bootstrap_default_strategies,
)
from projects.polymarket.crusaderbot.domain.strategy.base import BaseStrategy
from projects.polymarket.crusaderbot.domain.strategy.strategies.momentum_reversal import (
    DEFAULT_SL_PCT,
    DEFAULT_TP_PCT,
    DROP_THRESHOLD,
    MAX_YES_PRICE,
    MIN_VOLUME_24H,
    MIN_YES_PRICE,
    MomentumReversalStrategy,
    _evaluate_market,
    _extract_24h_price_change,
    _extract_liquidity,
    _extract_volume_24h,
    _extract_yes_price,
)
from projects.polymarket.crusaderbot.domain.strategy.types import (
    ExitDecision,
    MarketFilters,
    SignalCandidate,
    UserContext,
)

_PM_PATCH = (
    "projects.polymarket.crusaderbot.domain.strategy.strategies"
    ".momentum_reversal.pm.get_markets"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_registry():
    StrategyRegistry._reset_for_tests()
    yield
    StrategyRegistry._reset_for_tests()


def _make_filters(
    *,
    min_liquidity: float = 0.0,
    blacklisted: list[str] | None = None,
) -> MarketFilters:
    return MarketFilters(
        categories=[],
        min_liquidity=min_liquidity,
        max_time_to_resolution_days=365,
        blacklisted_market_ids=blacklisted or [],
    )


def _make_context(
    *,
    available: float = 1000.0,
    alloc: float = 0.5,
) -> UserContext:
    return UserContext(
        user_id="u1",
        sub_account_id="s1",
        risk_profile="balanced",
        capital_allocation_pct=alloc,
        available_balance_usdc=available,
    )


def _make_market(
    *,
    market_id: str = "m1",
    condition_id: str = "c1",
    active: bool = True,
    closed: bool = False,
    accepting_orders: bool = True,
    yes_price: float = 0.45,
    drop: float = -0.15,
    liquidity: float = 5_000.0,
    volume_24h: float = 2_000.0,
) -> dict:
    return {
        "id": market_id,
        "conditionId": condition_id,
        "active": active,
        "closed": closed,
        "acceptingOrders": accepting_orders,
        "outcomePrices": [str(yes_price), str(round(1.0 - yes_price, 4))],
        "oneDayPriceChange": drop,
        "liquidity": liquidity,
        "volume_24hr": volume_24h,
    }


# ---------------------------------------------------------------------------
# Contract compliance
# ---------------------------------------------------------------------------


def test_implements_base_strategy():
    assert issubclass(MomentumReversalStrategy, BaseStrategy)


def test_instantiates_and_has_required_attributes():
    s = MomentumReversalStrategy()
    assert s.name == "momentum_reversal"
    assert s.version
    assert s.risk_profile_compatibility


def test_default_tp_sl_returns_explicit_positive_decimals():
    tp, sl = MomentumReversalStrategy().default_tp_sl()
    assert isinstance(tp, float)
    assert isinstance(sl, float)
    assert tp > 0.0
    assert sl > 0.0
    assert tp == DEFAULT_TP_PCT
    assert sl == DEFAULT_SL_PCT


def test_default_tp_sl_values_are_conservative():
    tp, sl = MomentumReversalStrategy().default_tp_sl()
    assert tp <= 0.25
    assert sl <= 0.15


def test_evaluate_exit_returns_hold():
    result = asyncio.get_event_loop().run_until_complete(
        MomentumReversalStrategy().evaluate_exit({})
    )
    assert result == ExitDecision(should_exit=False, reason="hold")


# ---------------------------------------------------------------------------
# Registry bootstrap
# ---------------------------------------------------------------------------


def test_bootstrap_registers_momentum_reversal():
    reg = bootstrap_default_strategies()
    names = [s["name"] for s in reg.list_available()]
    assert "momentum_reversal" in names


def test_bootstrap_registers_all_three_strategies():
    reg = bootstrap_default_strategies()
    names = {s["name"] for s in reg.list_available()}
    assert {"copy_trade", "signal_following", "momentum_reversal"} <= names


def test_bootstrap_is_idempotent():
    bootstrap_default_strategies()
    bootstrap_default_strategies()
    reg = StrategyRegistry.instance()
    count = sum(1 for s in reg.list_available() if s["name"] == "momentum_reversal")
    assert count == 1


# ---------------------------------------------------------------------------
# scan() — empty / error paths
# ---------------------------------------------------------------------------


def test_scan_returns_empty_list_when_get_markets_returns_empty():
    s = MomentumReversalStrategy()
    with patch(_PM_PATCH, new=AsyncMock(return_value=[])):
        result = asyncio.get_event_loop().run_until_complete(
            s.scan(_make_filters(), _make_context())
        )
    assert result == []


def test_scan_returns_empty_list_when_get_markets_raises():
    s = MomentumReversalStrategy()
    with patch(_PM_PATCH, new=AsyncMock(side_effect=RuntimeError("network error"))):
        result = asyncio.get_event_loop().run_until_complete(
            s.scan(_make_filters(), _make_context())
        )
    assert result == []


def test_scan_skips_malformed_market_dict_without_exception():
    s = MomentumReversalStrategy()
    bad_markets = [{"garbage": True}, None, {}, {"id": "x"}]
    with patch(_PM_PATCH, new=AsyncMock(return_value=bad_markets)):
        result = asyncio.get_event_loop().run_until_complete(
            s.scan(_make_filters(), _make_context())
        )
    assert result == []


# ---------------------------------------------------------------------------
# scan() — market status filters
# ---------------------------------------------------------------------------


def test_scan_ignores_inactive_market():
    m = _make_market(active=False)
    _assert_scan_empty([m])


def test_scan_ignores_closed_market():
    m = _make_market(closed=True)
    _assert_scan_empty([m])


def test_scan_ignores_non_accepting_market():
    m = _make_market(accepting_orders=False)
    _assert_scan_empty([m])


# ---------------------------------------------------------------------------
# scan() — blacklist
# ---------------------------------------------------------------------------


def test_scan_ignores_blacklisted_condition_id():
    m = _make_market(condition_id="blacklisted_cid")
    _assert_scan_empty([m], blacklisted=["blacklisted_cid"])


def test_scan_ignores_blacklisted_market_id():
    m = _make_market(market_id="blacklisted_mid", condition_id="c1")
    _assert_scan_empty([m], blacklisted=["blacklisted_mid"])


# ---------------------------------------------------------------------------
# scan() — drop threshold filter
# ---------------------------------------------------------------------------


def test_scan_ignores_market_with_small_drop():
    m = _make_market(drop=-0.05)  # above DROP_THRESHOLD (-0.10), filtered out
    _assert_scan_empty([m])


def test_scan_ignores_market_with_price_increase():
    m = _make_market(drop=0.05)
    _assert_scan_empty([m])


def test_scan_accepts_market_at_threshold_boundary():
    m = _make_market(drop=DROP_THRESHOLD)
    _assert_scan_non_empty([m])


def test_scan_accepts_market_beyond_threshold():
    m = _make_market(drop=-0.20)
    _assert_scan_non_empty([m])


# ---------------------------------------------------------------------------
# scan() — liquidity filter
# ---------------------------------------------------------------------------


def test_scan_ignores_market_below_min_liquidity():
    m = _make_market(liquidity=500.0)
    _assert_scan_empty([m], min_liquidity=1_000.0)


def test_scan_accepts_market_meeting_min_liquidity():
    m = _make_market(liquidity=1_000.0)
    _assert_scan_non_empty([m], min_liquidity=1_000.0)


# ---------------------------------------------------------------------------
# scan() — volume filter
# ---------------------------------------------------------------------------


def test_scan_ignores_market_with_low_volume():
    m = _make_market(volume_24h=500.0)  # below MIN_VOLUME_24H (1000)
    _assert_scan_empty([m])


def test_scan_accepts_market_meeting_volume_threshold():
    m = _make_market(volume_24h=MIN_VOLUME_24H)
    _assert_scan_non_empty([m])


# ---------------------------------------------------------------------------
# scan() — YES price range filter
# ---------------------------------------------------------------------------


def test_scan_ignores_market_below_min_yes_price():
    m = _make_market(yes_price=0.05)
    _assert_scan_empty([m])


def test_scan_ignores_market_above_max_yes_price():
    m = _make_market(yes_price=0.90)
    _assert_scan_empty([m])


def test_scan_accepts_market_at_min_yes_price_boundary():
    m = _make_market(yes_price=MIN_YES_PRICE)
    _assert_scan_non_empty([m])


def test_scan_accepts_market_at_max_yes_price_boundary():
    m = _make_market(yes_price=MAX_YES_PRICE)
    _assert_scan_non_empty([m])


# ---------------------------------------------------------------------------
# scan() — confidence sorting
# ---------------------------------------------------------------------------


def test_scan_sorts_by_confidence_highest_first():
    m1 = _make_market(market_id="m1", condition_id="c1", drop=-0.10)
    m2 = _make_market(market_id="m2", condition_id="c2", drop=-0.20)
    m3 = _make_market(market_id="m3", condition_id="c3", drop=-0.15)

    result = _run_scan([m1, m2, m3])
    assert len(result) == 3
    assert result[0].condition_id == "c2"  # biggest drop → highest confidence
    assert result[1].condition_id == "c3"
    assert result[2].condition_id == "c1"


def test_scan_confidence_capped_at_1_0():
    m = _make_market(drop=-0.50)  # far beyond 0.20 normalization ceiling
    result = _run_scan([m])
    assert len(result) == 1
    assert result[0].confidence == 1.0


def test_scan_confidence_scales_linearly_up_to_20pct_drop():
    m = _make_market(drop=-0.10)  # 10% drop → 0.5 confidence
    result = _run_scan([m])
    assert len(result) == 1
    assert abs(result[0].confidence - 0.5) < 1e-9


# ---------------------------------------------------------------------------
# scan() — SignalCandidate output shape
# ---------------------------------------------------------------------------


def test_scan_emits_yes_side_only():
    m = _make_market()
    result = _run_scan([m])
    assert all(c.side == "YES" for c in result)


def test_scan_candidate_has_correct_strategy_name():
    m = _make_market()
    result = _run_scan([m])
    assert result[0].strategy_name == "momentum_reversal"


def test_scan_candidate_suggested_size_within_bounds():
    m = _make_market()
    result = _run_scan([m], available=1000.0, alloc=0.5)
    # allocated = 500 * 0.05 = 25, within [1, 50]
    assert 1.0 <= result[0].suggested_size_usdc <= 50.0


def test_scan_candidate_metadata_contains_reason():
    m = _make_market()
    result = _run_scan([m])
    assert "reason" in result[0].metadata


# ---------------------------------------------------------------------------
# Helper: _evaluate_market unit tests
# ---------------------------------------------------------------------------


def _ts() -> datetime:
    return datetime.now(timezone.utc)


def test_evaluate_market_returns_none_without_ids():
    assert _evaluate_market(
        {"active": True},
        blacklist=set(),
        min_liquidity=0.0,
        user_context=_make_context(),
        strategy_name="momentum_reversal",
        signal_ts=_ts(),
    ) is None


def test_evaluate_market_returns_none_for_missing_yes_price():
    m = _make_market()
    m.pop("outcomePrices")
    assert _evaluate_market(
        m,
        blacklist=set(),
        min_liquidity=0.0,
        user_context=_make_context(),
        strategy_name="momentum_reversal",
        signal_ts=_ts(),
    ) is None


def test_evaluate_market_returns_none_when_no_drop_data():
    m = _make_market()
    m.pop("oneDayPriceChange")
    assert _evaluate_market(
        m,
        blacklist=set(),
        min_liquidity=0.0,
        user_context=_make_context(),
        strategy_name="momentum_reversal",
        signal_ts=_ts(),
    ) is None


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------


def test_extract_yes_price_from_outcomePrices():
    assert _extract_yes_price({"outcomePrices": ["0.35", "0.65"]}) == pytest.approx(0.35)


def test_extract_yes_price_returns_none_on_missing():
    assert _extract_yes_price({}) is None


def test_extract_yes_price_returns_none_on_bad_value():
    assert _extract_yes_price({"outcomePrices": ["bad"]}) is None


def test_extract_24h_price_change_from_top_level():
    assert _extract_24h_price_change({"oneDayPriceChange": -0.15}) == pytest.approx(-0.15)


def test_extract_24h_price_change_from_nested_priceChange():
    m = {"priceChange": {"oneDay": -0.12}}
    assert _extract_24h_price_change(m) == pytest.approx(-0.12)


def test_extract_24h_price_change_prefers_top_level():
    m = {"oneDayPriceChange": -0.15, "priceChange": {"oneDay": -0.12}}
    assert _extract_24h_price_change(m) == pytest.approx(-0.15)


def test_extract_24h_price_change_returns_none_on_missing():
    assert _extract_24h_price_change({}) is None


def test_extract_liquidity_from_flat_value():
    assert _extract_liquidity({"liquidity": 5000.0}) == pytest.approx(5000.0)


def test_extract_liquidity_from_dict():
    assert _extract_liquidity({"liquidity": {"total": 3000}}) == pytest.approx(3000.0)


def test_extract_liquidity_returns_zero_on_missing():
    assert _extract_liquidity({}) == pytest.approx(0.0)


def test_extract_volume_24h_from_volume_24hr():
    assert _extract_volume_24h({"volume_24hr": "1500"}) == pytest.approx(1500.0)


def test_extract_volume_24h_returns_zero_on_missing():
    assert _extract_volume_24h({}) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_scan(
    markets: list[dict],
    *,
    min_liquidity: float = 0.0,
    blacklisted: list[str] | None = None,
    available: float = 1000.0,
    alloc: float = 0.5,
) -> list[SignalCandidate]:
    s = MomentumReversalStrategy()
    with patch(_PM_PATCH, new=AsyncMock(return_value=markets)):
        return asyncio.get_event_loop().run_until_complete(
            s.scan(
                _make_filters(min_liquidity=min_liquidity, blacklisted=blacklisted),
                _make_context(available=available, alloc=alloc),
            )
        )


def _assert_scan_empty(
    markets: list[dict],
    *,
    min_liquidity: float = 0.0,
    blacklisted: list[str] | None = None,
) -> None:
    assert _run_scan(markets, min_liquidity=min_liquidity, blacklisted=blacklisted) == []


def _assert_scan_non_empty(
    markets: list[dict],
    *,
    min_liquidity: float = 0.0,
    blacklisted: list[str] | None = None,
) -> None:
    result = _run_scan(markets, min_liquidity=min_liquidity, blacklisted=blacklisted)
    assert len(result) > 0
