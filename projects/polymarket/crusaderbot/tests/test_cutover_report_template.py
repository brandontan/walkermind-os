"""Hermetic coverage for the WARP-78 Track D holdout report renderer.

No DB, no network. Verifies the 6 required sections render, canonical rule
keys are used, and the Track C verdict logic (PASS / FAIL / RETRY) is correct.
"""
from __future__ import annotations

from projects.polymarket.crusaderbot.scripts.report_cutover_holdout import (
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


def test_verdict_fail_on_catastrophic_cell() -> None:
    cells, overall = _strong_cells()
    bad = cells[TARGET_CELLS[0]]
    bad.comp_ev_sum = 60 * -0.06  # below the -0.050 absolute-EV catastrophe floor
    bad.deltas = [-0.06] * 60
    verdict, _ = apply_criteria(cells, overall, Criteria())
    assert verdict == "FAIL"
