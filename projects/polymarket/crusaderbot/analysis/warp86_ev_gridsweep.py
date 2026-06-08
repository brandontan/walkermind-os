#!/usr/bin/env python3
"""WARP-86 Phase 0a — TP/SL EV grid-sweep over settled paper-trade history.

Runs a full TP x SL grid-sweep on the settled trade history to look for an
EV-optimal exit setting, with bootstrap 95% CI bounds and a clear
recommendation for Phase 0b. SCORER_ACTIVE / ORCHESTRATOR_ACTIVE /
ENABLE_LIVE_TRADING are NOT touched — this is pure read-only analysis.

DATA SOURCE (corrected from the directive)
------------------------------------------
The directive named ``positions`` with a ``realized_outcome`` column, but the
live ``positions`` table has NO ``realized_outcome`` column and was wiped to a
handful of rows for the clean-test start. The settled outcome history with the
n>=1445 baseline lives in ``factor_vectors`` (settled = ``realized_outcome IS
NOT NULL``), which carries ``entry_side`` ('YES'/'NO'), ``entry_price``,
``realized_outcome`` ('UP'/'DOWN'), ``asset``, ``timeframe`` and ``data_source``.
Win convention (repo standard, late_entry_oos_evaluator): a YES entry wins on
``realized_outcome='UP'``; a NO entry wins on ``DOWN``.

EV CONVENTIONS
--------------
Two EV models are computed per (TP, SL) combo:

  A. ``mean_ev`` — the directive's literal convention: a directional win
     realises ``+TP``, a loss realises ``-SL``. EV = wr*TP - (1-wr)*SL.

  B. ``mean_ev_capped`` — a more accurate, still-computable convention that uses
     ``entry_price``: a winner held toward settlement can only realise up to
     ``(1-p)/p`` (the option-payoff ceiling for an entry at price p), so the win
     return is ``min(TP, (1-p)/p)``; a loss still realises ``-SL`` (the position
     goes to 0, so any SL<=1 triggers). This exposes the fact that the favourite
     winners in this dataset (p~0.9+) cannot reach a large TP at all.

STRUCTURAL CAVEAT (this is the headline finding)
------------------------------------------------
Neither convention has access to the INTRA-TRADE price PATH (no per-position
MFE/MAE excursion is stored — see PROJECT_STATE KNOWN ISSUES). Both therefore
assume every loss cleanly realises exactly ``-SL`` and never see a *winner that
would have been stopped out by a tight SL first*. Consequence: EV is strictly
monotone-DECREASING in SL under both conventions, so the grid's "EV-optimal"
combo is ALWAYS the minimum-SL corner. That is an artifact of the missing
counterfactual, NOT a real recommendation to drop the stop. A robust interior
TP/SL cannot be identified from settlement outcomes alone; it requires
per-position peak-favourable / peak-adverse excursion capture going forward.

USAGE
-----
    # exact per-row data straight from the DB (preferred):
    python -m crusaderbot.analysis.warp86_ev_gridsweep --from-db

    # reproducible offline run from the committed read-only binned snapshot
    # (binwidth 0.05; the committed CSV/MD were generated this way):
    python warp86_ev_gridsweep.py            # default: --snapshot analysis/data/...

Idempotent: re-running overwrites the dated output files in-place.
"""
from __future__ import annotations

import argparse
import csv
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

# --- Grid (475 combos = 25 TP x 19 SL) ---------------------------------------
# TP: 0.50..2.90 step 0.10 (25 values). SL: 0.10..1.00 step 0.05 (19 values).
# (The directive wrote "0.50 to 3.00 ... (25 values)"; 25 values at step 0.10
# from 0.50 ends at 2.90 — the 25-value count is authoritative over the 3.00
# endpoint so the combo total is exactly 475. Baseline 1.5/0.5 is in-grid.)
TP_VALUES: list[float] = [round(0.50 + 0.10 * i, 2) for i in range(25)]
SL_VALUES: list[float] = [round(0.10 + 0.05 * i, 2) for i in range(19)]
N_BOOTSTRAP: int = 1000
SEED: int = 42

_HERE = Path(__file__).resolve().parent
DEFAULT_SNAPSHOT = _HERE / "data" / "warp86_settled_histogram.csv"
DEFAULT_OUT_DIR = _HERE / "reports"

# settled-row predicate + win expression (shared by the --from-db SQL path).
SETTLED_WHERE = (
    "realized_outcome IS NOT NULL AND entry_side IS NOT NULL "
    "AND entry_price IS NOT NULL"
)
WIN_SQL = (
    "((entry_side='YES' AND realized_outcome='UP') "
    "OR (entry_side='NO' AND realized_outcome='DOWN'))"
)


