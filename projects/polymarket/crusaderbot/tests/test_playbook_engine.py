"""PLAYBOOK engine — Phase-1 FOUNDATION unit tests.

Covers the market quality filter, native signal formulas, the precedence-claim
router, the Closing Edge module, correlation keys, the PlaybookStrategy adapter,
and preset/registry/backend wiring. Hermetic — no DB, no network.
"""
from __future__ import annotations

import asyncio

import pytest

from projects.polymarket.crusaderbot.domain.playbook.correlation import (
    cluster_key,
    score_correlation,
)
from projects.polymarket.crusaderbot.domain.playbook.market_quality import (
    evaluate_market_quality,
)
from projects.polymarket.crusaderbot.domain.playbook.modules import (
    ClosingEdgeModule,
    InjuryAlphaModule,
    MarketSnapshot,
    PublicFadeModule,
    SharpMoneyModule,
)
from projects.polymarket.crusaderbot.domain.playbook.router import (
    DEFAULT_MODULE_ORDER,
    PlaybookRouter,
)
from projects.polymarket.crusaderbot.domain.playbook.signals import (
    EVENT_TTL,
    LINE_MOVEMENT,
    SHARP_MONEY,
    compute_signal_bundle,
    event_ttl_reading,
    line_movement_reading,
    liquidity_reading,
    market_sentiment_reading,
    sharp_money_reading,
)
from projects.polymarket.crusaderbot.domain.strategy.registry import (
    StrategyRegistry,
    bootstrap_default_strategies,
)
from projects.polymarket.crusaderbot.domain.strategy.strategies.playbook import (
    PlaybookStrategy,
)
from projects.polymarket.crusaderbot.domain.strategy.types import (
    MarketFilters,
    UserContext,
)


def _snapshot(**over) -> MarketSnapshot:
    base = dict(
        market_id="m1",
        condition_id="c1",
        sport="NFL",
        fair_price=0.60,
        yes_ask=0.55,
        no_ask=0.46,
        seconds_to_event=600.0,
        liquidity_usdc=20_000.0,
        suggested_size_usdc=20.0,
        cluster_key="nfl:kc@buf",
    )
    base.update(over)
    return MarketSnapshot(**base)


def _bundle(snap: MarketSnapshot):
    return compute_signal_bundle(
        market_id=snap.market_id,
        mid_now=snap.fair_price,
        mid_prev=snap.fair_price,
        noise_sigma=0.05,
        liquidity_usdc=snap.liquidity_usdc,
        spread=0.03,
        seconds_to_event=snap.seconds_to_event,
        close_window_sec=1_800.0,
        buy_flow_usdc=0.0,
        sell_flow_usdc=0.0,
        sharp_signed_usdc=0.0,
        total_flow_usdc=0.0,
    )


def _user() -> UserContext:
    return UserContext(
        user_id="u1",
        sub_account_id="s1",
        risk_profile="balanced",
        capital_allocation_pct=0.40,
        available_balance_usdc=1_000.0,
        equity_usdc=1_000.0,
    )


# --------------------------------------------------------------------------- #
# Market quality filter
# --------------------------------------------------------------------------- #


def test_market_quality_accepts_healthy_book():
    res = evaluate_market_quality(
        liquidity_usdc=20_000.0, best_bid=0.54, best_ask=0.57,
        top_depth_usdc=500.0, resolution_clear=True, event_integrity_ok=True,
    )
    assert res.accepted and res.reason == "ok"


@pytest.mark.parametrize(
    "kw,reason_prefix",
    [
        (dict(event_integrity_ok=False), "event_integrity"),
        (dict(resolution_clear=False), "resolution_unclear"),
        (dict(liquidity_usdc=100.0), "liquidity_"),
        (dict(best_bid=0.50, best_ask=0.65), "spread_"),
        (dict(top_depth_usdc=10.0), "depth_"),
    ],
)
def test_market_quality_rejects(kw, reason_prefix):
    base = dict(
        liquidity_usdc=20_000.0, best_bid=0.54, best_ask=0.57,
        top_depth_usdc=500.0, resolution_clear=True, event_integrity_ok=True,
    )
    base.update(kw)
    res = evaluate_market_quality(**base)
    assert not res.accepted
    assert res.reason.startswith(reason_prefix)


