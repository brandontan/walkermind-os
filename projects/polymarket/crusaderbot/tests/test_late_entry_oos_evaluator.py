"""WARP-81 Phase 2 — late_entry_v3 OOS drift evaluator unit tests.

Hermetic: no DB, no network. Synthetic factor_vectors-shaped rows verify the
realized-EV convention, the horizon selection, the two-sample CI math, the
chronological train/test split, and the per-cell verdict logic.
"""
from __future__ import annotations

from projects.polymarket.crusaderbot.domain.research.late_entry_oos_evaluator import (
    DEFAULT_TEST_FRACTION,
    evaluate_oos,
    normalize_cell_key,
    realized_ev,
    render_report,
    row_outcome,
    two_sample_diff_ci,
    winning_side,
)


def _row(
    *,
    asset="btc",
    timeframe="5m",
    entry_side="YES",
    entry_price=0.5,
    realized_outcome="UP",
    realized_outcome_safe_close=None,
    evaluated_rule="close_sweep",
    router_selected_rule=None,
    selected_by_router=False,
    epoch=0.0,
) -> dict:
    return {
        "asset": asset,
        "timeframe": timeframe,
        "entry_side": entry_side,
        "entry_price": entry_price,
        "realized_outcome": realized_outcome,
        "realized_outcome_safe_close": realized_outcome_safe_close,
        "evaluated_rule": evaluated_rule,
        "router_selected_rule": router_selected_rule,
        "selected_by_router": selected_by_router,
        "candle_close_epoch": epoch,
        "settled_at": None,
    }


# ── convention ────────────────────────────────────────────────────────────────

def test_winning_side_mapping():
    assert winning_side("UP") == "YES"
    assert winning_side("DOWN") == "NO"
    assert winning_side("FLAT") is None
    assert winning_side(None) is None


def test_realized_ev_favorite_win_and_loss():
    # YES entry @0.4, candle UP → YES wins → ev = 1 - 0.4 = +0.6
    assert round(realized_ev(_row(entry_side="YES", entry_price=0.4, realized_outcome="UP")), 6) == 0.6
    # YES entry @0.4, candle DOWN → loss → ev = -0.4
    assert round(realized_ev(_row(entry_side="YES", entry_price=0.4, realized_outcome="DOWN")), 6) == -0.4
    # NO entry @0.7, candle DOWN → NO wins → ev = 1 - 0.7 = +0.3
    assert round(realized_ev(_row(entry_side="NO", entry_price=0.7, realized_outcome="DOWN")), 6) == 0.3


def test_realized_ev_undecidable_returns_none():
    assert realized_ev(_row(realized_outcome="FLAT")) is None          # push
    assert realized_ev(_row(entry_side="?")) is None                   # bad side
    assert realized_ev(_row(entry_price=None)) is None                 # no price
    assert realized_ev(_row(entry_price=1.4)) is None                  # price out of [0,1]


def test_safe_close_horizon_overrides_outcome():
    # safe_close rule: realized_outcome=UP but safe_close horizon=DOWN → use DOWN.
    r = _row(
        entry_side="YES", entry_price=0.5,
        realized_outcome="UP", realized_outcome_safe_close="DOWN",
        evaluated_rule="safe_close",
    )
    assert row_outcome(r) == "DOWN"
    assert round(realized_ev(r), 6) == -0.5  # YES loses on the safe-close horizon
    # close_sweep rule ignores the safe_close column → uses realized_outcome=UP.
    r2 = _row(
        entry_side="YES", entry_price=0.5,
        realized_outcome="UP", realized_outcome_safe_close="DOWN",
        evaluated_rule="close_sweep",
    )
    assert row_outcome(r2) == "UP"
    assert round(realized_ev(r2), 6) == 0.5


def test_router_selected_rule_drives_horizon():
    # evaluated_rule=close_sweep but the router selected safe_close → safe horizon.
    r = _row(
        realized_outcome="UP", realized_outcome_safe_close="DOWN",
        evaluated_rule="close_sweep", router_selected_rule="safe_close",
        selected_by_router=True,
    )
    assert row_outcome(r) == "DOWN"


def test_normalize_cell_key():
    assert normalize_cell_key("btc", "5m") == "BTC/5m"
    assert normalize_cell_key(None, "5m") is None
    assert normalize_cell_key("eth", "") is None


# ── stats ─────────────────────────────────────────────────────────────────────

def test_two_sample_diff_ci_basic():
    a = [0.0, 0.0, 0.0, 0.0]   # in-sample mean 0
    b = [1.0, 1.0, 1.0, 1.0]   # oos mean 1
    diff, se, lo, hi = two_sample_diff_ci(a, b)
    assert diff == 1.0 and se == 0.0 and lo == 1.0 and hi == 1.0  # zero variance


