"""Hermetic coverage for the WARP-78 Track D holdout report renderer.

No DB, no network. Verifies the 6 required sections render, canonical rule
keys are used, and the Track C verdict logic (PASS / FAIL / RETRY) is correct.
"""
from __future__ import annotations

from projects.polymarket.crusaderbot.scripts.report_cutover_holdout import (
    CUTOVER_CELLS,
    TARGET_CELLS,
    CellStats,
    Criteria,
    apply_criteria,
    compute_report,
    render_markdown,
    _demo_rows,
)


def _strong_cells():
    cells = {}
    for ck in TARGET_CELLS:
        cs = CellStats(cell=ck, settled=210, holdout_n=63, decided=60)
        cs.comp_ev_sum = 60 * 0.03
        cs.deltas = [0.03] * 60
        cells[ck] = cs
    overall = CellStats(cell="overall", settled=840, holdout_n=252, decided=240)
    overall.comp_ev_sum = 240 * 0.03
    overall.deltas = [0.03] * 240
    return cells, overall


def test_empty_cells_arg_is_a_cli_error() -> None:
    import pytest

    from projects.polymarket.crusaderbot.scripts.report_cutover_holdout import main
    with pytest.raises(SystemExit) as exc:  # argparse parser.error → exit 2
        main(["--demo", "--cells", " , "])
    assert exc.value.code == 2


def test_5m_scope_passes_despite_terminal_15m() -> None:
    # Strong 5m cells + terminal (sub-minimum) 15m cells. Under the default
    # CUTOVER_CELLS scope the 15m cells are ignored → PASS. Under the full 4-cell
    # scope the terminal 15m cells fail §1.5 → RETRY (never PASS). This is the
    # whole reason for the scope param.
    cells = {}
    for ck in ("BTC/5m", "ETH/5m"):
        cs = CellStats(cell=ck, settled=210, holdout_n=63, decided=60)
        cs.comp_ev_sum = 60 * 0.03
        cs.deltas = [0.03] * 60
        cells[ck] = cs
    for ck in ("BTC/15m", "ETH/15m"):  # terminal — far below the 200 minimum
        cells[ck] = CellStats(cell=ck, settled=12, holdout_n=4, decided=4)
    overall = CellStats(cell="overall", settled=420, holdout_n=126, decided=120)
    overall.comp_ev_sum = 120 * 0.03
    overall.deltas = [0.03] * 120

    assert apply_criteria(cells, overall, Criteria())[0] == "PASS"  # default 5m scope
    assert apply_criteria(cells, overall, Criteria(), target_cells=TARGET_CELLS)[0] == "RETRY"


def test_demo_report_renders_all_sections() -> None:
    rows = _demo_rows()
    cells, overall, meta = compute_report(rows)
    verdict, gates = apply_criteria(cells, overall, Criteria())
    md = render_markdown(cells, overall, meta, verdict, gates, Criteria(), data_source="DEMO")
    for header in (
        "## 1. Sample size",
        "## 2. EV delta",
        "## 3. Decision diff matrix",
        "## 4. Factor contribution",
        "## 5. Cell-level safety check",
        "## 6. Final recommendation",
    ):
        assert header in md, header
    # canonical keys present, no rogue smart_strike
    assert "candle_auto" in md and "close_sweep" in md and "flip_hunter" in md
    assert "smart_strike" not in md
    assert verdict in {"PASS", "FAIL", "RETRY"}


def test_verdict_pass_when_strong() -> None:
    cells, overall = _strong_cells()
    verdict, _ = apply_criteria(cells, overall, Criteria())
    assert verdict == "PASS"


def test_verdict_retry_when_marginal() -> None:
    cells, overall = _strong_cells()
    overall.comp_ev_sum = 240 * 0.005  # positive but below the +0.015 margin
    overall.deltas = [0.005] * 240
    verdict, _ = apply_criteria(cells, overall, Criteria())
    assert verdict == "RETRY"


def test_overall_excludes_off_scope_cells() -> None:
    # The default scope is the 5m-first cutover cells. Off-scope cells — SOL/5m
    # AND the terminal 15m cells — must NOT pollute the overall aggregate the
    # cutover decision is gated on.
    rows = _demo_rows(per_cell=120)  # generates BTC/5m, BTC/15m, ETH/5m, ETH/15m
    sol = [dict(r, asset="sol") for r in rows[:120]]  # SOL/5m — off scope
    cells, overall, _ = compute_report(rows + sol)  # default target_cells = CUTOVER_CELLS
    assert CUTOVER_CELLS == ("BTC/5m", "ETH/5m")
    assert "SOL/5m" in cells and "BTC/15m" in cells  # still computed per-cell
    # overall sums ONLY the in-scope 5m cells (15m + SOL excluded)
    assert overall.settled == sum(cells[ck].settled for ck in CUTOVER_CELLS)
    assert overall.settled < sum(cells[ck].settled for ck in TARGET_CELLS)


def test_verdict_fail_on_catastrophic_cell() -> None:
    cells, overall = _strong_cells()
    bad = cells[TARGET_CELLS[0]]
    bad.comp_ev_sum = 60 * -0.06  # below the -0.050 absolute-EV catastrophe floor
    bad.deltas = [-0.06] * 60
    verdict, _ = apply_criteria(cells, overall, Criteria())
    assert verdict == "FAIL"
