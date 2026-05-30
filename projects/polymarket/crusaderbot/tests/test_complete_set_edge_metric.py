"""Observational complete-set edge metric
(WARP/R00T/complete-set-edge-metric, Lane 3/5 Polybot directive).

Stamps `complete_set_edge = round(1 - (yes_ask + no_ask), 4)` into every
late_entry_v3 candidate's metadata. FOUNDATION lane — read-only metric
exposure, no trade-logic change. Future lanes can promote to a hard gate
or operator dashboard once production data shows whether the signal is
predictive.

Math reference (Polymarket UP+DOWN settle to $1.00 at expiry):
  edge > 0  → cost < 1.00 → textbook taker-side arbitrage (rare; book
              depth usually kills it)
  edge = 0  → cost = 1.00 → efficient pricing
  edge < 0  → cost > 1.00 → overpriced relative to settlement bound

Stamp lives in: ``late_entry_v3._evaluate_market``
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from projects.polymarket.crusaderbot.domain.strategy.strategies import (
    late_entry_v3 as lev3,
)
from projects.polymarket.crusaderbot.domain.strategy.types import UserContext


# Coverage strategy: the formula correctness + metadata stamp are fully
# covered by the parametrized math fingerprint and the three behavioural
# regime tests below. Earlier drafts also kept `inspect.getsource` source
# pins; dropped per Gemini review on PR #1477 because they assert on
# implementation syntax (quote style, expression layout) and would break
# on any formatter pass even when behaviour is unchanged.


# ---------------------------------------------------------------------
# Math fingerprint — the formula behaviour across regimes.
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "yes_ask,no_ask,expected_edge",
    [
        # Efficient pricing — no arb either way.
        (0.50, 0.50, 0.0),
        # Underpriced cost = 0.95 → 5c arb edge (rare, would be eaten
        # by spread / depth in practice).
        (0.55, 0.40, 0.05),
        # Overpriced cost = 1.10 → -10c edge (taker can never profit).
        (0.65, 0.45, -0.10),
        # Tight near-binary lean.
        (0.95, 0.04, 0.01),
        # Negative edge case from real candle data (sum 1.02).
        (0.62, 0.40, -0.02),
    ],
)
def test_complete_set_edge_formula(yes_ask, no_ask, expected_edge):
    """The textbook formula `edge = 1 - (yes_ask + no_ask)` must hold
    across positive / zero / negative regimes. Rounded to 4 decimals
    (same IEEE-754 precision argument as the leg-spread gate — Polymarket
    tick is 0.01, 4 decimals is well below tick granularity)."""
    edge = round(1.0 - (yes_ask + no_ask), 4)
    assert edge == pytest.approx(expected_edge)


# ---------------------------------------------------------------------
# Behavioural — metric ends up in a real candidate's metadata.
# ---------------------------------------------------------------------


def _book(ask: float, bid: float) -> dict:
    return {
        "asks": [{"price": str(ask), "size": "100"}],
        "bids": [{"price": str(bid), "size": "100"}],
    }


def _market_with_seconds_left(*, secs: float = 20.0) -> dict:
    end = datetime(2026, 5, 30, 14, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=secs)
    return {
        "conditionId": "cond-1",
        "slug": "btc-updown-5m-test",
        "closed": False,
        "active": True,
        "acceptingOrders": True,
        "clobTokenIds": ["yes_tok", "no_tok"],
        "endDate": end.isoformat().replace("+00:00", "Z"),
    }


def _evaluate_args() -> dict:
    now = datetime(2026, 5, 30, 14, 0, 0, tzinfo=timezone.utc)
    return dict(
        blacklist=set(),
        user_context=UserContext(
            user_id="u",
            sub_account_id="u",
            risk_profile="balanced",
            capital_allocation_pct=0.10,
            available_balance_usdc=500.0,
        ),
        strategy_name="late_entry_v3",
        signal_ts=now,
        now_ts=now.timestamp(),
        min_ask_diff=0.02,
        entry_window_sec=35.0,
        fav_price_min=0.55,
        fav_price_max=0.70,
        min_entry_sec=None,
        underdog_mode=False,
        force_exit_at_rem_sec=None,
        max_leg_spread=None,  # Lane 2 gate disabled — Lane 3 is observational only
    )


@pytest.mark.asyncio
async def test_metric_stamped_in_accepted_candidate_metadata(monkeypatch):
    """Accepted candidate must surface `complete_set_edge` in metadata
    so operator can read the metric for the trade that fired."""
    yes_book = _book(ask=0.65, bid=0.64)
    no_book = _book(ask=0.35, bid=0.34)
    # cost = 1.00, edge = 0.0 (efficient pricing — round-trip)
    m = _market_with_seconds_left()

    async def _fake_get_book(token_id: str):
        return yes_book if token_id == "yes_tok" else no_book

    monkeypatch.setattr(lev3.pm, "get_book", _fake_get_book)

    cand, reason = await lev3._evaluate_market(m, **_evaluate_args())
    assert cand is not None, (
        f"Setup should accept this candidate but got reason={reason!r}; "
        f"fix the test market shape if the strategy gate moved."
    )
    assert "complete_set_edge" in cand.metadata
    assert cand.metadata["complete_set_edge"] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_metric_captures_negative_edge_on_overpriced_market(monkeypatch):
    """When cost > 1.00 (overpriced book) the metric must be negative —
    operator should be able to flag these markets as 'never profitable
    from a taker arb perspective' from the metadata alone."""
    # cost = 1.04, edge = -0.04. Kept under MAX_SPREAD=1.05 so the
    # pre-existing complete-set-cost gate (`spread > MAX_SPREAD` reject)
    # does not short-circuit before the metric is stamped — Lane 3's
    # contract is that the metric is *observational*, not gated by the
    # arb-edge sign.
    yes_book = _book(ask=0.64, bid=0.63)
    no_book = _book(ask=0.40, bid=0.39)
    m = _market_with_seconds_left()

    async def _fake_get_book(token_id: str):
        return yes_book if token_id == "yes_tok" else no_book

    monkeypatch.setattr(lev3.pm, "get_book", _fake_get_book)

    cand, reason = await lev3._evaluate_market(m, **_evaluate_args())
    assert cand is not None, (
        f"Overpriced (but still inside MAX_SPREAD=1.05) market should "
        f"produce a candidate; got reason={reason!r}."
    )
    assert cand.metadata["complete_set_edge"] == pytest.approx(-0.04)