# --------------------------------------------------------------------------- #
# Signal formulas
# --------------------------------------------------------------------------- #


def test_signal_confidence_clamped_and_formulas():
    assert line_movement_reading(0.6, 0.5, 0.05).confidence == 1.0  # 0.1/0.05 → clamp 1
    assert line_movement_reading(0.5, 0.5, 0.0).confidence == 0.0  # sigma<=0
    assert event_ttl_reading(900.0, 1_800.0).confidence == pytest.approx(0.5)
    assert event_ttl_reading(3_600.0, 1_800.0).confidence == 0.0  # far away
    assert market_sentiment_reading(8_000.0, 2_000.0).confidence == pytest.approx(0.6)
    assert sharp_money_reading(0.0, 0.0).confidence == 0.0  # no flow
    assert 0.0 <= liquidity_reading(20_000.0, 0.03).confidence <= 1.0


def test_signal_reading_rejects_bad_confidence():
    from projects.polymarket.crusaderbot.domain.playbook.signals import SignalReading
    # out-of-range confidence raises
    with pytest.raises(ValueError):
        SignalReading(LINE_MOVEMENT, 0.0, 1.5, native=True)
    # extreme inputs clamp rather than raise
    assert sharp_money_reading(5.0, 1.0).confidence == 1.0


def test_weighted_score_normalised():
    snap = _snapshot()
    b = _bundle(snap)
    score = b.weighted_score({EVENT_TTL: 0.5, LINE_MOVEMENT: 0.5})
    assert 0.0 <= score <= 1.0


# --------------------------------------------------------------------------- #
# Router + Closing Edge module
# --------------------------------------------------------------------------- #


def test_router_default_order_is_precedence():
    assert PlaybookRouter().module_names == DEFAULT_MODULE_ORDER


def test_router_routes_to_closing_edge_on_stale_book():
    snap = _snapshot()  # 600s to event, YES edge 0.05
    res = PlaybookRouter().route(snap, _bundle(snap))
    assert res.routed
    assert res.module == "closing_edge"
    assert res.decision.side == "YES"
    assert res.decision.confidence > 0.0


def test_router_no_claim_when_ttl_outside_window():
    snap = _snapshot(seconds_to_event=10_000.0)
    res = PlaybookRouter().route(snap, _bundle(snap))
    assert not res.routed
    # every module skipped with a reason
    assert dict(res.skipped)["closing_edge"].startswith("ttl_outside")


def test_router_no_claim_when_no_edge():
    # fair == ask on both sides → zero edge
    snap = _snapshot(fair_price=0.55, yes_ask=0.55, no_ask=0.45)
    res = PlaybookRouter().route(snap, _bundle(snap))
    assert not res.routed


def test_stub_modules_never_claim_in_phase1():
    snap = _snapshot()
    b = _bundle(snap)
    for mod in (SharpMoneyModule(), PublicFadeModule(), InjuryAlphaModule()):
        assert mod.evaluate(snap, b).claimed is False


def test_closing_edge_force_exit_seconds():
    assert ClosingEdgeModule().force_exit_seconds() == 60.0


def test_closing_edge_picks_higher_edge_side():
    # NO edge (1-0.4) - 0.50 = 0.10 vs YES 0.40 - 0.39 = 0.01 → NO wins
    snap = _snapshot(fair_price=0.40, yes_ask=0.39, no_ask=0.50)
    res = PlaybookRouter().route(snap, _bundle(snap))
    assert res.routed and res.decision.side == "NO"


# --------------------------------------------------------------------------- #
# Correlation
# --------------------------------------------------------------------------- #


def test_cluster_key_and_correlation():
    k1 = cluster_key(sport="NBA", event_id="evt-1")
    k2 = cluster_key(sport="NBA", event_id="evt-1")
    assert k1 == k2 == "nba:evt-1"
    assert score_correlation(k1, k2).correlated is True
    assert score_correlation(k1, "nba:evt-2").correlated is False
    # unclustered never self-correlates
    u = cluster_key(sport="NBA")
    assert u == "unclustered"
    assert score_correlation(u, u).correlated is False


# --------------------------------------------------------------------------- #
# PlaybookStrategy adapter
# --------------------------------------------------------------------------- #


