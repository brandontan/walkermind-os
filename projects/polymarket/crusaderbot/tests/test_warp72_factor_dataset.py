"""WARP-72 Phase 2 prep — durable factor-vector dataset sink tests.

Covers the upsert recorder (column/value alignment, latest-wins UPSERT shape,
per-candle write throttle = the GRAIN guard, gating), the router-selection
backfill UPDATE, and the settlement backfill (open->close resolution, aged-out
'unresolved', still-in-window retry). Hermetic — no DB, no network: a fake
asyncpg pool/connection captures the SQL + bound args.
"""
from __future__ import annotations

import asyncio

import pytest

from projects.polymarket.crusaderbot.domain.research import factor_dataset as fd
from projects.polymarket.crusaderbot.domain.research.factor_dataset import (
    backfill_factor_settlement,
    mark_router_selection_row,
    record_factor_vector,
)
from projects.polymarket.crusaderbot.domain.signal.factors import FactorVector


# ── fake asyncpg pool/conn ────────────────────────────────────────────────
class _Conn:
    def __init__(self, fetch_rows=None):
        self.calls: list[tuple] = []       # (sql, args)
        self._fetch_rows = fetch_rows or []

    async def execute(self, sql, *args):
        self.calls.append((sql, args))

    async def fetch(self, sql, *args):
        self.calls.append((sql, args))
        return self._fetch_rows


class _Pool:
    def __init__(self, conn):
        self._c = conn

    def acquire(self):
        c = self._c

        class _Ctx:
            async def __aenter__(self_inner):
                return c

            async def __aexit__(self_inner, *a):
                return False

        return _Ctx()


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _reset_throttle():
    fd._last_write.clear()
    yield
    fd._last_write.clear()


def _fv(condition_id="0xC1", **over) -> FactorVector:
    base = dict(
        market_id=condition_id, condition_id=condition_id, slug="btc-updown-5m-1",
        asset="btc", timeframe="5m", evaluated_rule="close_sweep",
        momentum=0.001, momentum_delta=0.05, momentum_span_sec=30.0, momentum_samples=3,
        volatility_sigma=0.0001, liquidity_usdc=1234.0, spread=0.98,
        orderbook_depth_usdc=1234.0, ttl_sec=20.0, oracle_edge=0.03,
        oracle_edge_status="computed", oracle_would_pass=True, oracle_delta=0.001,
        fav_side="YES", entry_side="YES", fav_price=0.65, entry_price=0.65,
        ask_diff=0.45, complete_set_edge=0.02, underdog_mode=False,
        realized_outcome="UP", realized_delta=0.001, outcome_source="provisional",
        outcome_observed_rem_sec=20.0, candle_open_epoch=1.0, candle_close_epoch=301.0,
    )
    base.update(over)
    return FactorVector(**base)


# ── recorder: column/value alignment + UPSERT shape ───────────────────────
def test_record_upsert_args_aligned():
    conn = _Conn()
    ok = _run(record_factor_vector(_fv(), pool=_Pool(conn), now=1000.0))
    assert ok is True
    sql, args = conn.calls[0]
    assert "INSERT INTO factor_vectors" in sql
    assert "ON CONFLICT (condition_id) DO UPDATE" in sql
    assert "WHERE factor_vectors.settled = FALSE" in sql  # settled rows immutable
    assert len(args) == len(fd._COLS) == 34
    assert args[0] == "0xC1"               # condition_id first
    assert args[fd._COLS.index("volatility_sigma")] == 0.0001
    assert args[fd._COLS.index("selected_by_router")] is False  # coerced bool


def test_record_throttle_collapses_scan_ticks():
    # GRAIN guard: repeated scans of the same candle within the gap write ONCE.
    conn = _Conn()
    pool = _Pool(conn)
    assert _run(record_factor_vector(_fv(), pool=pool, now=1000.0)) is True
    assert _run(record_factor_vector(_fv(), pool=pool, now=1002.0)) is False  # < gap
    assert _run(record_factor_vector(_fv(), pool=pool, now=1010.0)) is True   # > gap
    assert len(conn.calls) == 2  # only the two un-throttled writes hit the DB