@dataclass
class Rows:
    """Per-trade settled rows for one scope."""

    entry_price: np.ndarray  # (n,) float in (0,1)
    win: np.ndarray          # (n,) int8 {0,1}

    @property
    def n(self) -> int:
        return int(self.win.shape[0])

    @property
    def win_rate(self) -> float:
        return float(self.win.mean()) if self.n else 0.0

    @property
    def baseline_ev(self) -> float:
        """E.1 convention: mean(is_win - entry_price). The +0.48% baseline."""
        return float((self.win - self.entry_price).mean()) if self.n else 0.0


def load_from_snapshot(path: Path, scope: str) -> Rows:
    """Reconstruct per-row arrays from the committed binned histogram.

    The snapshot is ``scope,win,count,avg_p`` — each row is a 0.05-wide
    entry-price bucket with its member count and the bucket's mean price. We
    expand it to ``count`` pseudo-rows at ``avg_p`` (faithful for aggregate EV
    and for bootstrap resampling; binwidth 0.05 is the only smoothing).
    """
    prices: list[float] = []
    wins: list[int] = []
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row["scope"] != scope:
                continue
            c = int(row["count"])
            prices.extend([float(row["avg_p"])] * c)
            wins.extend([int(row["win"])] * c)
    if not prices:
        raise SystemExit(f"snapshot {path} has no rows for scope={scope!r}")
    return Rows(np.asarray(prices, dtype=float), np.asarray(wins, dtype=np.int8))


def load_from_db(scope: str) -> Rows:
    """Exact per-row settled data from Postgres via DATABASE_URL (asyncpg).

    ``scope`` is 'ALL' (all data_source) or a data_source value (e.g.
    'paper_real'). Read-only SELECT. Requires DATABASE_URL in the environment.
    """
    import asyncio

    import asyncpg  # local import: only needed on the --from-db path

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("--from-db requires DATABASE_URL in the environment")

    where = SETTLED_WHERE
    args: list[object] = []
    if scope != "ALL":
        where += " AND data_source::text = $1"
        args.append(scope)
    sql = (
        f"SELECT entry_price::float8 AS p, "
        f"CASE WHEN {WIN_SQL} THEN 1 ELSE 0 END AS win "
        f"FROM factor_vectors WHERE {where}"
    )

    async def _fetch() -> list[asyncpg.Record]:
        conn = await asyncpg.connect(dsn)
        try:
            return await conn.fetch(sql, *args)
        finally:
            await conn.close()

    recs = asyncio.run(_fetch())
    if not recs:
        raise SystemExit(f"no settled rows for scope={scope!r}")
    prices = np.asarray([float(r["p"]) for r in recs], dtype=float)
    wins = np.asarray([int(r["win"]) for r in recs], dtype=np.int8)
    return Rows(prices, wins)


def _capped_win_return(p: np.ndarray, tp: float) -> np.ndarray:
    """Convention-B win return: min(TP, settlement ceiling (1-p)/p)."""
    # np.divide(where=) evaluates the division only where p > 0 — a p == 0 element
    # keeps the preset +inf and never triggers a divide-by-zero warning.
    ceiling = np.divide(1.0 - p, p, out=np.full_like(p, np.inf), where=p > 0.0)
    return np.minimum(tp, ceiling)


@dataclass
class ComboResult:
    tp: float
    sl: float
    n: int
    mean_ev: float          # convention A
    ci_lower: float
    ci_upper: float
    mean_ev_capped: float   # convention B
    ci_lower_capped: float
    ci_upper_capped: float


def sweep(rows: Rows, rng: np.random.Generator) -> list[ComboResult]:
    """475-combo grid sweep with a shared 1000x bootstrap (comparable CIs)."""
    win = rows.win.astype(float)
    p = rows.entry_price
    n = rows.n
    boot_idx = rng.integers(0, n, size=(N_BOOTSTRAP, n))
    wr_boot = win[boot_idx].mean(axis=1)             # (B,) bootstrap win-rate
    loss_frac_boot = 1.0 - wr_boot

    out: list[ComboResult] = []
    for tp in TP_VALUES:
        # convention A is linear in win -> mean EV = wr*tp - (1-wr)*sl, vectorised.
        # convention B needs the per-row capped win return; precompute per tp.
        cr = np.where(rows.win == 1, _capped_win_return(p, tp), 0.0)
        cr_boot_mean = cr[boot_idx].mean(axis=1)     # (B,) E[win*min(tp,(1-p)/p)]
        for sl in SL_VALUES:
            # A
            mean_a = float(rows.win_rate * tp - (1.0 - rows.win_rate) * sl)
            ev_a_boot = wr_boot * tp - loss_frac_boot * sl
            lo_a, hi_a = np.percentile(ev_a_boot, [2.5, 97.5])
            # B
            mean_b = float(cr.mean() - (1.0 - rows.win_rate) * sl)
            ev_b_boot = cr_boot_mean - loss_frac_boot * sl
            lo_b, hi_b = np.percentile(ev_b_boot, [2.5, 97.5])
            out.append(ComboResult(
                tp=tp, sl=sl, n=n,
                mean_ev=mean_a, ci_lower=float(lo_a), ci_upper=float(hi_a),
                mean_ev_capped=mean_b,
                ci_lower_capped=float(lo_b), ci_upper_capped=float(hi_b),
            ))
    return out