@pytest.mark.asyncio
async def test_metric_captures_positive_edge_when_book_underpriced(monkeypatch):
    """Rare-but-real: when cost < 1.00 the metric is positive (textbook
    arb exists at the quoted top-of-book). Strategy still trades the
    directional side — the metric just exposes the observation."""
    # fav_price_min=0.55 so YES must be >= 0.55 to qualify;
    # cost = 0.55 + 0.43 = 0.98, edge = 0.02
    yes_book = _book(ask=0.55, bid=0.54)
    no_book = _book(ask=0.43, bid=0.42)
    m = _market_with_seconds_left()

    async def _fake_get_book(token_id: str):
        return yes_book if token_id == "yes_tok" else no_book

    monkeypatch.setattr(lev3.pm, "get_book", _fake_get_book)

    cand, reason = await lev3._evaluate_market(m, **_evaluate_args())
    # ask_diff = 0.12 (well above min 0.02), entry_price = 0.55
    # (== fav_price_min, gate uses `<`). Explicit assert (not skip) so a
    # regression that newly rejects this market trips a real failure
    # instead of silently passing.
    assert cand is not None, (
        f"Underpriced market with cost=0.98 (edge=+0.02) and YES "
        f"at fav_price_min must produce a candidate; got reason={reason!r}."
    )
    assert cand.metadata["complete_set_edge"] == pytest.approx(0.02)
