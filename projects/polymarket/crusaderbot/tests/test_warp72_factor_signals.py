"""WARP-72 Phase 1 — SMART STRIKE factor signals + labeled-dataset emission.

SHADOW/telemetry-only build (WARP•R00T). Verifies:

  * Momentum: pure rolling-window velocity + tracker (sampling, intra-tick
    de-dup, window prune, idle-key eviction). The audit (WARP-71) found momentum
    was unmeasured — this is the new real short-window repricing signal.
  * Factors: realized open->close label math, FactorVector -> factor_* metadata,
    router-selection stamp, fail-soft emit.
  * Wiring: a surviving candidate carries the full factor_* surface (volatility
    sigma now EXPOSED, not oracle-only; liquidity / spread / depth / TTL exposed);
    the factor vector is emitted for EVERY evaluated candle — traded OR rejected
    by a directional gate — decoupled from execution; the flag silences it; and
    the oracle realized label rides through when the advisory edge is wired.

No network, no DB, no broker. Polymarket API calls are patched with AsyncMock.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from projects.polymarket.crusaderbot.domain.signal import factors as fac
from projects.polymarket.crusaderbot.domain.signal.factors import (
    FACTOR_VECTOR_EVENT,
    FactorVector,
    mark_router_selection,
    realized_candle_outcome,
)
from projects.polymarket.crusaderbot.domain.signal.momentum import (
    MomentumTracker,
    PriceSample,
    compute_momentum,
    get_tracker,
)
from projects.polymarket.crusaderbot.domain.strategy.strategies import late_entry_v3 as lev3
from projects.polymarket.crusaderbot.domain.strategy.strategies.late_entry_v3 import (
    LateEntryV3Strategy,
    OracleEdgeConfig,
)
from projects.polymarket.crusaderbot.domain.strategy.types import MarketFilters, UserContext

_MARKETS_PATCH = (
    "projects.polymarket.crusaderbot.domain.strategy.strategies"
    ".late_entry_v3.pm.get_crypto_window_markets"
)
_BOOK_PATCH = (
    "projects.polymarket.crusaderbot.domain.strategy.strategies"
    ".late_entry_v3.pm.get_book"
)


# ---------------------------------------------------------------------------
# 1. Momentum — pure compute
# ---------------------------------------------------------------------------


def test_compute_momentum_needs_two_points():
    now = 1000.0
    assert compute_momentum([], window_sec=60, now=now) is None
    assert compute_momentum([PriceSample(now, 0.5)], window_sec=60, now=now) is None


def test_compute_momentum_velocity_and_sign():
    now = 1030.0
    samples = [PriceSample(1000.0, 0.50), PriceSample(1030.0, 0.56)]
    r = compute_momentum(samples, window_sec=60, now=now)
    assert r is not None
    assert r.samples == 2
    assert r.span_sec == 30.0
    assert r.delta == pytest.approx(0.06)
    assert r.velocity == pytest.approx(0.06 / 30.0)  # rising -> positive
    # Falling series -> negative velocity.
    down = compute_momentum(
        [PriceSample(1000.0, 0.60), PriceSample(1030.0, 0.54)], window_sec=60, now=now
    )
    assert down is not None and down.velocity < 0.0


def test_compute_momentum_excludes_out_of_window():
    now = 1000.0
    # The old sample (t=800) is outside a 60s window -> only one in-window point.
    samples = [PriceSample(800.0, 0.4), PriceSample(990.0, 0.5)]
    assert compute_momentum(samples, window_sec=60, now=now) is None


# ---------------------------------------------------------------------------
# 2. Momentum — tracker behaviour
# ---------------------------------------------------------------------------


def test_tracker_records_and_reads():
    t = MomentumTracker(window_sec=60)
    t.record("m", 0.50, now=1000.0)
    t.record("m", 0.55, now=1030.0)
    r = t.momentum("m", now=1030.0)
    assert r is not None and r.samples == 2 and r.velocity > 0.0


def test_tracker_intra_tick_dedup():
    # candle_auto scans the same market for 3 rules in one tick (~same wall-clock);
    # only one sample should land.
    t = MomentumTracker(window_sec=60, min_gap_sec=1.0)
    t.record("m", 0.50, now=1000.0)
    t.record("m", 0.51, now=1000.2)  # within min_gap -> skipped
    t.record("m", 0.52, now=1000.5)  # within min_gap -> skipped
    assert t.momentum("m", now=1000.5) is None  # still only 1 sample


def test_tracker_prunes_and_rejects_bad_prices():
    t = MomentumTracker(window_sec=10)  # retention = 30s
    t.record("m", 0.50, now=1000.0)
    t.record("m", None, now=1005.0)     # ignored
    t.record("m", -1.0, now=1006.0)     # non-positive -> ignored
    t.record("m", 0.55, now=1040.0)     # 40s later -> old sample pruned
    # Only the newest survives -> not enough for momentum.
    assert t.momentum("m", now=1040.0) is None
    assert t.tracked_keys == 1


def test_tracker_evicts_idle_keys():
    t = MomentumTracker(window_sec=10, max_keys=2)
    t.record("a", 0.5, now=1000.0)
    t.record("b", 0.5, now=1000.0)
    # 'a'/'b' are now idle (>30s); adding 'c' at capacity sweeps them.
    t.record("c", 0.5, now=1100.0)
    assert t.tracked_keys == 1 and t.momentum("c", now=1100.0) is None


def test_tracker_enforces_hard_key_cap_under_churn():
    # All keys are FRESH (none idle) — the hard cap must still bound the map by
    # evicting the oldest-updated key, never growing unboundedly.
    t = MomentumTracker(window_sec=100, max_keys=3)
    for i, k in enumerate(["a", "b", "c", "d", "e"]):
        t.record(k, 0.5, now=1000.0 + i)  # each within retention, strictly fresh
    # Cap holds despite 5 fresh keys; oldest were evicted, newest retained.
    assert t.tracked_keys == 3
    assert "e" in t._hist and "a" not in t._hist  # oldest-updated evicted first


# ---------------------------------------------------------------------------
# 3. Factors — realized label, metadata, router stamp, emit
# ---------------------------------------------------------------------------


def test_realized_candle_outcome():
    assert realized_candle_outcome(100.0, 101.0) == ("UP", pytest.approx(0.01))
    assert realized_candle_outcome(100.0, 99.0) == ("DOWN", pytest.approx(-0.01))
    assert realized_candle_outcome(100.0, 100.0) == ("FLAT", 0.0)
    assert realized_candle_outcome(None, 1.0) == (None, None)
    assert realized_candle_outcome(0.0, 1.0) == (None, None)  # open<=0 undefined


def _fv(**over) -> FactorVector:
    base = dict(
        market_id="c1", condition_id="c1", slug="btc-updown-5m-1", asset="btc",
        timeframe="5m", evaluated_rule="close_sweep", momentum=0.001,
        momentum_delta=0.05, momentum_span_sec=30.0, momentum_samples=3,
        volatility_sigma=0.0001, liquidity_usdc=1234.0, spread=0.98,
        orderbook_depth_usdc=1234.0, ttl_sec=20.0, oracle_edge=0.03,
        oracle_edge_status="computed", oracle_would_pass=True, oracle_delta=0.001,
        fav_side="YES", entry_side="YES", fav_price=0.65, entry_price=0.65,
        ask_diff=0.45, complete_set_edge=0.02, underdog_mode=False,
        realized_outcome="UP", realized_delta=0.001, outcome_source="oracle_open_to_now",
        outcome_observed_rem_sec=20.0, candle_open_epoch=1.0, candle_close_epoch=301.0,
    )
    base.update(over)
    return FactorVector(**base)


def test_factor_vector_to_metadata_prefixes_all_keys():
    md = _fv().to_metadata()
    assert md["factor_momentum"] == 0.001
    assert md["factor_volatility_sigma"] == 0.0001
    assert md["factor_ttl_sec"] == 20.0
    assert md["factor_oracle_edge"] == 0.03
    assert md["factor_realized_outcome"] == "UP"
    assert all(k.startswith("factor_") for k in md)
    # All 7 factors present on the scorable surface.
    for k in ("factor_momentum", "factor_volatility_sigma", "factor_liquidity_usdc",
              "factor_spread", "factor_orderbook_depth_usdc", "factor_ttl_sec",
              "factor_oracle_edge"):
        assert k in md


def test_mark_router_selection():
    md: dict = {}
    mark_router_selection(md, "safe_close")
    assert md["factor_router_selected_rule"] == "safe_close"
    assert md["factor_selected_by_router"] is True
    mark_router_selection(None, "x")  # type: ignore[arg-type]  # no raise


def test_factor_vector_emit_is_failsoft(monkeypatch):
    events: list = []
    monkeypatch.setattr(fac.log, "info", lambda ev, **kw: events.append((ev, kw)))
    _fv().emit()
    assert events and events[0][0] == FACTOR_VECTOR_EVENT
    assert events[0][1]["realized_outcome"] == "UP"


# ---------------------------------------------------------------------------
# 4. Wiring — scan() stamps the factor surface + emits for every candle
# ---------------------------------------------------------------------------


def _filters() -> MarketFilters:
    return MarketFilters(
        categories=[], min_liquidity=0.0, max_time_to_resolution_days=365,
        blacklisted_market_ids=[],
    )


def _ctx() -> UserContext:
    return UserContext(
        user_id="u1", sub_account_id="s1", risk_profile="balanced",
        capital_allocation_pct=0.5, available_balance_usdc=1000.0, equity_usdc=1000.0,
        selected_timeframe="5m", selected_assets=("BTC",),
        max_per_trade_mode="auto", max_per_trade_usdc=None, max_per_trade_pct=None,
    )


def _market(condition_id: str = "c1", secs: float = 20.0, **extra) -> dict:
    end = datetime.now(timezone.utc) + timedelta(seconds=secs)
    m = {
        "id": "m1", "conditionId": condition_id, "slug": "btc-updown-5m-1779249900",
        "question": "BTC 5 minute up or down?", "active": True, "closed": False,
        "acceptingOrders": True, "clobTokenIds": ["yes_tok", "no_tok"],
        "endDate": end.isoformat().replace("+00:00", "Z"),
    }
    m.update(extra)
    return m


def _book(ask: float | None) -> dict:
    if ask is None:
        return {"bids": [], "asks": []}
    return {"bids": [{"price": "0.10", "size": "5"}], "asks": [{"price": str(ask), "size": "5"}]}


def _books(yes_ask: float | None, no_ask: float | None):
    async def _inner(tok: str) -> dict:
        return _book(yes_ask) if tok == "yes_tok" else _book(no_ask) if tok == "no_tok" else _book(None)
    return _inner


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _reset_momentum():
    get_tracker().reset()
    yield
    get_tracker().reset()


@pytest.fixture
def _capture(monkeypatch):
    events: list = []
    monkeypatch.setattr(fac.log, "info", lambda ev, **kw: events.append((ev, kw)))
    return events


def _factor_events(events: list) -> list[dict]:
    return [kw for ev, kw in events if ev == FACTOR_VECTOR_EVENT]


def test_surviving_candidate_carries_factor_surface(_capture):
    strat = LateEntryV3Strategy()
    with patch(_MARKETS_PATCH, new=AsyncMock(return_value=[_market()])), \
         patch(_BOOK_PATCH, new=AsyncMock(side_effect=_books(0.65, 0.20))):
        cands = _run(strat.scan(_filters(), _ctx(), evaluated_rule="close_sweep"))
    assert len(cands) == 1
    md = cands[0].metadata
    # Volatility sigma is now EXPOSED (was oracle-advisory-only per WARP-71).
    assert md["factor_volatility_sigma"] is not None and md["factor_volatility_sigma"] > 0.0
    # Liquidity / spread / depth / TTL exposed on the scorable surface.
    assert md["factor_liquidity_usdc"] is not None
    assert md["factor_orderbook_depth_usdc"] == md["factor_liquidity_usdc"]
    assert md["factor_spread"] == pytest.approx(0.85)
    assert md["factor_ttl_sec"] is not None and md["factor_ttl_sec"] > 0
    assert md["factor_evaluated_rule"] == "close_sweep"
    # Momentum is None on the first scan (only one sample) — honest "no history".
    assert md["factor_momentum"] is None
    # Exactly one dataset row emitted for this evaluated candle.
    assert len(_factor_events(_capture)) == 1


def test_emits_for_rejected_candle_decoupled_from_execution(_capture):
    # Coin-flip book (ask_diff 0.01 < 0.05) -> NO candidate, but the factor vector
    # MUST still be emitted: the dataset covers ALL evaluated candles, traded or not.
    strat = LateEntryV3Strategy()
    with patch(_MARKETS_PATCH, new=AsyncMock(return_value=[_market()])), \
         patch(_BOOK_PATCH, new=AsyncMock(side_effect=_books(0.52, 0.51))):
        cands = _run(strat.scan(_filters(), _ctx(), evaluated_rule="safe_close"))
    assert cands == []
    rows = _factor_events(_capture)
    assert len(rows) == 1
    assert rows[0]["evaluated_rule"] == "safe_close"
    assert rows[0]["volatility_sigma"] is not None  # factor still measured


def test_flag_disables_emission_and_metadata(monkeypatch, _capture):
    monkeypatch.setattr(lev3, "_factor_vector_enabled", lambda: False)
    strat = LateEntryV3Strategy()
    with patch(_MARKETS_PATCH, new=AsyncMock(return_value=[_market()])), \
         patch(_BOOK_PATCH, new=AsyncMock(side_effect=_books(0.65, 0.20))):
        cands = _run(strat.scan(_filters(), _ctx(), evaluated_rule="close_sweep"))
    assert len(cands) == 1
    assert not any(k.startswith("factor_") for k in cands[0].metadata)
    assert _factor_events(_capture) == []


def test_momentum_populates_across_scans(_capture):
    # Two scans of the same market with a controllable clock so the samples are
    # >min_gap apart and within-window -> momentum becomes measurable.
    strat = LateEntryV3Strategy()
    base = 1_000_000.0
    clock = {"t": base}

    class _DT(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return datetime.fromtimestamp(clock["t"], tz=tz or timezone.utc)

    # endDate is pinned to the fake clock base so seconds_left stays in-window as
    # the clock advances (scan1 -> 25s left, scan2 -> 10s left).
    end_iso = datetime.fromtimestamp(base + 25.0, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    mkt = _market(secs=25.0, endDate=end_iso)
    with patch(_MARKETS_PATCH, new=AsyncMock(return_value=[mkt])), \
         patch(_BOOK_PATCH, new=AsyncMock(side_effect=_books(0.60, 0.30))), \
         patch.object(lev3, "datetime", _DT):
        _run(strat.scan(_filters(), _ctx(), evaluated_rule="close_sweep"))
        clock["t"] += 15.0  # next fast-loop tick
        _run(strat.scan(_filters(), _ctx(), evaluated_rule="close_sweep"))

    rows = _factor_events(_capture)
    assert len(rows) == 2
    # Second row has >=2 in-window samples -> momentum is measurable.
    assert rows[1]["momentum"] is not None
    assert rows[1]["momentum_samples"] >= 2


def test_oracle_realized_label_rides_through(_capture):
    # Advisory oracle wired: price_to_beat (open) from metadata, price (now) from
    # the provider -> realized open->close label stamped on the dataset row.
    strat = LateEntryV3Strategy()
    edge_cfg = OracleEdgeConfig(
        enabled=True,
        price_provider=lambda sym: 104_500.0,  # now > open -> UP
        min_dist=0.0, max_dist=1.0, min_edge=0.0,
    )
    mkt = _market(priceToBeat=104_000.0)
    with patch(_MARKETS_PATCH, new=AsyncMock(return_value=[mkt])), \
         patch(_BOOK_PATCH, new=AsyncMock(side_effect=_books(0.65, 0.20))):
        cands = _run(strat.scan(_filters(), _ctx(), evaluated_rule="close_sweep", edge_cfg=edge_cfg))
    assert len(cands) == 1
    md = cands[0].metadata
    assert md["factor_realized_outcome"] == "UP"
    assert md["factor_outcome_source"] == "oracle_open_to_now"
    assert md["factor_oracle_edge"] is not None
    assert md["factor_realized_delta"] == pytest.approx((104_500.0 - 104_000.0) / 104_000.0)
