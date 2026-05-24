"""Hermetic tests for the crypto short-duration timeframe classifier.

Coverage:
    * classify_crypto_timeframe: keyword detection (5m / 15m), 15m-before-5m
      precedence, duration fallback, fail-closed on ambiguous/non-classifiable.
    * is_short_crypto_market: composes crypto-asset gate + timeframe match,
      timeframe=None means "any 5m/15m crypto market".

No network, no DB.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from projects.polymarket.crusaderbot.domain.strategy.eligibility import (
    classify_crypto_timeframe,
    is_short_crypto_market,
)


def _market(**kw):
    base = {"category": "Crypto"}
    base.update(kw)
    return base


# ── classify_crypto_timeframe — keyword detection ───────────────────────────

def test_keyword_5m_slug():
    m = _market(slug="bitcoin-up-or-down-5-minute-2026-05-24")
    assert classify_crypto_timeframe(m) == "5m"


def test_keyword_15m_slug():
    m = _market(slug="ethereum-up-or-down-15-minute-2026-05-24")
    assert classify_crypto_timeframe(m) == "15m"


def test_keyword_15m_takes_precedence_over_5m_substring():
    # "15m" must win even when a bare "5m"-like token could match inside it.
    m = _market(question="BTC 15m candle up or down?")
    assert classify_crypto_timeframe(m) == "15m"


def test_keyword_question_field():
    m = _market(question="Will BTC be up in the next 5 min?")
    assert classify_crypto_timeframe(m) == "5m"


# ── duration fallback ───────────────────────────────────────────────────────

def test_duration_fallback_5m():
    now = datetime.now(timezone.utc)
    m = _market(
        slug="btc-hourly",  # no interval keyword
        startDate=now.isoformat(),
        endDate=(now + timedelta(minutes=5)).isoformat(),
    )
    assert classify_crypto_timeframe(m) == "5m"


def test_duration_fallback_15m():
    now = datetime.now(timezone.utc)
    m = _market(
        slug="eth-recurring",
        startDate=now.isoformat(),
        endDate=(now + timedelta(minutes=15)).isoformat(),
    )
    assert classify_crypto_timeframe(m) == "15m"


# ── fail-closed ─────────────────────────────────────────────────────────────

def test_unclassifiable_returns_none():
    m = _market(slug="bitcoin-ath-2026", question="Will BTC hit $200k in 2026?")
    assert classify_crypto_timeframe(m) is None


def test_long_duration_returns_none():
    now = datetime.now(timezone.utc)
    m = _market(
        slug="btc-eoy",
        startDate=now.isoformat(),
        endDate=(now + timedelta(hours=6)).isoformat(),
    )
    assert classify_crypto_timeframe(m) is None


def test_non_dict_returns_none():
    assert classify_crypto_timeframe(None) is None
    assert classify_crypto_timeframe("nope") is None


# ── is_short_crypto_market ──────────────────────────────────────────────────

def test_short_crypto_match_timeframe():
    m = _market(question="Bitcoin up or down 5 minute", slug="btc-5-minute")
    assert is_short_crypto_market(m, "5m") is True
    assert is_short_crypto_market(m, "15m") is False


def test_short_crypto_timeframe_none_accepts_any_classified():
    m = _market(question="ETH 15 minute up or down", slug="eth-15-minute")
    assert is_short_crypto_market(m, None) is True


def test_non_crypto_rejected():
    m = {"category": "Politics", "question": "Election 5 minute recount", "slug": "x-5-minute"}
    assert is_short_crypto_market(m, "5m") is False


def test_crypto_without_timeframe_rejected():
    m = _market(question="Will BTC hit $200k?", slug="btc-200k")
    assert is_short_crypto_market(m, "5m") is False
    assert is_short_crypto_market(m, None) is False
