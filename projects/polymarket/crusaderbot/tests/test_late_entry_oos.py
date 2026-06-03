"""Tests for the late_entry_v3 OOS edge harness (WARP-58).

Pins: the round-trip cost model math, per-trade net netting, the per-preset
decider entry-window/price gating, and run_oos inertness on an empty substrate
(every preset UNPROVEN_NO_DATA). No DB — snapshot rows are injected.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from projects.polymarket.crusaderbot.domain.research.late_entry_oos import (
    PRESETS,
    CostModel,
    OOSResult,
    build_decider,
    run_oos,
)
from projects.polymarket.crusaderbot.domain.research.replay import ReplayTrade


def _row(market_id: str, mid: float, scanned_at: datetime, rem_sec: float) -> dict:
    end = scanned_at + timedelta(seconds=rem_sec)
    return {
        "market_id": market_id,
        "category": "crypto",
        "best_bid": mid - 0.01,
        "best_ask": mid + 0.01,
        "mid_price": mid,
        "liquidity_usdc": 5000.0,
        "raw": json.dumps({"slug": f"{market_id}-updown-5m", "endDate": end.isoformat()}),
        "scanned_at": scanned_at,
    }


# ---- cost model -----------------------------------------------------------

def test_round_trip_cost_fraction_default():
    c = CostModel()  # 1 tick/side, tick 0.01, fee 0 -> 0.02 absolute price cost
    # YES notional 0.55 -> 0.02 / 0.55
    assert c.round_trip_cost_fraction(0.55) == pytest.approx(0.02 / 0.55)
    # non-positive notional -> no position
    assert c.round_trip_cost_fraction(0.0) == 0.0


def test_net_return_subtracts_cost():
    c = CostModel()
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    t = ReplayTrade(
        module="m", category="crypto", side="YES",
        entry_ts=now, resolution_ts=now + timedelta(seconds=35),
        entry_price=0.55, exit_price=1.0,
    )
    gross = (1.0 - 0.55) / 0.55
    assert c.net_return(t) == pytest.approx(gross - 0.02 / 0.55)


def test_net_return_can_flip_winner_to_loser():
    c = CostModel()
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    # tiny gross win (entry 0.50 -> exit 0.505) is erased by the cost haircut
    t = ReplayTrade(
        module="m", category="crypto", side="YES",
        entry_ts=now, resolution_ts=now + timedelta(seconds=10),
        entry_price=0.50, exit_price=0.505,
    )
    assert trade_gross(t) > 0
    assert c.net_return(t) < 0


def trade_gross(t: ReplayTrade) -> float:
    from projects.polymarket.crusaderbot.domain.research.replay import trade_return
    return trade_return(t)


# ---- decider gating -------------------------------------------------------

def test_decider_admits_in_window_favored():
    decide = build_decider("close_sweep")  # window 35s, fav 0.55-0.70
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    # mid 0.60 favored YES, 20s to close -> inside window, fav in band
    assert decide(_row("mkt1", 0.60, now, rem_sec=20.0)) == ("late_entry_v3::close_sweep", "YES")


def test_decider_rejects_outside_window():
    decide = build_decider("close_sweep")
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    # 200s to close >> 35s window
    assert decide(_row("mkt1", 0.60, now, rem_sec=200.0)) is None


def test_decider_rejects_fav_price_out_of_band():
    decide = build_decider("close_sweep")  # fav max 0.70
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    # mid 0.80 favored YES at 0.80 > 0.70 ceiling -> reject
    assert decide(_row("mkt1", 0.80, now, rem_sec=20.0)) is None


def test_flip_hunter_takes_underdog_cheap_side():
    decide = build_decider("flip_hunter")  # underdog, fav band 0.10-0.36, window 180/min 60
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    # mid 0.70 -> majority YES; underdog flips to NO priced 0.30 (in band)
    assert decide(_row("mkt1", 0.70, now, rem_sec=120.0)) == ("late_entry_v3::flip_hunter", "NO")


# ---- run_oos inertness ----------------------------------------------------

@pytest.mark.asyncio
async def test_run_oos_empty_substrate_all_unproven():
    async def empty_fetch(_lookback: int) -> list:
        return []

    results = await run_oos(fetch_rows=empty_fetch)
    assert set(results) == set(PRESETS)
    for preset in PRESETS:
        r = results[preset]
        assert isinstance(r, OOSResult)
        assert r.n_trades == 0
        assert r.edge_bps is None
        assert r.status == "UNPROVEN_NO_DATA"


@pytest.mark.asyncio
async def test_run_oos_thin_sample_is_unproven():
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    # 2 markets (well under MIN_OOS_TRADES) -> close_sweep measured but UNPROVEN_THIN
    rows = [
        _row("a", 0.60, now, rem_sec=20.0), _row("a", 1.0, now + timedelta(seconds=20), rem_sec=0.0),
        _row("b", 0.62, now, rem_sec=15.0), _row("b", 0.0, now + timedelta(seconds=15), rem_sec=0.0),
    ]

    async def fetch(_lookback: int) -> list:
        return rows

    results = await run_oos(presets=("close_sweep",), fetch_rows=fetch)
    r = results["close_sweep"]
    assert r.n_trades == 2
    assert r.status == "UNPROVEN_THIN"
    assert r.edge_bps is None  # thin sample -> not credited
    assert r.hit_rate is not None  # but metrics still computed
