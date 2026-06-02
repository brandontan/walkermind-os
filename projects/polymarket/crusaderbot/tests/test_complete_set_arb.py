"""Unit tests for the complete-set arbitrage detection/sizing core (Lane 1).

Pure module (no DB / IO) — exercises the level-walking fillable-size math and its
guards. The arb thesis: buy y YES + y NO for < y*$1.00, hold to settlement for a
locked y*$1.00 payout.
"""
from __future__ import annotations

from projects.polymarket.crusaderbot.domain.strategy.complete_set_arb import (
    COMPLETE_SET_PAYOUT,
    CompleteSetQuote,
    fillable_complete_set,
)

_IDS = dict(
    market_id="m1", condition_id="c1", yes_token_id="ytok", no_token_id="ntok"
)


def _book(asks: list[tuple[float, float]]) -> dict:
    return {"bids": [], "asks": [{"price": p, "size": s} for p, s in asks]}


def test_payout_constant() -> None:
    assert COMPLETE_SET_PAYOUT == 1.0


def test_empty_books_return_none() -> None:
    assert fillable_complete_set(_book([]), _book([(0.4, 10)]), min_pair_margin=0.02, **_IDS) is None
    assert fillable_complete_set(None, None, min_pair_margin=0.02, **_IDS) is None


def test_simple_profitable_single_level() -> None:
    q = fillable_complete_set(
        _book([(0.45, 100)]), _book([(0.50, 100)]), min_pair_margin=0.02, **_IDS
    )
    assert isinstance(q, CompleteSetQuote)
    assert q.fillable_shares == 100.0
    assert q.avg_pair_cost == 0.95
    assert q.yes_cost_usdc == 45.0
    assert q.no_cost_usdc == 50.0
    assert q.gross_margin_usdc == 5.0          # 100*1.00 - 95
    assert q.net_margin_usdc == 3.0            # 5 - 0.02*100
    assert q.total_cost_usdc == 95.0


def test_unprofitable_pair_rejected() -> None:
    # 0.55 + 0.50 = 1.05 > threshold (0.98) → no profitable pair
    assert fillable_complete_set(
        _book([(0.55, 100)]), _book([(0.50, 100)]), min_pair_margin=0.02, **_IDS
    ) is None


def test_marginal_crossover_stops_at_profitable_prefix() -> None:
    # YES: 0.40/50 then 0.60/50 ; NO: 0.50/100
    # pair1 0.90 ok → take 50 ; pair2 1.10 > 0.98 → stop
    q = fillable_complete_set(
        _book([(0.40, 50), (0.60, 50)]), _book([(0.50, 100)]),
        min_pair_margin=0.02, **_IDS,
    )
    assert q is not None
    assert q.fillable_shares == 50.0
    assert q.yes_cost_usdc == 20.0
    assert q.no_cost_usdc == 25.0
    assert q.gross_margin_usdc == 5.0


def test_descending_ask_order_is_handled() -> None:
    # Polymarket returns asks worst(highest)-first; cheapest must still be used.
    q = fillable_complete_set(
        _book([(0.60, 50), (0.40, 50)]), _book([(0.50, 100)]),
        min_pair_margin=0.02, **_IDS,
    )
    assert q is not None
    # cheapest YES (0.40,50) pairs with NO 0.50 → 0.90 ok; next YES 0.60 → 1.10 stop
    assert q.fillable_shares == 50.0
    assert q.yes_cost_usdc == 20.0


def test_string_prices_and_sizes_parsed() -> None:
    book_y = {"bids": [], "asks": [{"price": "0.45", "size": "100"}]}
    book_n = {"bids": [], "asks": [{"price": "0.50", "size": "100"}]}
    q = fillable_complete_set(book_y, book_n, min_pair_margin=0.02, **_IDS)
    assert q is not None and q.fillable_shares == 100.0


def test_degenerate_levels_skipped() -> None:
    # price>=1, price<=0, size<=0 all skipped → only the (0.45,100)/(0.50,100) real levels remain
    book_y = _book([(0.0, 100), (1.0, 100), (0.45, 100), (0.50, -5)])
    book_n = _book([(-0.1, 100), (0.50, 100)])
    q = fillable_complete_set(book_y, book_n, min_pair_margin=0.02, **_IDS)
    assert q is not None
    assert q.fillable_shares == 100.0
    assert q.avg_pair_cost == 0.95


