"""Phase-2c-1 — Monte Carlo robustness engine + classifier + LIVE gate tests.

Covers the dependency-free simulator (deterministic extremes + percentile),
the ROBUST/FRAGILE/UNTRADEABLE/INSUFFICIENT_DATA classifier, module grouping +
persistence in ``classify_modules``, and the fail-soft ``live_eligible`` gate.
Hermetic — no DB, no network.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from projects.polymarket.crusaderbot.domain.research import monte_carlo as MC
from projects.polymarket.crusaderbot.domain.research import robustness as RB
from projects.polymarket.crusaderbot.domain.research.monte_carlo import MCResult, simulate
from projects.polymarket.crusaderbot.domain.research.robustness import (
    Classification,
    classify,
    classify_modules,
    live_eligible,
)


def _mc(**over) -> MCResult:
    base = dict(
        sample_size=50, n_paths=2_000, horizon=200, ev_per_trade=0.05,
        ruin_probability=0.0, p95_max_drawdown=0.03, median_max_drawdown=0.01,
        p95_losing_streak=3,
    )
    base.update(over)
    return MCResult(**base)


# ── simulator ─────────────────────────────────────────────────────────────
def test_simulate_all_wins_no_drawdown_no_ruin():
    res = simulate([0.2] * 100, bet_fraction=0.06, n_paths=50, horizon=100, seed=1)
    assert res.ev_per_trade == pytest.approx(0.2)
    assert res.ruin_probability == 0.0
    assert res.p95_max_drawdown == 0.0 and res.p95_losing_streak == 0


def test_simulate_all_losses_ruin_certain():
    res = simulate([-0.5] * 100, bet_fraction=0.06, n_paths=50, horizon=200, seed=1)
    assert res.ev_per_trade == pytest.approx(-0.5)
    assert res.ruin_probability == 1.0
    assert res.p95_max_drawdown > 0.4


def test_simulate_empty_returns_zeroed():
    res = simulate([], bet_fraction=0.06)
    assert res.sample_size == 0 and res.ruin_probability == 0.0


def test_simulate_is_deterministic_with_seed():
    a = simulate([0.3, -0.4, 0.1], bet_fraction=0.06, n_paths=100, seed=7)
    b = simulate([0.3, -0.4, 0.1], bet_fraction=0.06, n_paths=100, seed=7)
    assert a == b


def test_percentile_nearest_rank():
    assert MC._percentile([10.0, 20.0, 30.0, 40.0], 50.0) == 20.0
    assert MC._percentile([], 95.0) == 0.0
    assert MC._percentile([5.0], 95.0) == 5.0


# ── classifier ────────────────────────────────────────────────────────────
def test_classify_insufficient_data():
    assert classify(_mc(sample_size=10)) is Classification.INSUFFICIENT_DATA


def test_classify_untradeable_negative_ev():
    assert classify(_mc(ev_per_trade=-0.01)) is Classification.UNTRADEABLE


def test_classify_untradeable_high_ruin():
    assert classify(_mc(ruin_probability=0.10)) is Classification.UNTRADEABLE


def test_classify_fragile_on_deep_drawdown():
    assert classify(_mc(p95_max_drawdown=0.10)) is Classification.FRAGILE


def test_classify_fragile_on_long_streak():
    assert classify(_mc(p95_losing_streak=9)) is Classification.FRAGILE


def test_classify_robust():
    assert classify(_mc()) is Classification.ROBUST


# ── fake pool/conn ────────────────────────────────────────────────────────
class _Conn:
    def __init__(self, *, fetch_rows=None, fetchrow_val=None, raise_on=None):
        self.fetch_rows = fetch_rows or []
        self.fetchrow_val = fetchrow_val
        self.raise_on = raise_on or set()
        self.executemany_rows = None

        self.fetchrow_args: tuple = ()

    async def fetch(self, sql, *a):
        if "fetch" in self.raise_on:
            raise RuntimeError("db down")
        return self.fetch_rows

    async def fetchrow(self, sql, *a):
        self.fetchrow_args = a
        if "fetchrow" in self.raise_on:
            raise RuntimeError("db down")
        return self.fetchrow_val

    async def executemany(self, sql, rows):
        self.executemany_rows = rows


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


def _patch(conn):
    return patch.object(RB, "get_pool", return_value=_Pool(conn))


# ── classify_modules ──────────────────────────────────────────────────────
def test_classify_modules_groups_and_persists():
    rows = (
        [{"module": "sharp_money", "pnl_usdc": 6.0, "size_usdc": 20.0}] * 40
        + [{"module": "closing_edge", "pnl_usdc": -20.0, "size_usdc": 20.0}] * 40
    )
    conn = _Conn(fetch_rows=rows)
    with _patch(conn):
        out = asyncio.run(classify_modules(seed=1))
    by = {r.module: r for r in out}
    assert set(by) == {"sharp_money", "closing_edge"}
    assert by["sharp_money"].classification is Classification.ROBUST
    assert by["closing_edge"].classification is Classification.UNTRADEABLE
    assert conn.executemany_rows is not None and len(conn.executemany_rows) == 2


def test_classify_modules_failsoft_on_read_error():
    conn = _Conn(raise_on={"fetch"})
    with _patch(conn):
        out = asyncio.run(classify_modules())
    assert out == []


# ── live_eligible gate ────────────────────────────────────────────────────
def test_live_eligible_untradeable_blocks():
    conn = _Conn(fetchrow_val={"classification": "UNTRADEABLE"})
    with _patch(conn):
        ok, reason = asyncio.run(live_eligible("sharp_money"))
    assert ok is False and reason == "untradeable_paper_only"


def test_live_eligible_filters_by_mode():
    conn = _Conn(fetchrow_val={"classification": "ROBUST"})
    with _patch(conn):
        asyncio.run(live_eligible("sharp_money", mode="live"))
    assert conn.fetchrow_args == ("sharp_money", "balanced", "live")  # mode pinned


def test_classify_modules_persists_all_label_when_mode_none():
    rows = [{"module": "m", "pnl_usdc": 6.0, "size_usdc": 20.0}] * 40
    conn = _Conn(fetch_rows=rows)
    with _patch(conn):
        asyncio.run(classify_modules(mode=None, seed=1))
    assert conn.executemany_rows[0][-1] == "all"  # NOT NULL satisfied for mode=None


@pytest.mark.parametrize("cls", ["ROBUST", "FRAGILE", "INSUFFICIENT_DATA"])
def test_live_eligible_non_untradeable_allows(cls):
    conn = _Conn(fetchrow_val={"classification": cls})
    with _patch(conn):
        ok, _ = asyncio.run(live_eligible("m"))
    assert ok is True


def test_live_eligible_unclassified_allows():
    conn = _Conn(fetchrow_val=None)
    with _patch(conn):
        ok, reason = asyncio.run(live_eligible("m"))
    assert ok is True and reason == "unclassified_allow"


def test_live_eligible_failsoft_allows():
    conn = _Conn(raise_on={"fetchrow"})
    with _patch(conn):
        ok, reason = asyncio.run(live_eligible("m"))
    assert ok is True and reason == "gate_read_failed_allow"