_CSV_COLS = [
    "scope", "tp_pct", "sl_pct", "mean_ev", "ci_lower", "ci_upper", "n",
    "mean_ev_capped", "ci_lower_capped", "ci_upper_capped",
]


def write_csv(path: Path, per_scope: dict[str, list[ComboResult]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(_CSV_COLS)
        for scope, results in per_scope.items():
            for r in results:
                w.writerow([
                    scope, f"{r.tp:.2f}", f"{r.sl:.2f}", f"{r.mean_ev:.6f}",
                    f"{r.ci_lower:.6f}", f"{r.ci_upper:.6f}", r.n,
                    f"{r.mean_ev_capped:.6f}", f"{r.ci_lower_capped:.6f}",
                    f"{r.ci_upper_capped:.6f}",
                ])


def _top10_table(results: list[ComboResult], key, label: str) -> str:
    rows = sorted(results, key=key, reverse=True)[:10]
    lines = [
        f"| # | TP | SL | mean_ev (A) | 95% CI (A) | mean_ev_capped (B) |",
        "|---|----|----|-------------|------------|--------------------|",
    ]
    for i, r in enumerate(rows, 1):
        lines.append(
            f"| {i} | {r.tp:.2f} | {r.sl:.2f} | {r.mean_ev:+.4f} | "
            f"[{r.ci_lower:+.4f}, {r.ci_upper:+.4f}] | {r.mean_ev_capped:+.4f} |"
        )
    return f"**{label}**\n\n" + "\n".join(lines)


def write_md(
    path: Path, per_scope: dict[str, list[ComboResult]],
    rows_by_scope: dict[str, Rows], source_label: str, stamp: str,
) -> None:
    baseline = next(
        (r for r in per_scope["ALL"] if r.tp == 1.5 and r.sl == 0.5), None
    )
    pr_rows = rows_by_scope.get("paper_real")
    md = [
        "# WARP-86 Phase 0a — TP/SL EV Grid-Sweep",
        "",
        f"Generated: {stamp} Asia/Jakarta · Data source: {source_label}",
        "SCORER_ACTIVE / ORCHESTRATOR_ACTIVE / ENABLE_LIVE_TRADING: UNTOUCHED "
        "(read-only analysis).",
        "",
        "## Data",
        "",
        f"- Source table: `factor_vectors` settled rows ({SETTLED_WHERE}). NOT "
        "`positions` (no `realized_outcome` column; wiped for clean-test start).",
        f"- ALL scope n = **{rows_by_scope['ALL'].n}** (>= 1445 baseline target). "
        f"win-rate = **{rows_by_scope['ALL'].win_rate:.4f}**.",
    ]
    if pr_rows is not None:
        md.append(
            f"- paper_real scope n = **{pr_rows.n}**, win-rate = "
            f"**{pr_rows.win_rate:.4f}** (the decision-relevant real-data subset; "
            "paper_synthetic is the WARP-77 negative-EV seed and dilutes ALL)."
        )
    md += [
        "",
        "## Baseline reconciliation (E.1 convention: mean(is_win - entry_price))",
        "",
        f"- ALL: **{rows_by_scope['ALL'].baseline_ev:+.4f}** "
        f"({rows_by_scope['ALL'].baseline_ev * 100:+.2f}%).",
    ]
    if pr_rows is not None:
        md.append(
            f"- paper_real: **{pr_rows.baseline_ev:+.4f}** "
            f"({pr_rows.baseline_ev * 100:+.2f}%) — approximately reproduces the "
            "E.1 #1684 baseline (+0.48%, n=1445 snapshot); the full ALL set is "
            "near-zero because the paper_synthetic seed is slightly -EV."
        )
    md += [
        "",
        "Note: this E.1 metric is entry-price-relative and is a DIFFERENT quantity "
        "from the TP/SL grid EV below (which is a +TP/-SL return). They are not "
        "expected to be equal; the grid's 1.5/0.5 cell (convention A) is "
        f"**{baseline.mean_ev:+.4f}** with 95% CI "
        f"[{baseline.ci_lower:+.4f}, {baseline.ci_upper:+.4f}]."
        if baseline else "",
        "",
        "## Grid sweep (scope = ALL, 475 combos)",
        "",
        _top10_table(per_scope["ALL"], lambda r: r.mean_ev, "Top-10 by mean_ev (A)"),
        "",
        _top10_table(
            per_scope["ALL"], lambda r: r.ci_lower,
            "Top-10 by CI lower bound (A) — most robustly positive",
        ),
        "",
        "## Recommendation (Phase 0b)",
        "",
        "**Do NOT cut over to a grid-'optimal' TP/SL. The sweep cannot identify a "
        "robust interior setting from settlement outcomes alone.**",
        "",
        "1. EV is strictly monotone-decreasing in SL under both conventions, so the "
        "headline 'optimum' is always the minimum-SL / maximum-TP corner "
        f"(TP={TP_VALUES[-1]:.2f}, SL={SL_VALUES[0]:.2f}). This is an ARTIFACT of "
        "the missing intra-trade price path (no per-position MFE/MAE) — the model "
        "never sees a winner that a tight SL would have stopped out first, so it "
        "systematically under-prices the stop. It is not evidence the stop should "
        "be dropped (PROJECT_STATE KNOWN ISSUES: looser-SL bundles are BOUNDED, "
        "not point-estimable).",
        "2. Convention B (entry-price-capped) shows TP is largely inert here: the "
        "winners are heavy favourites (entry price ~0.9+), whose settlement "
        "ceiling (1-p)/p is small, so a large TP is unreachable and adds ~0. Raising "
        "TP past ~0.5 buys almost nothing on this population.",
        "3. The only robustly-signed, model-independent quantity is the win-rate "
        f"(~{rows_by_scope['ALL'].win_rate:.2f}) and the E.1 baseline EV sign "
        "(positive on paper_real, ~0 on the synthetic-diluted ALL).",
        "",
        "**Action:** keep Balanced **TP=1.5 / SL=0.5** (the only setting with an "
        "independent +EV signal on real data); open an instrumentation lane to "
        "capture per-position peak-favourable / peak-adverse excursion going "
        "forward — only that makes a TP/SL sweep able to find a real interior "
        "optimum. Re-run this sweep `--from-db` once excursion data accrues.",
        "",
        "## Method",
        "",
        f"- 25 TP x 19 SL = 475 combos. Bootstrap n={N_BOOTSTRAP} (seed {SEED}), "
        "shared resample indices across combos for comparable CIs; 95% percentile "
        "interval.",
        "- Convention A: win -> +TP, loss -> -SL. Convention B: win -> "
        "min(TP, (1-p)/p), loss -> -SL.",
        "- Win: YES entry wins on realized_outcome=UP; NO entry wins on DOWN.",
        f"- Committed artifacts generated from the read-only binned snapshot "
        "(binwidth 0.05); `--from-db` uses exact per-row data.",
        "",
    ]
    path.write_text("\n".join(md), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="WARP-86 TP/SL EV grid-sweep")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--from-db", action="store_true",
                     help="load exact per-row data from DATABASE_URL")
    src.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT,
                     help="binned histogram snapshot CSV (offline default)")
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = ap.parse_args()

    scopes = ["ALL", "paper_real"]
    rows_by_scope: dict[str, Rows] = {}
    for scope in scopes:
        rows_by_scope[scope] = (
            load_from_db(scope) if args.from_db
            else load_from_snapshot(args.snapshot, scope)
        )

    rng = np.random.default_rng(SEED)
    per_scope = {s: sweep(rows_by_scope[s], rng) for s in scopes}

    args.out_dir.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    stamp = datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M")
    source_label = "DATABASE_URL (exact per-row)" if args.from_db else (
        f"binned snapshot {args.snapshot.name} (binwidth 0.05)")
    csv_path = args.out_dir / f"warp86_ev_gridsweep_{day}.csv"
    md_path = args.out_dir / f"warp86_ev_gridsweep_{day}.md"
    write_csv(csv_path, per_scope)
    write_md(md_path, per_scope, rows_by_scope, source_label, stamp)
    print(f"wrote {csv_path} ({len(per_scope['ALL'])} combos x {len(scopes)} scopes)")
    print(f"wrote {md_path}")


if __name__ == "__main__":
    main()
