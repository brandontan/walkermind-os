"""Behaviour + safety pins for the #1815 late_entry_v3 realized-cohort export.

Owner directive (#1815): the calibration audit is READ-ONLY research; no live
behaviour change, no order intent, no real fund movement, no live-guard flip.
These tests pin:

  1. Bucket math is correct (n, wins, losses, win-rate, realized P&L, mean
     entry/size, exit-reason histogram).
  2. The ``MIN_OOS_TRADES`` floor (mirrors ``late_entry_oos.MIN_OOS_TRADES``)
     produces ``UNPROVEN_THIN`` for thin buckets and ``REALIZED`` only when
     ``n >= 20``.
  3. The simulated net EV per trade subtracts a transparent round-trip cost
     model (same shape as ``late_entry_oos.CostModel``) from realized gross
     return — never a live CLOB call.
  4. The query is SELECT-only, filtered to PAPER ``late_entry_v3`` closed rows,
     and excludes forced / horizon-exceeded / paper_to_live / already-closed
     exits which are not strategy-driven outcomes.
  5. Source-pin: the module never imports the CLOB / Bridge / Relayer / Gamma
     adapters, never emits an order intent, never reads or flips a live guard.
"""
from __future__ import annotations

import asyncio
import pathlib
from typing import Any
from unittest.mock import patch

from projects.polymarket.crusaderbot.domain.research import (
    late_entry_realized_cohort as lerc,
)
from projects.polymarket.crusaderbot.domain.research.late_entry_oos import (
    MIN_OOS_TRADES,
    CostModel,
)

_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Hermetic DB stand-in.
# ---------------------------------------------------------------------------

class _FakeConn:
    def __init__(self, rows: list[dict[str, Any]]):
        self._rows = rows
        self.executed: list[str] = []

    async def fetch(self, sql: str, *args):
        self.executed.append(sql)
        return list(self._rows)


class _FakePool:
    def __init__(self, conn: _FakeConn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _Ctx:
            async def __aenter__(self_):
                return conn

            async def __aexit__(self_, *exc):
                return False

        return _Ctx()


def _row(*, preset="close_sweep", side="YES", entry_price=0.55, size_usdc=10.0,
         pnl_usdc=0.5, exit_reason="tp_hit") -> dict[str, Any]:
    return {
        "active_preset": preset,
        "side": side,
        "entry_price": entry_price,
        "size_usdc": size_usdc,
        "pnl_usdc": pnl_usdc,
        "exit_reason": exit_reason,
    }


def _build(rows: list[dict[str, Any]], cost: CostModel | None = None) -> lerc.CalibrationReport:
    conn = _FakeConn(rows)
    pool = _FakePool(conn)
    with patch.object(lerc, "get_pool", lambda: pool):
        return _run(lerc.build_report(cost=cost))


# ---------------------------------------------------------------------------
# 1. Bucket math: a trivial 2-trade cohort with one win and one loss.
# ---------------------------------------------------------------------------

def test_bucket_math_win_and_loss() -> None:
    rows = [
        _row(pnl_usdc=2.0, exit_reason="tp_hit"),
        _row(pnl_usdc=-1.0, exit_reason="sl_hit"),
    ]
    report = _build(rows)
    assert report.total_trades == 2
    assert len(report.buckets) == 1
    b = report.buckets[0]
    assert b.preset == "close_sweep" and b.side == "YES"
    assert b.n_trades == 2
    assert b.wins == 1 and b.losses == 1 and b.breakeven == 0
    assert b.win_rate == 0.5
    assert b.realized_pnl_usdc == 1.0
    assert b.realized_mean_pnl_per_trade == 0.5
    assert b.exit_reason_counts == {"tp_hit": 1, "sl_hit": 1}


def test_buckets_split_by_preset_and_side() -> None:
    rows = [
        _row(preset="close_sweep", side="YES"),
        _row(preset="close_sweep", side="NO"),
        _row(preset="safe_close", side="YES"),
        _row(preset="flip_hunter", side="NO"),
    ]
    report = _build(rows)
    keys = {(b.preset, b.side) for b in report.buckets}
    assert keys == {
        ("close_sweep", "YES"), ("close_sweep", "NO"),
        ("safe_close", "YES"), ("flip_hunter", "NO"),
    }


# ---------------------------------------------------------------------------
# 2. UNPROVEN_THIN vs REALIZED gating mirrors late_entry_oos.MIN_OOS_TRADES.
# ---------------------------------------------------------------------------

def test_thin_bucket_is_unproven() -> None:
    rows = [_row()] * (MIN_OOS_TRADES - 1)
    report = _build(rows)
    assert report.buckets[0].status == "UNPROVEN_THIN"
    assert report.buckets[0].ready_for_verdict is False
    assert report.has_any_realized_bucket is False


def test_bucket_at_floor_is_realized() -> None:
    rows = [_row()] * MIN_OOS_TRADES
    report = _build(rows)
    assert report.buckets[0].status == "REALIZED"
    assert report.has_any_realized_bucket is True


# ---------------------------------------------------------------------------
# 3. Simulated net EV subtracts the transparent cost model.
# ---------------------------------------------------------------------------

def test_simulated_net_ev_subtracts_round_trip_cost() -> None:
    # YES at entry 0.50, size 10 USDC, gross +2 USDC -> gross return per share
    # = +0.20 (i.e. +2000 bps). Round-trip cost at notional 0.50 with default
    # tick 0.01 + 1 tick/side = 2 * 0.01 / 0.50 = 0.04 (i.e. +400 bps). Net EV
    # = +1600 bps.
    rows = [_row(side="YES", entry_price=0.50, size_usdc=10.0, pnl_usdc=2.0)]
    report = _build(rows)
    b = report.buckets[0]
    assert b.sim_cost_bps_per_trade == 400.0
    assert b.sim_net_ev_bps == 1600.0


def test_simulated_cost_for_no_side_uses_one_minus_price_notional() -> None:
    # NO at entry 0.20 -> NO-side notional = 1 - 0.20 = 0.80. Round-trip cost
    # = 2 * 0.01 / 0.80 = 0.025 (250 bps).
    rows = [_row(side="NO", entry_price=0.20, size_usdc=10.0, pnl_usdc=0.0)]
    report = _build(rows)
    b = report.buckets[0]
    assert b.sim_cost_bps_per_trade == 250.0
    assert b.sim_net_ev_bps == -250.0


def test_zero_fee_cost_model_is_documented_default() -> None:
    report = _build([_row()])
    assert report.cost_model["fee_bps"] == 0.0
    assert report.cost_model["tick_size"] == 0.01
    assert report.cost_model["slip_ticks_per_side"] == 1.0


# ---------------------------------------------------------------------------
# 4. Query filters: paper + closed + late_entry_v3 + excludes forced exits.
# ---------------------------------------------------------------------------

def test_query_is_read_only_and_scoped_correctly() -> None:
    conn = _FakeConn([])
    pool = _FakePool(conn)
    with patch.object(lerc, "get_pool", lambda: pool):
        _run(lerc.build_report())
    assert len(conn.executed) == 1
    sql = conn.executed[0]
    upper = sql.upper().strip()
    assert upper.startswith("SELECT") or upper.startswith("\n        SELECT")
    # Hard scope conditions.
    assert "mode = 'paper'" in sql
    assert "status = 'closed'" in sql
    assert "strategy_type = 'late_entry_v3'" in sql
    assert "pnl_usdc IS NOT NULL" in sql
    # Forced-exit / archived-cleanup rows are excluded.
    for excluded in ("force_close", "horizon_exceeded", "market_expired",
                     "paper_to_live_switch", "already_closed"):
        assert excluded in sql
    # NULL exit_reason is NOT silently dropped (Gemini SQL NULL fix): the
    # predicate explicitly admits NULL via ``exit_reason IS NULL OR ...``.
    assert "exit_reason IS NULL" in sql
    # No mutation verbs, ever.
    for verb in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "ALTER ", "TRUNCATE "):
        assert verb not in upper