def test_max_shares_cap_partial_fill() -> None:
    q = fillable_complete_set(
        _book([(0.45, 100)]), _book([(0.50, 100)]),
        min_pair_margin=0.02, max_shares=30, **_IDS,
    )
    assert q is not None
    assert q.fillable_shares == 30.0
    assert q.yes_cost_usdc == 13.5
    assert q.no_cost_usdc == 15.0


def test_min_shares_floor_rejects_dust() -> None:
    assert fillable_complete_set(
        _book([(0.45, 100)]), _book([(0.50, 100)]),
        min_pair_margin=0.02, min_shares=200, **_IDS,
    ) is None


def test_unequal_leg_depth_bounds_to_thinner_side() -> None:
    # YES depth 30 only; NO 100 → fillable bounded to 30
    q = fillable_complete_set(
        _book([(0.45, 30)]), _book([(0.50, 100)]),
        min_pair_margin=0.02, **_IDS,
    )
    assert q is not None
    assert q.fillable_shares == 30.0


def test_non_positive_margin_floor_returns_none() -> None:
    assert fillable_complete_set(
        _book([(0.45, 100)]), _book([(0.50, 100)]), min_pair_margin=0.0, **_IDS
    ) is None
    assert fillable_complete_set(
        _book([(0.45, 100)]), _book([(0.50, 100)]), min_pair_margin=-0.01, **_IDS
    ) is None


def test_multi_level_both_sides_accumulates() -> None:
    # YES: 0.40/40, 0.44/60 ; NO: 0.50/50, 0.52/50  (threshold 0.98)
    # chunk1: min(40,50)=40 @ (0.40+0.50)=0.90 → 40 sh
    # YES→0.44 rem? after 40, yes lvl0 exhausted → yes lvl1 0.44/60; no lvl0 rem 10
    # chunk2: min(60,10)=10 @ (0.44+0.50)=0.94 → +10 → 50 sh ; no lvl0 exhausted → no lvl1 0.52/50
    # chunk3: min(50,50)=50 @ (0.44+0.52)=0.96 ≤0.98 → +50 → 100 sh ; yes lvl1 exhausted
    q = fillable_complete_set(
        _book([(0.40, 40), (0.44, 60)]), _book([(0.50, 50), (0.52, 50)]),
        min_pair_margin=0.02, **_IDS,
    )
    assert q is not None
    assert q.fillable_shares == 100.0
    # cost = 40*0.40 + 10*0.44 + 50*0.44  (yes) ... compute via module
    expected_yes = 40 * 0.40 + (10 + 50) * 0.44
    expected_no = (40 + 10) * 0.50 + 50 * 0.52
    assert abs(q.yes_cost_usdc - expected_yes) < 1e-6
    assert abs(q.no_cost_usdc - expected_no) < 1e-6
    assert q.net_margin_usdc > 0.0


def test_malformed_asks_type_returns_none() -> None:
    # Non-list asks (e.g. a malformed API payload) must not raise — contract is
    # "never raises, returns None on a bad book".
    book_y = {"bids": [], "asks": 123}
    book_n = _book([(0.50, 100)])
    assert fillable_complete_set(book_y, book_n, min_pair_margin=0.02, **_IDS) is None


def test_infinite_and_nan_size_skipped() -> None:
    # inf / NaN sizes must be skipped so they never reach the cost/margin math.
    book_n = _book([(0.50, 100)])
    assert fillable_complete_set(
        {"bids": [], "asks": [{"price": 0.45, "size": float("inf")}]},
        book_n, min_pair_margin=0.02, **_IDS,
    ) is None
    assert fillable_complete_set(
        {"bids": [], "asks": [{"price": 0.45, "size": float("nan")}]},
        book_n, min_pair_margin=0.02, **_IDS,
    ) is None


def test_nan_margin_returns_none() -> None:
    # NaN floor must be rejected (not (NaN > 0) is True), not silently accepted.
    assert fillable_complete_set(
        _book([(0.45, 100)]), _book([(0.50, 100)]),
        min_pair_margin=float("nan"), **_IDS,
    ) is None
