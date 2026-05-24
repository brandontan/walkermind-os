"""Hermetic tests for ConfluenceScalperStrategy (issue #1267).

Coverage:
    * ConfluenceScalperStrategy implements BaseStrategy contract
    * Strategy is registered by bootstrap_default_strategies()
    * Risk profile compatibility: balanced / aggressive / custom only
    * Empty / invalid / errored market data returns [], not exception
    * Closed / inactive / non-accepting markets are ignored
    * Blacklisted markets are ignored
    * Mid-band YES price filter, drift magnitude band, liquidity + volume floors
    * Side selection: dip -> YES, rise -> NO
    * Confidence sorting (highest first), candidate metadata contains
      score_components + reason
    * default_tp_sl() returns positive scalp tuple
    * evaluate_exit() returns hold

No network, no DB, no broker. Polymarket API calls are patched with
unittest.mock.AsyncMock throughout.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from projects.polymarket.crusaderbot.domain.strategy import (
    StrategyRegistry,
    bootstrap_default_strategies,
)
from projects.polymarket.crusaderbot.domain.strategy.base import BaseStrategy
from projects.polymarket.crusaderbot.domain.strategy.strategies.confluence_scalper import (
    DEFAULT_SL_PCT,
    DEFAULT_TP_PCT,
    MAX_ABS_DRIFT,
    MAX_YES_PRICE,
    MIN_ABS_DRIFT,
    MIN_LIQUIDITY_USDC,
    MIN_VOLUME_24H,
    MIN_YES_PRICE,
    ConfluenceScalperStrategy,
)
from projects.polymarket.crusaderbot.domain.strategy.types import (
    ExitDecision,
    MarketFilters,
    SignalCandidate,
    UserContext,
)

_PM_PATCH = (
    "projects.polymarket.crusaderbot.domain.strategy.strategies"
    ".confluence_scalper.pm.get_markets"
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
    risk_profile: str = "balanced",
) -> UserContext:
    return UserContext(
        user_id="u1",
        sub_account_id="s1",
        risk_profile=risk_profile,
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
    yes_price: float = 0.50,
    drift: float = -0.05,
    liquidity: float = 20_000.0,
    volume_24h: float = 10_000.0,
    # Defaults satisfy the Issue #1269 eligibility gate (category=Crypto +
    # asset whitelist) AND the short-duration timeframe gate (5m/15m) which are
    # both enforced inside ConfluenceScalperStrategy. The default slug carries a
    # "5-minute" keyword (no asset token, so the asset gate still keys off the
    # question). Override per test when validating a rejection path.
    category: str = "Crypto",
    question: str = "Will BTC hit a new high?",
    slug: str = "up-or-down-5-minute",
) -> dict:
    return {
        "id": market_id,
        "conditionId": condition_id,
        "active": active,
        "closed": closed,
        "acceptingOrders": accepting_orders,
        "outcomePrices": [str(yes_price), str(round(1.0 - yes_price, 4))],
        "oneDayPriceChange": drift,
        "liquidity": liquidity,
        "volume_24hr": volume_24h,
        "category": category,
        "question": question,
        "slug": slug,
    }


def _run_scan(
    markets: list[dict],
    *,
    min_liquidity: float = 0.0,
    blacklisted: list[str] | None = None,
    available: float = 1000.0,
    alloc: float = 0.5,
) -> list[SignalCandidate]:
    s = ConfluenceScalperStrategy()
    with patch(_PM_PATCH, new=AsyncMock(return_value=markets)):
        return asyncio.run(
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
) -> list[SignalCandidate]:
    result = _run_scan(markets, min_liquidity=min_liquidity, blacklisted=blacklisted)
    assert len(result) > 0
    return result


# ---------------------------------------------------------------------------
# Contract compliance
# ---------------------------------------------------------------------------


def test_implements_base_strategy():
    assert issubclass(ConfluenceScalperStrategy, BaseStrategy)


def test_instantiates_with_required_attributes():
    s = ConfluenceScalperStrategy()
    assert s.name == "confluence_scalper"
    assert s.version
    assert s.risk_profile_compatibility


def test_risk_profile_compatibility_excludes_conservative():
    compat = ConfluenceScalperStrategy.risk_profile_compatibility
    assert "conservative" not in compat
    assert set(compat) == {"balanced", "aggressive", "custom"}


def test_default_tp_sl_returns_positive_scalp_tuple():
    tp, sl = ConfluenceScalperStrategy().default_tp_sl()
    assert isinstance(tp, float)
    assert isinstance(sl, float)
    assert tp == DEFAULT_TP_PCT
    assert sl == DEFAULT_SL_PCT
    assert tp > 0.0 and sl > 0.0
    assert tp <= 0.15 and sl <= 0.10


def test_evaluate_exit_returns_hold():
    result = asyncio.run(ConfluenceScalperStrategy().evaluate_exit({}))
    assert result == ExitDecision(should_exit=False, reason="hold")


# ---------------------------------------------------------------------------
# Registry bootstrap
# ---------------------------------------------------------------------------


def test_bootstrap_registers_confluence_scalper():
    reg = bootstrap_default_strategies()
    names = [s["name"] for s in reg.list_available()]
    assert "confluence_scalper" in names


def test_bootstrap_preserves_existing_strategies():
    reg = bootstrap_default_strategies()
    names = {s["name"] for s in reg.list_available()}
    assert {
        "copy_trade",
        "signal_following",
        "momentum_reversal",
        "confluence_scalper",
    } <= names


def test_bootstrap_is_idempotent():
    bootstrap_default_strategies()
    bootstrap_default_strategies()
    reg = StrategyRegistry.instance()
    count = sum(1 for s in reg.list_available() if s["name"] == "confluence_scalper")
    assert count == 1


def test_registry_get_compatible_returns_for_balanced():
    reg = bootstrap_default_strategies()
    compat = reg.get_compatible("balanced")
    assert any(s.name == "confluence_scalper" for s in compat)


def test_registry_get_compatible_excludes_for_conservative():
    reg = bootstrap_default_strategies()
    compat = reg.get_compatible("conservative")
    assert not any(s.name == "confluence_scalper" for s in compat)


# ---------------------------------------------------------------------------
# scan() — failure + empty paths
# ---------------------------------------------------------------------------


def test_scan_returns_empty_when_get_markets_returns_empty():
    s = ConfluenceScalperStrategy()
    with patch(_PM_PATCH, new=AsyncMock(return_value=[])):
        result = asyncio.run(s.scan(_make_filters(), _make_context()))
    assert result == []


def test_scan_returns_empty_when_get_markets_raises():
    s = ConfluenceScalperStrategy()
    with patch(_PM_PATCH, new=AsyncMock(side_effect=RuntimeError("network down"))):
        result = asyncio.run(s.scan(_make_filters(), _make_context()))
    assert result == []


def test_scan_skips_malformed_market_dict_without_exception():
    bad_markets = [{"garbage": True}, None, {}, {"id": "x"}]
    assert _run_scan(bad_markets) == []


# ---------------------------------------------------------------------------
# scan() — Issue #1269 eligibility gate (crypto-only + asset whitelist)
# ---------------------------------------------------------------------------


def test_scan_skips_non_short_duration_market():
    # A market that names a crypto asset but is NOT a short-duration candle
    # (no 5m/15m interval in its text) must self-skip inside scan() — the
    # timeframe gate is fail-closed. e.g. a long-horizon political "ban" market.
    _assert_scan_empty([
        _make_market(
            category="Politics",
            question="Will BTC ban pass?",
            slug="btc-ban-referendum-2026",
        )
    ])


def test_scan_skips_off_whitelist_crypto_asset():
    _assert_scan_empty([_make_market(question="Will ADA hit \\$10?")])


def test_scan_keeps_each_whitelisted_asset():
    for question in (
        "Will BTC hit a new high?",
        "Will ETH gas drop?",
        "Will SOL TVL grow?",
        "Will XRP ETF land?",
        "Will DOGE moon?",
        "Will BNB outperform?",
        "Will HYPE pump?",
    ):
        m = _make_market(market_id="m_" + question[:4], condition_id="c_" + question[:4],
                         question=question)
        result = _run_scan([m])
        assert len(result) == 1, question


# ---------------------------------------------------------------------------
# scan() — market status filters
# ---------------------------------------------------------------------------


def test_scan_ignores_inactive_market():
    _assert_scan_empty([_make_market(active=False)])


def test_scan_ignores_closed_market():
    _assert_scan_empty([_make_market(closed=True)])


def test_scan_ignores_non_accepting_market():
    _assert_scan_empty([_make_market(accepting_orders=False)])


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
# scan() — mid-band YES price filter
# ---------------------------------------------------------------------------


def test_scan_ignores_market_below_min_yes_price():
    _assert_scan_empty([_make_market(yes_price=MIN_YES_PRICE - 0.01)])


def test_scan_ignores_market_above_max_yes_price():
    _assert_scan_empty([_make_market(yes_price=MAX_YES_PRICE + 0.01)])


def test_scan_accepts_market_at_min_yes_price_boundary():
    _assert_scan_non_empty([_make_market(yes_price=MIN_YES_PRICE)])


def test_scan_accepts_market_at_max_yes_price_boundary():
    _assert_scan_non_empty([_make_market(yes_price=MAX_YES_PRICE)])


# ---------------------------------------------------------------------------
# scan() — drift magnitude band
# ---------------------------------------------------------------------------


def test_scan_ignores_market_with_no_drift_data():
    m = _make_market()
    m.pop("oneDayPriceChange")
    _assert_scan_empty([m])


def test_scan_ignores_market_below_min_drift():
    _assert_scan_empty([_make_market(drift=-(MIN_ABS_DRIFT - 0.001))])


def test_scan_ignores_market_above_max_drift_treated_as_trend_break():
    _assert_scan_empty([_make_market(drift=-(MAX_ABS_DRIFT + 0.001))])


def test_scan_accepts_market_at_min_drift_boundary():
    _assert_scan_non_empty([_make_market(drift=-MIN_ABS_DRIFT)])


def test_scan_accepts_market_at_max_drift_boundary():
    _assert_scan_non_empty([_make_market(drift=-MAX_ABS_DRIFT)])


# ---------------------------------------------------------------------------
# scan() — liquidity + volume floors
# ---------------------------------------------------------------------------


def test_scan_ignores_market_below_internal_liquidity_floor():
    _assert_scan_empty([_make_market(liquidity=MIN_LIQUIDITY_USDC - 1.0)])


def test_scan_ignores_market_below_user_filter_liquidity_when_higher():
    # internal floor 5k, user filter 10k -> 8k must be filtered
    _assert_scan_empty([_make_market(liquidity=8_000.0)], min_liquidity=10_000.0)


def test_scan_accepts_market_at_internal_liquidity_floor():
    _assert_scan_non_empty([_make_market(liquidity=MIN_LIQUIDITY_USDC)])


def test_scan_ignores_market_below_volume_floor():
    _assert_scan_empty([_make_market(volume_24h=MIN_VOLUME_24H - 1.0)])


def test_scan_accepts_market_at_volume_floor():
    _assert_scan_non_empty([_make_market(volume_24h=MIN_VOLUME_24H)])


# ---------------------------------------------------------------------------
# scan() — side selection from drift direction
# ---------------------------------------------------------------------------


def test_scan_emits_yes_side_on_dip():
    result = _assert_scan_non_empty([_make_market(drift=-0.05)])
    assert result[0].side == "YES"


def test_scan_emits_no_side_on_pop():
    result = _assert_scan_non_empty([_make_market(drift=0.05)])
    assert result[0].side == "NO"


# ---------------------------------------------------------------------------
# scan() — SignalCandidate output shape
# ---------------------------------------------------------------------------


def test_scan_candidate_strategy_name_is_confluence_scalper():
    result = _assert_scan_non_empty([_make_market()])
    assert result[0].strategy_name == "confluence_scalper"


def test_scan_candidate_metadata_contains_score_components_and_reason():
    result = _assert_scan_non_empty([_make_market()])
    meta = result[0].metadata
    assert "score_components" in meta
    components = meta["score_components"]
    for key in ("drift", "liquidity", "volume", "midband"):
        assert key in components
        assert 0.0 <= components[key] <= 1.0
    assert "reason" in meta
    assert isinstance(meta["reason"], str) and meta["reason"]


def test_scan_candidate_reasoning_is_populated():
    result = _assert_scan_non_empty([_make_market()])
    assert result[0].reasoning
    assert "Scalp" in result[0].reasoning


def test_scan_candidate_confidence_in_unit_interval():
    result = _assert_scan_non_empty([_make_market()])
    assert 0.0 <= result[0].confidence <= 1.0


def test_scan_candidate_suggested_size_within_bounds():
    result = _run_scan([_make_market()], available=1000.0, alloc=0.5)
    assert len(result) > 0
    # allocated = 500 * 0.04 = 20, within [1, 25]
    assert 1.0 <= result[0].suggested_size_usdc <= 25.0


def test_scan_sorts_candidates_by_confidence_descending():
    # midband_score weight 0.20, drift_score weight 0.35
    # m_best: drift at sweet spot (-0.05), price 0.50, high liq/vol -> highest
    # m_mid:  drift far from sweet spot (-0.02), price 0.50, high liq/vol
    # m_low:  drift far + off-band price -> lowest
    m_best = _make_market(market_id="m_best", condition_id="c_best", drift=-0.05, yes_price=0.50)
    m_mid = _make_market(market_id="m_mid", condition_id="c_mid", drift=-0.02, yes_price=0.50)
    m_low = _make_market(market_id="m_low", condition_id="c_low", drift=-0.02, yes_price=0.35)
    result = _run_scan([m_low, m_mid, m_best])
    assert len(result) == 3
    assert result[0].market_id == "m_best"
    # m_low has both worse drift and worse midband
    assert result[-1].market_id == "m_low"