def test_rows_with_null_exit_reason_still_count_in_cohort() -> None:
    """A NULL exit_reason on a closed late_entry_v3 row must be retained
    (Gemini-flagged: ``NULL NOT IN (...)`` is NULL, which would drop the row)."""
    rows = [_row(exit_reason=None, pnl_usdc=1.0)] * 25  # n >= MIN_OOS_TRADES
    report = _build(rows)
    assert report.total_trades == 25
    assert len(report.buckets) == 1
    b = report.buckets[0]
    assert b.n_trades == 25
    # ``None`` exit_reason renders as the histogram key ``"unknown"``.
    assert b.exit_reason_counts == {"unknown": 25}


# ---------------------------------------------------------------------------
# 5. Source-pin: the module is research-only — no CLOB/Bridge/Relayer/Gamma
#    adapters, no order intent, no live-guard flag access.
# ---------------------------------------------------------------------------

def test_module_source_is_research_only_no_live_path() -> None:
    src = (_ROOT / "domain/research/late_entry_realized_cohort.py").read_text(encoding="utf-8")
    forbidden = (
        "from ...integrations.clob",
        "from ...integrations.polymarket",
        "from ...integrations.polymarket_bridge",
        "from ...services.bridge",
        "from ...domain.execution.live",
        "from ...domain.execution.router",
        "from ...domain.execution.paper",
        "from ...wallet.ledger",
        "from ...wallet.custody",
        "from ...wallet.deposit_assets",
        "USE_REAL_CLOB",
        "EXECUTION_PATH_VALIDATED",
        "ENABLE_LIVE_TRADING",
        "CAPITAL_MODE_CONFIRMED",
        "assert_live_guards",
        "send_user",
        "post_order",
        "submit_order",
        "router.execute",
        "INSERT INTO",
        "UPDATE ",
        "DELETE FROM",
    )
    for f in forbidden:
        assert f not in src, f"realized-cohort export must not reference {f!r}"


# ---------------------------------------------------------------------------
# Renderer: Markdown table is stable and lists every bucket.
# ---------------------------------------------------------------------------

def test_markdown_renderer_includes_every_bucket_and_status() -> None:
    rows = [_row(preset="close_sweep", side="YES")] * 25
    rows += [_row(preset="safe_close", side="NO")] * 5
    report = _build(rows)
    md = lerc.render_markdown(report)
    assert "close_sweep" in md and "safe_close" in md
    assert "REALIZED" in md
    assert "UNPROVEN_THIN" in md
    assert "Universe: BTC/ETH 5m/15m" in md
