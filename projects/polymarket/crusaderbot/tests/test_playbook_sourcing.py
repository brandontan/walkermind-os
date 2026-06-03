"""Hermetic tests for playbook sports-market recognition + sourcing.

WARP/ROOT/strategy-real-clob-sourcing (playbook half): today's individual game
markets live on Gamma /markets with a ``sportsMarketType`` + per-game
``gameStartTime`` and ``category=None`` — the old category-token-only check
excluded every one. _is_sports_market now recognises them via sportsMarketType
(authoritative), the tag-derived category, or the event slug. The selection
window is a single (0, 72h].
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from projects.polymarket.crusaderbot.domain.strategy.strategies import playbook as pbs


def test_is_sports_market_recognises_sportsmarkettype_even_with_null_category():
    # /markets game markets: category None but a real sportsMarketType.
    assert pbs._is_sports_market({"sportsMarketType": "moneyline", "category": None}) is True
    assert pbs._is_sports_market({"sportsMarketType": "spreads"}) is True


def test_is_sports_market_recognises_tag_category():
    assert pbs._is_sports_market({"category": "sports nba"}) is True
    assert pbs._is_sports_market({"category": "soccer"}) is True


def test_is_sports_market_recognises_event_slug():
    # category None, no sportsMarketType, but the parent event slug names a sport.
    assert pbs._is_sports_market(
        {"category": None, "events": [{"slug": "nba-nyk-sas-2026-06-03"}]}
    ) is True
    assert pbs._is_sports_market({"category": None, "slug": "world-cup-winner"}) is True


def test_is_sports_market_rejects_non_sports_and_junk():
    assert pbs._is_sports_market({"category": "crypto"}) is False
    assert pbs._is_sports_market({"category": None}) is False
    assert pbs._is_sports_market("junk") is False
    assert pbs._is_sports_market(None) is False


def test_select_window_includes_game_market_with_null_category():
    now = datetime(2026, 6, 3, 0, 0, 0, tzinfo=timezone.utc)
    markets = [
        # near-term game market, category None, sportsMarketType set -> selected
        {"conditionId": "g1", "category": None, "sportsMarketType": "moneyline",
         "gameStartTime": (now + timedelta(hours=6)).isoformat()},
        # non-sports in window -> excluded
        {"conditionId": "x", "category": "crypto",
         "gameStartTime": (now + timedelta(hours=1)).isoformat()},
    ]
    got = {t[1] for t in pbs.select_sports_markets_in_window(markets, now=now)}
    assert got == {"g1"}
