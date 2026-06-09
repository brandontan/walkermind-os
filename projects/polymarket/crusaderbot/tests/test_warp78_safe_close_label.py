"""WARP-78 label fix — safe_close-horizon realized label tests.

The settlement backfill now resolves, alongside the open→close label, the
underlying direction at open→(close − 30s) — safe_close's real force-exit horizon —
and writes it to the additive realized_outcome_safe_close / _delta columns. These
tests prove the horizon outcome is computed from the ring and can DIFFER from
open→close (the bias / degeneracy-break Phase 0 identified). Hermetic — fake pool.
"""
from __future__ import annotations

import asyncio

import pytest

from projects.polymarket.crusaderbot.domain.research import factor_dataset as fd
from projects.polymarket.crusaderbot.domain.research.factor_dataset import (
    backfill_factor_settlement,
)


class _Conn:
    def __init__(self, fetch_rows=None):
        self.calls: list[tuple] = []
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


def _row(open_epoch=1000.0, close_epoch=1300.0):
    return {
        "condition_id": "0xC1", "asset": "btc",
        "candle_open_epoch": open_epoch, "candle_close_epoch": close_epoch,
    }


def _update_call(conn: _Conn):
    return next(c for c in conn.calls if "UPDATE factor_vectors" in c[0])


def test_safe_close_label_differs_from_open_close():
    # open=100 (t1000); close=102 UP (t1300); close-30=99 DOWN (t1270).
    prices = {1000.0: 100.0, 1300.0: 102.0, 1270.0: 99.0}

    def price_at(symbol, epoch):
        return prices.get(float(epoch))

    conn = _Conn(fetch_rows=[_row()])
    n = _run(backfill_factor_settlement(price_at, now=1400.0, pool=_Pool(conn)))
    assert n == 1
    sql, args = _update_call(conn)
    assert "realized_outcome_safe_close" in sql
    assert "realized_delta_safe_close" in sql
    # _write_settled arg order: cid, outcome, delta, open, close, source, sc_out, sc_delta
    assert args[1] == "UP"      # open→close
    assert args[6] == "DOWN"    # open→(close-30s): the safe_close horizon DIFFERS
    assert args[7] is not None and args[7] < 0  # negative delta (100→99)


def test_safe_close_label_null_when_horizon_tick_missing():
    # No tick at close-30 (t1270) → sc label stays None; open→close still settles.
    prices = {1000.0: 100.0, 1300.0: 102.0}

    def price_at(symbol, epoch):
        return prices.get(float(epoch))

    conn = _Conn(fetch_rows=[_row()])
    n = _run(backfill_factor_settlement(price_at, now=1400.0, pool=_Pool(conn)))
    assert n == 1
    _sql, args = _update_call(conn)
    assert args[1] == "UP"        # open→close resolved
    assert args[6] is None        # safe_close horizon unresolved → NULL
    assert args[7] is None


def test_lead_constant_is_thirty():
    assert fd.SAFE_CLOSE_EXIT_LEAD_SEC == 30.0