def test_two_sample_diff_ci_with_variance_straddles_zero():
    a = [0.1, -0.1, 0.1, -0.1, 0.0]
    b = [0.0, 0.1, -0.1, 0.05, -0.05]
    diff, se, lo, hi = two_sample_diff_ci(a, b)
    assert lo < 0.0 < hi  # noisy, near-equal means → CI straddles 0


# ── evaluator: verdicts ───────────────────────────────────────────────────────

def _cell_rows(n, *, in_win, oos_win, n_oos, price=0.5):
    """n rows in one cell, oldest first; first (n-n_oos) controlled by in_win,
    last n_oos by oos_win. Win → YES/UP, loss → YES/DOWN."""
    rows = []
    for i in range(n):
        is_oos = i >= (n - n_oos)
        win = oos_win if is_oos else in_win
        rows.append(_row(
            entry_side="YES", entry_price=price,
            realized_outcome="UP" if win else "DOWN", epoch=float(i),
        ))
    return rows


def test_verdict_degrades_when_oos_collapses():
    # 100 rows: 70 in-sample winners (+0.5), 30 OOS losers (-0.5).
    rows = _cell_rows(100, in_win=True, oos_win=False, n_oos=30)
    rep = evaluate_oos(rows)
    cell = rep.cells[0]
    assert cell.cell == "BTC/5m"
    assert cell.n_in == 70 and cell.n_oos == 30
    assert round(cell.in_sample_ev, 4) == 0.5
    assert round(cell.oos_ev, 4) == -0.5
    assert round(cell.drift, 4) == -1.0
    assert cell.significant is True
    assert cell.verdict == "degrades"
    assert round(cell.in_hit_rate, 4) == 1.0 and round(cell.oos_hit_rate, 4) == 0.0


def test_verdict_holds_when_stable():
    # 100 winners throughout → drift 0, not significant → holds.
    rows = _cell_rows(100, in_win=True, oos_win=True, n_oos=30)
    cell = evaluate_oos(rows).cells[0]
    assert round(cell.drift, 4) == 0.0
    assert cell.significant is False
    assert cell.verdict == "holds"


def test_verdict_inconclusive_when_thin():
    # 20 rows → OOS slice < MIN_PER_SPLIT (30) → inconclusive regardless of drift.
    rows = _cell_rows(20, in_win=True, oos_win=False, n_oos=6)
    cell = evaluate_oos(rows).cells[0]
    assert cell.verdict == "inconclusive_thin"


def test_chronological_ordering_uses_epoch():
    # Insert OUT of order: a late loser (epoch 9) and early winners (epoch 0-2).
    rows = [
        _row(realized_outcome="DOWN", epoch=9.0),  # newest → OOS
        _row(realized_outcome="UP", epoch=0.0),
        _row(realized_outcome="UP", epoch=1.0),
        _row(realized_outcome="UP", epoch=2.0),
    ]
    cell = evaluate_oos(rows).cells[0]
    # 4 rows, test_fraction 0.30 → n_oos=1 (the epoch=9 loser), in=3 winners.
    assert cell.n_in == 3 and cell.n_oos == 1
    assert round(cell.in_sample_ev, 4) == 0.5
    assert round(cell.oos_ev, 4) == -0.5


def test_multi_cell_separation_and_overall():
    btc = _cell_rows(100, in_win=True, oos_win=False, n_oos=30)
    eth = [_row(asset="eth", realized_outcome="UP", epoch=float(i)) for i in range(100)]
    rep = evaluate_oos(btc + eth)
    cells = {c.cell: c for c in rep.cells}
    assert set(cells) == {"BTC/5m", "ETH/5m"}
    assert cells["BTC/5m"].verdict == "degrades"
    assert cells["ETH/5m"].verdict == "holds"
    assert rep.overall is not None and rep.overall.cell == "OVERALL"
    assert rep.overall.n_total == 200


def test_undecidable_rows_excluded():
    rows = [_row(realized_outcome="UP", epoch=float(i)) for i in range(50)]
    rows += [_row(realized_outcome="FLAT", epoch=float(100 + i)) for i in range(50)]  # all pushes
    cell = evaluate_oos(rows).cells[0]
    assert cell.n_total == 50  # the 50 FLAT pushes are dropped, not counted


def test_render_report_contains_table_and_significance_marker():
    rows = _cell_rows(100, in_win=True, oos_win=False, n_oos=30)
    out = render_report(evaluate_oos(rows))
    assert "in-sample EV/trade" in out and "OOS EV/trade" in out
    assert "BTC/5m" in out and "OVERALL" in out
    assert "degrades" in out
    assert "*" in out  # significant drift marker
    assert f"test_fraction={DEFAULT_TEST_FRACTION:.0%}" in out