def test_strategy_evaluate_snapshot_emits_candidate():
    s = PlaybookStrategy()
    cand = s.evaluate_snapshot(_snapshot(), _user())
    assert cand is not None
    assert cand.strategy_name == "playbook"
    assert cand.side == "YES"
    assert cand.metadata["selected_module"] == "closing_edge"
    assert cand.metadata["engine"] == "playbook"
    assert cand.metadata["cluster_key"] == "nfl:kc@buf"


def test_strategy_default_tp_sl():
    assert PlaybookStrategy().default_tp_sl() == (0.25, 0.12)


def test_strategy_evaluate_exit_force_exit_and_hold():
    s = PlaybookStrategy()
    # force-exit when seconds_to_close <= force threshold
    ex = asyncio.run(s.evaluate_exit({
        "strategy_metadata": {"force_exit_at_event_sec": 60.0},
        "seconds_to_close": 45.0,
    }))
    assert ex.should_exit and ex.reason == "strategy_exit"
    # hold when far from event and price healthy
    hold = asyncio.run(s.evaluate_exit({
        "strategy_metadata": {"force_exit_at_event_sec": 60.0},
        "seconds_to_close": 600.0,
        "current_price": 0.55,
    }))
    assert not hold.should_exit and hold.reason == "hold"


# --------------------------------------------------------------------------- #
# Registry + preset + backend wiring
# --------------------------------------------------------------------------- #


def test_registry_registers_playbook():
    StrategyRegistry._reset_for_tests()
    reg = bootstrap_default_strategies()
    s = reg.get("playbook")
    assert s.name == "playbook"
    assert "balanced" in s.risk_profile_compatibility


def test_preset_registered_and_visible():
    # Phase-2a: playbook is registered, routable, AND user-selectable again now
    # that its scan dispatch (Phase B4) is wired.
    from projects.polymarket.crusaderbot.domain.preset.presets import (
        PRESET_ORDER,
        VISIBLE_PRESET_ORDER,
        get_preset,
    )
    p = get_preset("playbook")
    assert p is not None and p.strategies == ("playbook",)
    assert "playbook" in PRESET_ORDER
    assert "playbook" in VISIBLE_PRESET_ORDER


def test_playbook_activatable_phase2():
    # Dispatch is wired (Phase-2a) → playbook is activatable; HIDDEN_PRESETS empty.
    from projects.polymarket.crusaderbot.domain.preset.presets import (
        HIDDEN_PRESETS,
        PRESETS,
        is_activatable,
    )
    assert "playbook" in PRESETS
    assert "playbook" not in HIDDEN_PRESETS
    assert is_activatable("playbook") is True
    assert is_activatable("candle_auto") is True
    assert is_activatable("nonexistent") is False


def test_playbook_dispatch_wired_in_scan_loop():
    # The scan loop allows the playbook strategy under the playbook preset.
    from projects.polymarket.crusaderbot.services.signal_scan import signal_scan_job as ssj
    assert "playbook" in ssj._PRESET_ALLOWED
    assert ssj._PLAYBOOK_STRATEGY_NAME in ssj._PRESET_ALLOWED["playbook"]
    assert ssj._PLAYBOOK_STRATEGY_NAME in ssj._DOMAIN_STRATEGY_NAMES
    assert ssj._preset_allows("playbook", ssj._PLAYBOOK_STRATEGY_NAME) is True
    assert ssj._preset_allows("candle_auto", ssj._PLAYBOOK_STRATEGY_NAME) is False


def test_backend_and_bot_roster_in_sync():
    from projects.polymarket.crusaderbot.webtrader.backend import router as r
    assert r._PRESET_TO_STRATEGY["playbook"] == "playbook"
    assert "playbook" in r._PRESET_PARAMS
    assert "playbook" in r._ADMIN_STRATEGIES
    assert r._PRESET_LOCKED_CATEGORY["playbook"] == "Sports"
    from projects.polymarket.crusaderbot.bot.presets import PRESET_CONFIG, PRESET_ORDER
    assert "playbook" in PRESET_CONFIG
    assert "playbook" in PRESET_ORDER


# --------------------------------------------------------------------------- #
# Phase-2a: sports snapshot fetch + helpers
# --------------------------------------------------------------------------- #


