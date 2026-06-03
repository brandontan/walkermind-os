"""PLAYBOOK feed-dependent modules — Phase-2d Injury Alpha / Phase-2e Public Fade.

Covers the two feed signal formulas, the Injury Alpha + Public Fade module gates,
router precedence with feed data attached, the Odds API / ESPN reference parsers,
and the ``build_sports_feed`` factory + strategy feed-attach. Hermetic — no DB, no
network (HTTP adapters are exercised through their pure parsers and a fake feed).
"""
from __future__ import annotations

import asyncio
import time

from projects.polymarket.crusaderbot.domain.playbook.feeds import (
    InjuryEvent,
    NullFeed,
    PublicFlow,
)
from projects.polymarket.crusaderbot.domain.playbook.feeds_http import (
    EspnInjuryFeed,
    FeedTarget,
    OddsApiFeed,
    build_sports_feed,
    decimal_to_implied,
    devig_two_way,
    parse_espn_injury_payload,
    parse_oddsapi_model_probability,
    parse_oddsapi_public_flow,
)
from projects.polymarket.crusaderbot.domain.playbook.modules import (
    INJURY_MIN_TTL_SEC,
    PUBLIC_FADE_MIN_TTL_SEC,
    InjuryAlphaModule,
    MarketSnapshot,
    PublicFadeModule,
)
from projects.polymarket.crusaderbot.domain.playbook.router import PlaybookRouter
from projects.polymarket.crusaderbot.domain.playbook.signals import (
    NEWS_INJURY,
    PUBLIC_FLOW,
    compute_signal_bundle,
    news_injury_reading,
    public_flow_reading,
)
from projects.polymarket.crusaderbot.domain.strategy.strategies.playbook import (
    PlaybookStrategy,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _snapshot(**over) -> MarketSnapshot:
    base = dict(
        market_id="m1",
        condition_id="c1",
        sport="NBA",
        fair_price=0.55,
        yes_ask=0.55,
        no_ask=0.46,
        seconds_to_event=7_200.0,  # 2h — outside both close windows
        liquidity_usdc=20_000.0,
        suggested_size_usdc=20.0,
        cluster_key="nba:lal@bos",
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
        injury_present=snap.injury_present,
        injury_severity=snap.injury_severity,
        injury_detected_age_sec=snap.injury_detected_age_sec,
        injury_repriced_fraction=snap.injury_repriced_fraction,
        injury_yes_favored=snap.injury_yes_favored,
        public_pct_on_side=snap.public_pct_on_side,
        public_side=snap.public_side,
    )


class _FakeFeed:
    """Minimal SportsFeed returning preset injury / public flow objects."""

    def __init__(self, injury: InjuryEvent | None = None, public: PublicFlow | None = None):
        self._injury, self._public = injury, public

    async def get_injury_event(self, market_id: str):
        return self._injury

    async def get_public_flow(self, market_id: str):
        return self._public

    async def get_model_probability(self, market_id: str, side: str):
        return None


# --------------------------------------------------------------------------- #
# Signal formulas
# --------------------------------------------------------------------------- #
def test_news_injury_reading_absent_is_neutral():
    r = news_injury_reading(
        present=False, severity=0.0, detected_age_sec=0.0,
        repriced_fraction=0.0, yes_favored=True,
    )
    assert r.confidence == 0.0 and r.value == 0.0 and r.native is False


def test_news_injury_reading_sign_and_decay():
    fresh = news_injury_reading(
        present=True, severity=1.0, detected_age_sec=0.0,
        repriced_fraction=0.0, yes_favored=True,
    )
    assert fresh.confidence == 1.0 and fresh.value > 0  # YES-favoring → positive
    no_side = news_injury_reading(
        present=True, severity=1.0, detected_age_sec=0.0,
        repriced_fraction=0.0, yes_favored=False,
    )
    assert no_side.value < 0  # NO-favoring → negative
    # Recency decay: half the max age → half confidence.
    half = news_injury_reading(
        present=True, severity=1.0, detected_age_sec=1_800.0,
        repriced_fraction=0.0, yes_favored=True, max_age_sec=3_600.0,
    )
    assert abs(half.confidence - 0.5) < 1e-9
    # Repricing decay: fully repriced → no edge left.
    gone = news_injury_reading(
        present=True, severity=1.0, detected_age_sec=0.0,
        repriced_fraction=1.0, yes_favored=True,
    )
    assert gone.confidence == 0.0


def test_public_flow_reading_imbalance_and_sign():
    even = public_flow_reading(public_pct_on_side=0.5, side="YES")
    assert even.confidence == 0.0
    heavy = public_flow_reading(public_pct_on_side=1.0, side="YES")
    assert heavy.confidence == 1.0 and heavy.value > 0
    no_side = public_flow_reading(public_pct_on_side=0.8, side="NO")
    assert no_side.value < 0  # signed toward the public side (NO)
    assert public_flow_reading(public_pct_on_side=0.9, side="").confidence == 0.0


def test_compute_bundle_keeps_neutral_without_feed_inputs():
    snap = _snapshot()
    b = _bundle(snap)
    assert b.get(NEWS_INJURY).confidence == 0.0
    assert b.get(PUBLIC_FLOW).confidence == 0.0


# --------------------------------------------------------------------------- #
# Injury Alpha module
# --------------------------------------------------------------------------- #
def test_injury_alpha_claims_when_fresh_and_unrepriced():
    snap = _snapshot(
        injury_present=True, injury_severity=0.9, injury_detected_age_sec=300.0,
        injury_repriced_fraction=0.0, injury_yes_favored=False,  # injury hurts YES → buy NO
        seconds_to_event=7_200.0,
    )
    dec = InjuryAlphaModule().evaluate(snap, _bundle(snap))
    assert dec.claimed and dec.side == "NO"
    assert dec.tp_pct == 0.30 and dec.sl_pct == 0.15
    assert dec.metadata["module"] == "injury_alpha"


def test_injury_alpha_abstains_inside_1h_window():
    snap = _snapshot(
        injury_present=True, injury_severity=0.9, injury_detected_age_sec=60.0,
        seconds_to_event=INJURY_MIN_TTL_SEC - 1.0,
    )
    assert InjuryAlphaModule().evaluate(snap, _bundle(snap)).claimed is False


def test_injury_alpha_abstains_when_already_repriced():
    snap = _snapshot(
        injury_present=True, injury_severity=0.9, injury_detected_age_sec=60.0,
        injury_repriced_fraction=0.8, seconds_to_event=7_200.0,
    )
    dec = InjuryAlphaModule().evaluate(snap, _bundle(snap))
    assert dec.claimed is False and "repriced" in dec.reasoning


def test_injury_alpha_abstains_without_event():
    snap = _snapshot(seconds_to_event=7_200.0)
    assert InjuryAlphaModule().evaluate(snap, _bundle(snap)).claimed is False


# --------------------------------------------------------------------------- #
# Public Fade module
# --------------------------------------------------------------------------- #
def test_public_fade_claims_opposite_side_on_overreaction():
    # Public 80% on YES while market implies 55% → overreaction; fade → buy NO.
    snap = _snapshot(
        public_pct_on_side=0.80, public_side="YES", fair_price=0.55,
        seconds_to_event=7_200.0,
    )
    dec = PublicFadeModule().evaluate(snap, _bundle(snap))
    assert dec.claimed and dec.side == "NO"
    assert dec.metadata["overreaction"] > 0


def test_public_fade_abstains_inside_closing_window():
    snap = _snapshot(
        public_pct_on_side=0.80, public_side="YES", fair_price=0.55,
        seconds_to_event=PUBLIC_FADE_MIN_TTL_SEC - 1.0,
    )
    assert PublicFadeModule().evaluate(snap, _bundle(snap)).claimed is False


def test_public_fade_abstains_below_theta():
    snap = _snapshot(public_pct_on_side=0.55, public_side="YES", seconds_to_event=7_200.0)
    assert PublicFadeModule().evaluate(snap, _bundle(snap)).claimed is False


def test_public_fade_abstains_without_overreaction():
    # Public 70% but market already implies 75% on that side → no overreaction.
    snap = _snapshot(
        public_pct_on_side=0.70, public_side="YES", fair_price=0.75,
        seconds_to_event=7_200.0,
    )
    dec = PublicFadeModule().evaluate(snap, _bundle(snap))
    assert dec.claimed is False and "overreaction" in dec.reasoning


# --------------------------------------------------------------------------- #
# Router precedence with feed data
# --------------------------------------------------------------------------- #
def test_router_injury_alpha_outranks_closing_edge():
    # Inside the closing window AND an injury present: injury_alpha is precedence 1
    # but needs TTL>1h, so at TTL<1h closing_edge wins; at TTL>1h injury wins.
    far = _snapshot(
        injury_present=True, injury_severity=0.9, injury_detected_age_sec=120.0,
        injury_yes_favored=True, seconds_to_event=7_200.0,
        fair_price=0.60, yes_ask=0.50, no_ask=0.46,  # also a closing-edge-style edge
    )
    res = PlaybookRouter().route(far, _bundle(far))
    assert res.routed and res.module == "injury_alpha"


def test_router_public_fade_is_last_resort():
    snap = _snapshot(
        public_pct_on_side=0.85, public_side="YES", fair_price=0.55,
        seconds_to_event=7_200.0, yes_ask=0.55, no_ask=0.46,  # no closing edge
    )
    res = PlaybookRouter().route(snap, _bundle(snap))
    assert res.routed and res.module == "public_fade"


# --------------------------------------------------------------------------- #
# Odds API parsers
# --------------------------------------------------------------------------- #
def _odds_payload(p_yes_soft: float, p_yes_sharp: float) -> dict:
    """Build an Odds API h2h payload from desired YES implied probs per book."""
    def book(key, p_yes):
        return {
            "key": key,
            "markets": [{
                "key": "h2h",
                "outcomes": [
                    {"name": "Lakers", "price": round(1.0 / p_yes, 4)},
                    {"name": "Celtics", "price": round(1.0 / (1.0 - p_yes), 4)},
                ],
            }],
        }
    return {"bookmakers": [book("pinnacle", p_yes_sharp), book("draftkings", p_yes_soft)]}


def test_decimal_and_devig():
    assert abs(decimal_to_implied(2.0) - 0.5) < 1e-9
    assert decimal_to_implied(0.0) is None
    a, b = devig_two_way(0.55, 0.55)  # 10% overround → 0.5 / 0.5
    assert abs(a - 0.5) < 1e-9 and abs(b - 0.5) < 1e-9


def test_oddsapi_model_probability_consensus():
    payload = _odds_payload(p_yes_soft=0.60, p_yes_sharp=0.50)
    p = parse_oddsapi_model_probability(payload, yes_outcome_name="Lakers", side="YES")
    assert p is not None and 0.5 < p < 0.6  # de-vigged average of 0.50 and 0.60
    p_no = parse_oddsapi_model_probability(payload, yes_outcome_name="Lakers", side="NO")
    assert abs((p + p_no) - 1.0) < 1e-9


def test_oddsapi_public_flow_detects_soft_lean():
    # Soft book prices YES higher than the sharp book → public leans YES.
    payload = _odds_payload(p_yes_soft=0.65, p_yes_sharp=0.55)
    pf = parse_oddsapi_public_flow(
        payload, "m1", yes_outcome_name="Lakers",
        public_book="draftkings", sharp_book="pinnacle",
    )
    assert pf is not None and pf.side == "YES" and pf.public_pct_on_side > 0.5
    # Equal lines → no lean.
    flat = parse_oddsapi_public_flow(
        _odds_payload(0.55, 0.55), "m1", yes_outcome_name="Lakers",
        public_book="draftkings", sharp_book="pinnacle",
    )
    assert flat is not None and abs(flat.public_pct_on_side - 0.5) < 1e-9


def test_oddsapi_public_flow_none_when_book_missing():
    payload = {"bookmakers": [{"key": "betmgm", "markets": []}]}
    assert parse_oddsapi_public_flow(
        payload, "m1", yes_outcome_name="Lakers",
        public_book="draftkings", sharp_book="pinnacle",
    ) is None


# --------------------------------------------------------------------------- #
# ESPN injury parser
# --------------------------------------------------------------------------- #
def test_parse_espn_injury_picks_most_severe_recent():
    now = time.time()
    payload = {"injuries": [{"injuries": [
        {"status": "Questionable", "date": _iso(now - 600), "athlete": {"displayName": "Role Player"}},
        {"status": "Out", "date": _iso(now - 300), "athlete": {"displayName": "Star"}},
    ]}]}
    ev = parse_espn_injury_payload(payload, "m1", yes_favored=False, now_epoch=now)
    assert ev is not None and ev.severity == 1.0 and "Star" in ev.headline
    assert ev.yes_favored is False


def test_parse_espn_injury_skips_stale_and_unknown():
    now = time.time()
    payload = {"injuries": [
        {"status": "Out", "date": _iso(now - 200_000)},   # too old
        {"status": "Healthy", "date": _iso(now - 100)},    # unknown status
    ]}
    assert parse_espn_injury_payload(payload, "m1", yes_favored=True, now_epoch=now) is None


def _iso(epoch: float) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat().replace("+00:00", "Z")


# --------------------------------------------------------------------------- #
# Factory + adapters (no network)
# --------------------------------------------------------------------------- #
def test_build_sports_feed_defaults_to_nullfeed():
    class _S:
        PLAYBOOK_INJURY_FEED_ENABLED = True
        PLAYBOOK_PUBLIC_FEED_ENABLED = True

    # No resolver → always NullFeed, regardless of flags.
    assert isinstance(build_sports_feed(_S(), resolver=None), NullFeed)


def test_build_sports_feed_nullfeed_when_flags_off():
    class _S:
        PLAYBOOK_INJURY_FEED_ENABLED = False
        PLAYBOOK_PUBLIC_FEED_ENABLED = False

    assert isinstance(build_sports_feed(_S(), resolver=lambda m: None), NullFeed)


def test_espn_feed_no_network_without_target():
    feed = EspnInjuryFeed(resolver=lambda m: None)
    assert asyncio.run(feed.get_injury_event("m1")) is None
    # Missing ESPN addressing on the target → still no network call, None.
    feed2 = EspnInjuryFeed(resolver=lambda m: FeedTarget(market_id=m))
    assert asyncio.run(feed2.get_injury_event("m1")) is None


def test_oddsapi_feed_no_network_without_target():
    feed = OddsApiFeed(resolver=lambda m: None, api_key="k")
    assert asyncio.run(feed.get_public_flow("m1")) is None
    assert asyncio.run(feed.get_model_probability("m1", "YES")) is None


# --------------------------------------------------------------------------- #
# Strategy feed-attach
# --------------------------------------------------------------------------- #
def test_strategy_feed_inputs_nullfeed_is_empty():
    strat = PlaybookStrategy()  # default NullFeed
    assert asyncio.run(strat._feed_inputs("c1")) == {}


def test_strategy_feed_inputs_maps_injury_and_public():
    injury = InjuryEvent(
        market_id="c1", headline="Star out", severity=0.9,
        detected_ts_epoch=time.time() - 120.0, yes_favored=False, repriced_fraction=0.1,
    )
    public = PublicFlow(market_id="c1", public_pct_on_side=0.8, side="yes")
    strat = PlaybookStrategy(feed=_FakeFeed(injury=injury, public=public))
    out = asyncio.run(strat._feed_inputs("c1"))
    assert out["injury_present"] is True and out["injury_yes_favored"] is False
    assert out["injury_severity"] == 0.9 and out["injury_detected_age_sec"] >= 120.0
    assert out["public_pct_on_side"] == 0.8 and out["public_side"] == "YES"


def test_strategy_evaluate_snapshot_routes_injury_alpha():
    strat = PlaybookStrategy()
    snap = _snapshot(
        injury_present=True, injury_severity=0.9, injury_detected_age_sec=120.0,
        injury_yes_favored=True, seconds_to_event=7_200.0,
        fair_price=0.55, yes_ask=0.55, no_ask=0.46,
    )
    cand = strat.evaluate_snapshot(snap, _user())
    assert cand is not None and cand.metadata["selected_module"] == "injury_alpha"
    assert cand.metadata["applied_tp_pct"] == 0.30


def _user():
    from projects.polymarket.crusaderbot.domain.strategy.types import UserContext
    return UserContext(
        user_id="u1", sub_account_id="s1", risk_profile="balanced",
        capital_allocation_pct=0.40, available_balance_usdc=1_000.0, equity_usdc=1_000.0,
    )
