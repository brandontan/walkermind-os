"""Phase-2c-3 — walk-forward replay engine tests.

Covers the §12.1 pure units (per-trade return, metrics, walk-forward folds,
leakage + overfit detectors) and the fail-soft / inert-until-data ``replay``
orchestrator. Hermetic — no DB, no network.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from projects.polymarket.crusaderbot.domain.research import replay as RP
from projects.polymarket.crusaderbot.domain.research.replay import (
    ReplayTrade,
    compute_metrics,
    has_leakage,
    is_overfit,
    overfit_degradation,
    replay,
    trade_return,
    walk_forward_split,
)

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _trade(side="YES", entry=0.5, exit_=1.0, mins=0, res_mins=60, module="sharp_money") -> ReplayTrade:
    return ReplayTrade(
        module=module, category="MLB", side=side,
        entry_ts=_T0 + timedelta(minutes=mins),
        resolution_ts=_T0 + timedelta(minutes=res_mins),
        entry_price=entry, exit_price=exit_,
    )


# ── per-trade return ──────────────────────────────────────────────────────
def test_trade_return_yes_win():
    assert trade_return(_trade("YES", 0.5, 1.0)) == 1.0     # 0.5 → 1.0 = +100%


def test_trade_return_yes_loss():
    assert trade_return(_trade("YES", 0.5, 0.0)) == -1.0


def test_trade_return_no_win():
    # NO bought at 1-0.5=0.5, YES settles 0 → NO wins → +100%.
    assert trade_return(_trade("NO", 0.5, 0.0)) == 1.0
    # NO bought at 1-0.4=0.6, YES settles 0 → +0.4/0.6 ≈ +66.7%.
    assert abs(trade_return(_trade("NO", 0.4, 0.0)) - (0.4 / 0.6)) < 1e-9


def test_trade_return_degenerate_zero():
    assert trade_return(_trade("YES", 0.0, 1.0)) == 0.0


# ── metrics ───────────────────────────────────────────────────────────────
def test_metrics_empty_zeroed():
    m = compute_metrics([])
    assert m.n_trades == 0 and m.ev_per_trade == 0.0 and m.profit_factor == 0.0


def test_metrics_basic_stats():
    m = compute_metrics([1.0, -0.5, 1.0, -0.5], [60.0, 60.0, 60.0, 60.0])
    assert m.n_trades == 4
    assert m.win_rate == 0.5
    assert abs(m.ev_per_trade - 0.25) < 1e-9
    assert abs(m.profit_factor - 2.0) < 1e-9       # 2.0 win / 1.0 loss
    assert m.avg_holding_sec == 60.0
    assert m.sharpe > 0 and m.sortino > 0


def test_metrics_max_drawdown():
    # cum: +1, +0.5, -0.5 → peak 1.0, trough 0.5 → DD 1.0
    m = compute_metrics([1.0, -0.5, -1.0])
    assert abs(m.max_drawdown - 1.5) < 1e-9


def test_metrics_all_losses_profit_factor_zero():
    m = compute_metrics([-0.2, -0.3])
    assert m.win_rate == 0.0 and m.profit_factor == 0.0 and m.ev_per_trade < 0


# ── walk-forward ──────────────────────────────────────────────────────────
def test_walk_forward_expanding_windows():
    trades = [_trade(mins=i, res_mins=i + 1) for i in range(10)]
    folds = walk_forward_split(trades, n_splits=4)
    assert len(folds) == 4
    # expanding train, validate strictly after train
    for train, validate in folds:
        assert train and validate
        assert max(t.entry_ts for t in train) <= min(v.entry_ts for v in validate)


def test_walk_forward_too_few_trades():
    assert walk_forward_split([_trade(), _trade()], n_splits=4) == []


# ── bias detection ────────────────────────────────────────────────────────
def test_leakage_entry_after_resolution():
    assert has_leakage(_trade(mins=120, res_mins=60)) is True   # entry after resolution
    assert has_leakage(_trade(mins=0, res_mins=60)) is False


def test_overfit_detector():
    strong = compute_metrics([0.3, 0.3, 0.3])
    weak = compute_metrics([0.01, -0.01, 0.0])
    assert overfit_degradation(strong, weak) > 0
    assert is_overfit(strong, weak) is True
    assert is_overfit(strong, strong) is False


# ── replay orchestrator (fail-soft / inert until data) ────────────────────
class _Conn:
    def __init__(self, rows=None, raise_exc=False):
        self.rows = rows or []
        self.raise_exc = raise_exc

    async def fetch(self, sql, *a):
        if self.raise_exc:
            raise RuntimeError("db down")
        return self.rows


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
    return patch.object(RP, "get_pool", return_value=_Pool(conn))


def _snap(market_id, mid, mins):
    return {
        "market_id": market_id, "category": "MLB", "mid_price": mid,
        "scanned_at": _T0 + timedelta(minutes=mins),
    }


def test_replay_empty_table_inert():
    with _patch(_Conn(rows=[])):
        out = asyncio.run(replay(lambda r: ("sharp_money", "YES")))
    assert out == {}


def test_replay_failsoft_on_error():
    with _patch(_Conn(raise_exc=True)):
        out = asyncio.run(replay(lambda r: ("sharp_money", "YES")))
    assert out == {}


def test_replay_builds_trades_and_metrics():
    # market m1: entry mid 0.5 → settle 1.0 (YES win, +1.0)
    rows = [_snap("m1", 0.5, 0), _snap("m1", 0.9, 30), _snap("m1", 1.0, 60)]
    with _patch(_Conn(rows=rows)):
        out = asyncio.run(replay(lambda r: ("sharp_money", "YES")))
    assert "sharp_money" in out
    assert out["sharp_money"].n_trades == 1
    assert out["sharp_money"].ev_per_trade == 1.0
    assert out["sharp_money"].avg_holding_sec == 3600.0  # 0→60min, durations preserved


def test_replay_skips_no_decision_and_single_snapshot():
    rows = [_snap("m1", 0.5, 0), _snap("m1", 1.0, 60), _snap("m2", 0.5, 0)]
    # decide returns None → no trade; m2 has a single snapshot → skipped
    with _patch(_Conn(rows=rows)):
        out = asyncio.run(replay(lambda r: None))
    assert out == {}