def test_playbook_snapshot_helpers():
    from projects.polymarket.crusaderbot.domain.strategy.strategies import playbook as pbs
    assert pbs._is_sports_category("nfl football") is True
    assert pbs._is_sports_category("crypto finance") is False
    assert pbs._parse_iso("2026-06-03T00:00:00Z") is not None
    assert pbs._parse_iso(None) is None
    assert pbs._extract_token_ids({"clobTokenIds": '["a","b"]'}) == ["a", "b"]
    assert pbs._extract_token_ids({"tokens": [{"token_id": "x"}, {"token_id": "y"}]}) == ["x", "y"]
    assert pbs._extract_token_ids({}) == []
    assert pbs._best_ask({"asks": [{"price": "0.55"}, {"price": "0.57"}]}) == 0.55
    assert pbs._best_bid({"bids": [{"price": "0.54"}, {"price": "0.50"}]}) == 0.54
    assert pbs._best_ask({"asks": []}) is None
    # fair prefers Gamma consensus over book mid
    assert pbs._fair_price(0.54, 0.55, {"outcomePrices": '["0.60","0.40"]'}) == 0.60
    assert pbs._fair_price(0.54, 0.56, {}) == pytest.approx(0.55)


def test_playbook_scan_builds_candidates_from_mocked_feed(monkeypatch):
    import asyncio
    from datetime import datetime, timedelta, timezone

    from projects.polymarket.crusaderbot.integrations import polymarket as pm

    start = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    market = {
        "id": "m1",
        "conditionId": "cond1",
        "slug": "nfl-kc-buf",
        "category": "nfl football",
        "gameStartTime": start,
        "clobTokenIds": '["yes_tok","no_tok"]',
        "liquidity": 20000,
        # Gamma consensus says YES fair 0.60; CLOB ask 0.55 below it → stale-book edge.
        "outcomePrices": '["0.60","0.40"]',
    }

    async def fake_events(limit=200):
        return [market]

    async def fake_book(token_id):
        if token_id == "yes_tok":
            return {"bids": [{"price": "0.54", "size": "100"}], "asks": [{"price": "0.55", "size": "100"}]}
        return {"bids": [{"price": "0.44", "size": "100"}], "asks": [{"price": "0.46", "size": "100"}]}

    monkeypatch.setattr(pm, "get_events_with_markets", fake_events)
    monkeypatch.setattr(pm, "get_book", fake_book)

    s = PlaybookStrategy()
    mf = MarketFilters(categories=[], min_liquidity=0.0, max_time_to_resolution_days=7, blacklisted_market_ids=[])
    cands = asyncio.run(s.scan(mf, _user()))
    assert len(cands) == 1
    assert cands[0].market_id == "m1"
    assert cands[0].side == "YES"
    assert cands[0].metadata["selected_module"] == "closing_edge"
    assert cands[0].suggested_size_usdc > 0


def test_playbook_scan_empty_on_fetch_error(monkeypatch):
    import asyncio

    from projects.polymarket.crusaderbot.integrations import polymarket as pm

    async def boom(limit=200):
        raise RuntimeError("gamma down")

    monkeypatch.setattr(pm, "get_events_with_markets", boom)
    s = PlaybookStrategy()
    mf = MarketFilters(categories=[], min_liquidity=0.0, max_time_to_resolution_days=7, blacklisted_market_ids=[])
    assert asyncio.run(s.scan(mf, _user())) == []


def test_playbook_skips_markets_outside_close_window(monkeypatch):
    import asyncio
    from datetime import datetime, timedelta, timezone

    from projects.polymarket.crusaderbot.integrations import polymarket as pm

    far = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
    market = {
        "id": "m2", "conditionId": "c2", "category": "nba basketball",
        "gameStartTime": far, "clobTokenIds": '["y","n"]',
        "liquidity": 20000, "outcomePrices": '["0.60","0.40"]',
    }

    async def fake_events(limit=200):
        return [market]

    async def fake_book(token_id):  # pragma: no cover - should never be called
        raise AssertionError("book fetched for out-of-window market")

    monkeypatch.setattr(pm, "get_events_with_markets", fake_events)
    monkeypatch.setattr(pm, "get_book", fake_book)
    s = PlaybookStrategy()
    mf = MarketFilters(categories=[], min_liquidity=0.0, max_time_to_resolution_days=7, blacklisted_market_ids=[])
    assert asyncio.run(s.scan(mf, _user())) == []
