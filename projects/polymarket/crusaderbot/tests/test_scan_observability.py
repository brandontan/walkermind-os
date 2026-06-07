"""WARP-80 sub-lane 1a — strategy scan observability unit tests.

Hermetic: no DB, no network. Exercises the threshold math (distance + would-pass
at all 3 relax levels), the ContextVar sink lifecycle, and the fail-soft writer
against a fake asyncpg pool that captures the SQL + bound rows.
"""
from __future__ import annotations

import asyncio
import json

from projects.polymarket.crusaderbot.domain.research import scan_observability as so
from projects.polymarket.crusaderbot.domain.research.scan_observability import (
    ScanObservation,
    begin_sink,
    drain_sink,
    record_observation,
    record_scan_observations,
    signed_distance,
    threshold_pass_map,
)


def _run(coro):
    return asyncio.run(coro)


# ── threshold math ────────────────────────────────────────────────────────────

def test_threshold_pass_map_min_floor_gate():
    # min_ev floor = 0.10; a market with ev=0.07 fails today but the relaxed
    # floors are 0.09 / 0.075 / 0.05 → passes only at -50%.
    m = threshold_pass_map(0.07, 0.10, direction="min")
    assert m == {"-10%": False, "-25%": False, "-50%": True}


def test_threshold_pass_map_min_passes_all_when_above():
    # ev well above the floor passes at every relaxed level.
    assert threshold_pass_map(0.20, 0.10, direction="min") == {
        "-10%": True, "-25%": True, "-50%": True,
    }


def test_threshold_pass_map_max_ceiling_gate():
    # price ceiling = 0.45; a market at 0.50 is over today. Relaxed ceilings are
    # 0.495 / 0.5625 / 0.675 → passes at +25% and +50% but not +10%.
    m = threshold_pass_map(0.50, 0.45, direction="max")
    assert m == {"+10%": False, "+25%": True, "+50%": True}


def test_signed_distance_directions():
    # floor: positive when passing, negative when below.
    assert round(signed_distance(0.07, 0.10, direction="min"), 6) == -0.03
    assert round(signed_distance(0.13, 0.10, direction="min"), 6) == 0.03
    # ceiling: positive when under the cap, negative when over.
    assert round(signed_distance(0.40, 0.45, direction="max"), 6) == 0.05
    assert round(signed_distance(0.50, 0.45, direction="max"), 6) == -0.05


# ── sink lifecycle ────────────────────────────────────────────────────────────

def test_record_is_noop_without_sink():
    # No sink open → record_observation must not raise and must drop the row.
    drain_sink(None)  # ensure clean state
    record_observation(ScanObservation(strategy="weather", market_id="m1"))
    assert drain_sink(None) == []


def test_sink_collects_and_drain_resets():
    token = begin_sink()
    record_observation(ScanObservation(strategy="weather", market_id="m1", binding_filter="ev"))
    record_observation(ScanObservation(strategy="playbook", market_id="m2", binding_filter="quality"))
    drained = drain_sink(token)
    assert [o.market_id for o in drained] == ["m1", "m2"]
    # After drain the sink is closed again → further records are dropped.
    record_observation(ScanObservation(strategy="weather", market_id="m3"))
    assert drain_sink(None) == []


def test_begin_sink_installs_fresh_list():
    # A new begin_sink must not inherit rows from a prior un-drained tick.
    begin_sink()
    record_observation(ScanObservation(strategy="weather", market_id="stale"))
    token2 = begin_sink()
    record_observation(ScanObservation(strategy="weather", market_id="fresh"))
    assert [o.market_id for o in drain_sink(token2)] == ["fresh"]


# ── fail-soft writer ──────────────────────────────────────────────────────────

class _FakeConn:
    def __init__(self, store):
        self._store = store

    async def executemany(self, sql, rows):
        self._store["sql"] = sql
        self._store["rows"] = rows


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _FakePool:
    def __init__(self, store):
        self._conn = _FakeConn(store)

    def acquire(self):
        return _FakeAcquire(self._conn)


def test_record_scan_observations_writes_rows_and_serializes_jsonb():
    store: dict = {}
    obs = [
        ScanObservation(
            strategy="weather", market_id="mkt-1", zero_reason="filter_or_no_match",
            binding_filter="ev", metric_value=0.07, threshold=0.10,
            distance_to_threshold=-0.03,
            would_pass_at_threshold={"-10%": False, "-25%": False, "-50%": True},
            module_state="live",
        ),
        ScanObservation(
            strategy="playbook", market_id="mkt-2", zero_reason="filter_or_no_match",
            binding_filter="router_abstain", module_state="null_feed",
        ),
    ]
    n = _run(record_scan_observations("run-1", obs, pool=_FakePool(store)))
    assert n == 2
    assert "INSERT INTO strategy_scan_observations" in store["sql"]
    rows = store["rows"]
    assert rows[0][1] == "weather" and rows[0][2] == "mkt-1"
    # would_pass_at_threshold is serialized to a JSON string for the ::jsonb cast.
    assert json.loads(rows[0][8])["-50%"] is True
    # null/None fields stay None (playbook abstain has no numeric metric).
    assert rows[1][5] is None and rows[1][8] == "{}"


def test_record_scan_observations_empty_is_zero():
    assert _run(record_scan_observations("run-1", [], pool=_FakePool({}))) == 0


def test_record_scan_observations_failsoft_on_pool_error():
    class _BoomPool:
        def acquire(self):
            raise RuntimeError("db down")

    obs = [ScanObservation(strategy="weather", market_id="m1")]
    # A pool/DB error must be swallowed → returns 0, never raises into the scan loop.
    assert _run(record_scan_observations("run-1", obs, pool=_BoomPool())) == 0


def test_row_drops_observation_without_market_id():
    store: dict = {}
    obs = [ScanObservation(strategy="weather", market_id="")]
    assert _run(record_scan_observations("run-1", obs, pool=_FakePool(store))) == 0