def test_record_distinct_candles_not_throttled():
    conn = _Conn()
    pool = _Pool(conn)
    assert _run(record_factor_vector(_fv("0xA"), pool=pool, now=1000.0)) is True
    assert _run(record_factor_vector(_fv("0xB"), pool=pool, now=1000.0)) is True
    assert len(conn.calls) == 2


def test_record_skips_empty_condition_id():
    conn = _Conn()
    # condition_id "" -> SignalCandidate-style guard returns False, no write.
    fv = _fv()
    object.__setattr__(fv, "condition_id", "")
    assert _run(record_factor_vector(fv, pool=_Pool(conn), now=1.0)) is False
    assert conn.calls == []


def test_record_failsoft_on_db_error():
    class _BadConn(_Conn):
        async def execute(self, sql, *args):
            raise RuntimeError("db down")

    assert _run(record_factor_vector(_fv(), pool=_Pool(_BadConn()), now=1.0)) is False


def test_record_failed_write_releases_throttle_for_retry():
    # A failed write must NOT poison the throttle cache — otherwise the candle's
    # final pre-close snapshot could be dropped for the whole gap window.
    class _BadConn(_Conn):
        async def execute(self, sql, *args):
            raise RuntimeError("db down")

    assert _run(record_factor_vector(_fv("0xZ"), pool=_Pool(_BadConn()), now=1000.0)) is False
    assert "0xZ" not in fd._last_write  # slot released on failure
    # Retry within the gap is allowed (not throttled) and succeeds on a good pool.
    good = _Conn()
    assert _run(record_factor_vector(_fv("0xZ"), pool=_Pool(good), now=1001.0)) is True
    assert len(good.calls) == 1


# ── router-selection backfill UPDATE ──────────────────────────────────────
def test_mark_router_selection_row():
    conn = _Conn()
    ok = _run(mark_router_selection_row("0xC1", "safe_close", pool=_Pool(conn)))
    assert ok is True
    sql, args = conn.calls[0]
    assert "UPDATE factor_vectors" in sql and "router_selected_rule" in sql
    assert "settled = FALSE" in sql
    assert args == ("0xC1", "safe_close")


# ── settlement backfill: open->close resolution ───────────────────────────
def _rows(*specs):
    # spec = (condition_id, asset, open_epoch, close_epoch)
    return [
        {"condition_id": c, "asset": a, "candle_open_epoch": o, "candle_close_epoch": cl}
        for (c, a, o, cl) in specs
    ]


def test_settlement_resolves_open_to_close():
    conn = _Conn(fetch_rows=_rows(("0xC1", "btc", 1000.0, 1300.0)))
    prices = {("btc/usd", 1000.0): 104_000.0, ("btc/usd", 1300.0): 104_600.0}
    n = _run(backfill_factor_settlement(
        lambda s, e: prices.get((s, e)), now=2000.0, pool=_Pool(conn),
    ))
    assert n == 1
    # First call is the SELECT; the settle UPDATE follows.
    update_sql, update_args = conn.calls[-1]
    assert "UPDATE factor_vectors" in update_sql and "settled = TRUE" in update_sql
    # _write_settled args: (condition_id, outcome, delta, open, close, source)
    assert update_args[0] == "0xC1"
    assert update_args[1] == "UP"
    assert update_args[4] == 104_600.0
    assert update_args[5] == "open_to_close"


def test_settlement_aged_out_marks_unresolved():
    # close far in the past + no price in ring -> give up, mark 'unresolved'.
    conn = _Conn(fetch_rows=_rows(("0xC1", "btc", 1.0, 100.0)))
    n = _run(backfill_factor_settlement(
        lambda s, e: None, now=10_000.0, ring_window_sec=1800.0, pool=_Pool(conn),
    ))
    assert n == 0  # not a resolved label
    _, update_args = conn.calls[-1]
    assert update_args[0] == "0xC1" and update_args[5] == "unresolved"


def test_settlement_recent_unresolved_left_for_retry():
    # close just happened, price not yet in ring -> no UPDATE, retry next pass.
    conn = _Conn(fetch_rows=_rows(("0xC1", "btc", 1700.0, 1990.0)))
    n = _run(backfill_factor_settlement(
        lambda s, e: None, now=2000.0, ring_window_sec=1800.0, pool=_Pool(conn),
    ))
    assert n == 0
    assert len(conn.calls) == 1  # only the SELECT; no settle/unresolve write
