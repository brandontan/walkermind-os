"""WARP-78 cutover holdout report renderer (Track D).

Renders the orchestrator-vs-router holdout result into the operator report
that drives the cutover decision, applying the Track C decision criteria
(reports/forge/cutover-decision-criteria.md) to produce the PASS / FAIL /
RETRY recommendation block.

Two modes:
  --demo        render the agreed TEMPLATE from a small in-memory synthetic
                fixture (no DB) — used to lock the visual format before real
                numbers land. This is what produced
                reports/forge/cutover-holdout-template.md.
  --from-db     render the REAL report from settled paper_real rows
                (scorer_trainer.fetch_settled_rows) — used at the real-data
                re-run. Requires CMD approval (mirrors ev_comparator --from-db).

Self-contained: imports only the production EV pipeline + stdlib. Encodes the
Track C thresholds; the --margin option selects C1/C2/C3.

Sections rendered:
  1. Sample-size table (per cell: settled / holdout / decided / exclusions)
  2. EV-delta table (orchestrator vs router, per cell + overall, with 95% CI)
  3. Decision diff matrix (rows where router and orchestrator disagreed)
  4. Factor contribution (which factor weights move the orchestrator's pick)
  5. Cell-level safety check (Track C catastrophic gate)
  6. Final recommendation (PASS / FAIL / RETRY)

Canonical preset/rule keys only: candle_auto / weather_monitor / playbook /
close_sweep / safe_close / flip_hunter.
"""
from __future__ import annotations

import argparse
import math
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from domain.strategy.ev_comparator import (  # noqa: E402
    EVComparator,
    derive_ev_model,
)
from domain.strategy.scorer import (  # noqa: E402
    FACTORS,
    RULE_PRECEDENCE,
    factors_from_row,
    normalize_cell_key,
    row_outcome_for_rule,
    rule_ev,
)

TARGET_CELLS: tuple[str, ...] = ("BTC/5m", "BTC/15m", "ETH/5m", "ETH/15m")
# Confirmed cutover scope (WARP-79): 5m-first — 15m dropped (Polymarket
# discontinued the updown-15m series, so those cells are terminal). §1.5/§1.7
# evaluate ONLY these cells; the §1.7 verdict LOGIC is unchanged — only the cell
# set it ranges over. Override at the CLI with --cells for a different scope.
CUTOVER_CELLS: tuple[str, ...] = ("BTC/5m", "ETH/5m")
_TRAIN_FRACTION: float = 0.7


@dataclass(frozen=True)
class Criteria:
    """Track C thresholds. ``margin`` is the CMD-selected option (C1/C2/C3)."""

    margin: float = 0.015  # C2 (recommended default)
    margin_label: str = "C2 (+0.015)"
    ci_must_exclude_zero: bool = True
    catastrophic_cell_delta: float = -0.020
    catastrophic_cell_abs_ev: float = -0.050
    min_settled: int = 200
    min_holdout: int = 60
    min_decided: int = 40


_MARGIN_OPTIONS: dict[str, tuple[float, str]] = {
    "C1": (0.030, "C1 strict (+0.030)"),
    "C2": (0.015, "C2 moderate (+0.015)"),
    "C3": (0.008, "C3 lenient (+0.008)"),
}


@dataclass
class CellStats:
    cell: str
    settled: int = 0
    holdout_n: int = 0
    decided: int = 0
    abstain: int = 0
    undecidable: int = 0
    router_ev_sum: float = 0.0
    comp_ev_sum: float = 0.0
    agreements: int = 0
    deltas: list[float] = field(default_factory=list)
    disagreements: dict[tuple[str, str], int] = field(default_factory=dict)
    top_factors: dict[str, list[tuple[str, float]]] = field(default_factory=dict)

    @property
    def router_avg(self) -> Optional[float]:
        return self.router_ev_sum / self.decided if self.decided else None

    @property
    def comp_avg(self) -> Optional[float]:
        return self.comp_ev_sum / self.decided if self.decided else None

    @property
    def ev_delta(self) -> Optional[float]:
        return (self.comp_ev_sum - self.router_ev_sum) / self.decided if self.decided else None

    @property
    def ci95(self) -> Optional[tuple[float, float]]:
        n = len(self.deltas)
        if n < 2:
            return None
        mean = sum(self.deltas) / n
        var = sum((d - mean) ** 2 for d in self.deltas) / (n - 1)
        half = 1.96 * math.sqrt(var / n)
        return (mean - half, mean + half)


# ---------------------------------------------------------------------------
# Computation (mirrors evaluate_ev_holdout split + ev_ab_compare per-row logic,
# retaining per-cell paired deltas + disagreement breakdown for the report)
# ---------------------------------------------------------------------------


def _split(rows: Sequence[Mapping[str, Any]], train_fraction: float):
    by_cell: dict[str, list[Mapping[str, Any]]] = {}
    for r in rows:
        ck = normalize_cell_key(r.get("asset"), r.get("timeframe")) or "UNKNOWN"
        by_cell.setdefault(ck, []).append(r)
    train: list[Mapping[str, Any]] = []
    test: dict[str, list[Mapping[str, Any]]] = {}
    settled: dict[str, int] = {}
    for ck, cr in by_cell.items():
        settled[ck] = len(cr)
        if len(cr) < 4:
            train.extend(cr)
            test[ck] = list(cr)
            continue
        cut = max(1, int(len(cr) * train_fraction))
        train.extend(cr[:cut])
        test[ck] = cr[cut:] or cr[:cut]
    return train, test, settled


def compute_report(
    rows: Sequence[Mapping[str, Any]], *, train_fraction: float = _TRAIN_FRACTION,
    target_cells: Sequence[str] = CUTOVER_CELLS,
) -> tuple[dict[str, CellStats], CellStats, dict[str, Any]]:
    train, test, settled = _split(rows, train_fraction)
    model = derive_ev_model(train)
    comparator = EVComparator.from_model(model)

    cells: dict[str, CellStats] = {}
    overall = CellStats(cell="overall")
    for ck, test_rows in test.items():
        cs = CellStats(cell=ck, settled=settled.get(ck, 0), holdout_n=len(test_rows))
        # factor contribution from the trained model (favorite + underdog rules)
        cell_model = (model.get("cells") or {}).get(ck, {})
        for rule in ("close_sweep", "flip_hunter"):
            w = ((cell_model.get("rules") or {}).get(rule, {}) or {}).get("weights", {}) or {}
            cs.top_factors[rule] = sorted(
                ((f, float(w.get(f, 0.0))) for f in FACTORS), key=lambda kv: -abs(kv[1])
            )[:3]
        for row in test_rows:
            router_rule = row.get("router_selected_rule") or row.get("evaluated_rule")
            if router_rule not in RULE_PRECEDENCE:
                cs.undecidable += 1
                continue
            fav = row.get("fav_side")
            r_ev = rule_ev(router_rule, fav, row.get("fav_price"), row_outcome_for_rule(router_rule, row))
            if r_ev is None:
                cs.undecidable += 1
                continue
            comp_rule = comparator.select(ck, list(RULE_PRECEDENCE), factors=factors_from_row(row))
            if comp_rule is None:
                cs.abstain += 1
                continue
            c_ev = rule_ev(comp_rule, fav, row.get("fav_price"), row_outcome_for_rule(comp_rule, row))
            if c_ev is None:
                cs.undecidable += 1
                continue
            cs.decided += 1
            cs.router_ev_sum += r_ev
            cs.comp_ev_sum += c_ev
            cs.deltas.append(c_ev - r_ev)
            if comp_rule == router_rule:
                cs.agreements += 1
            else:
                key = (router_rule, comp_rule)
                cs.disagreements[key] = cs.disagreements.get(key, 0) + 1
        cells[ck] = cs
        # Fold into overall ONLY for the cells in scope — a --from-db fetch returns
        # off-scope cells (the terminal 15m cells, SOL/5m, UNKNOWN); folding those
        # in would pollute the overall EV delta / CI that the Track C criteria gate
        # the cutover on.
        if ck not in target_cells:
            continue
        overall.settled += cs.settled
        overall.holdout_n += cs.holdout_n
        overall.decided += cs.decided
        overall.abstain += cs.abstain
        overall.undecidable += cs.undecidable
        overall.router_ev_sum += cs.router_ev_sum
        overall.comp_ev_sum += cs.comp_ev_sum
        overall.agreements += cs.agreements
        overall.deltas.extend(cs.deltas)
    meta = {"train_rows": len(train), "schema_version": model.get("schema_version")}
    return cells, overall, meta


# ---------------------------------------------------------------------------
# Criteria application (Track C verdict)
# ---------------------------------------------------------------------------


def apply_criteria(
    cells: dict[str, CellStats], overall: CellStats, crit: Criteria,
    *, target_cells: Sequence[str] = CUTOVER_CELLS,
) -> tuple[str, list[tuple[str, bool, str]]]:
    gates: list[tuple[str, bool, str]] = []
    delta = overall.ev_delta
    ci = overall.ci95

    margin_ok = delta is not None and delta >= crit.margin
    gates.append(("margin", margin_ok, f"Δ={_f(delta)} vs ≥{crit.margin:+.3f} ({crit.margin_label})"))

    ci_ok = (not crit.ci_must_exclude_zero) or (ci is not None and ci[0] > 0.0)
    gates.append(("ci_excludes_zero", ci_ok, f"95%CI={_ci(ci)}"))

    sample_ok = True
    sample_detail: list[str] = []
    for ck in target_cells:
        cs = cells.get(ck)
        ok = bool(cs and cs.settled >= crit.min_settled and cs.holdout_n >= crit.min_holdout
                  and cs.decided >= crit.min_decided)
        sample_ok = sample_ok and ok
        if not ok:
            n = (cs.settled if cs else 0, cs.holdout_n if cs else 0, cs.decided if cs else 0)
            sample_detail.append(f"{ck}:{n}")
    gates.append(("sample_minimums", sample_ok,
                  "all scoped cells ≥200/60/40" if sample_ok else "below: " + ", ".join(sample_detail)))

    catastrophic: list[str] = []
    for ck in target_cells:
        cs = cells.get(ck)
        if not cs or cs.decided == 0:
            continue
        if (cs.ev_delta is not None and cs.ev_delta <= crit.catastrophic_cell_delta) or (
            cs.comp_avg is not None and cs.comp_avg <= crit.catastrophic_cell_abs_ev
        ):
            catastrophic.append(f"{ck}(Δ={_f(cs.ev_delta)}, ev={_f(cs.comp_avg)})")
    no_catastrophe = not catastrophic
    gates.append(("no_catastrophic_cell", no_catastrophe,
                  "none" if no_catastrophe else "; ".join(catastrophic)))

    # Verdict per Track C §1.7
    if (delta is not None and delta <= 0.0) or catastrophic:
        verdict = "FAIL"
    elif margin_ok and ci_ok and sample_ok and no_catastrophe:
        verdict = "PASS"
    else:
        verdict = "RETRY"
    return verdict, gates


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _f(x: Optional[float]) -> str:
    return f"{x:+.4f}" if isinstance(x, (int, float)) else "N/A"


def _ci(ci: Optional[tuple[float, float]]) -> str:
    return f"[{ci[0]:+.4f}, {ci[1]:+.4f}]" if ci else "N/A"


def render_markdown(
    cells: dict[str, CellStats], overall: CellStats, meta: dict[str, Any],
    verdict: str, gates: list[tuple[str, bool, str]], crit: Criteria, *, data_source: str,
    target_cells: Sequence[str] = CUTOVER_CELLS,
) -> str:
    L: list[str] = []
    L.append("# WARP-78 Orchestrator Cutover — Holdout Report")
    L.append("")
    L.append(f"- Data source: **{data_source}**")
    L.append(f"- Cutover scope: **{', '.join(target_cells)}** "
             f"(15m dropped — Polymarket discontinued the updown-15m series)")
    L.append(f"- Decision criteria: Track C, margin **{crit.margin_label}**, "
             f"CI-excludes-0={crit.ci_must_exclude_zero}")
    L.append(f"- Preset under test: `candle_auto` + rule `auto` (orchestrator) vs precedence router")
    L.append(f"- Rules compared (canonical): `close_sweep` / `safe_close` / `flip_hunter`")
    L.append(f"- Model schema v{meta.get('schema_version')}, train rows {meta.get('train_rows')}")
    L.append("")
    L.append("> System in paper trading mode. No real capital deployed. When the data "
             "source is synthetic/DEMO the numbers below are illustrative — they exist "
             "to lock the report format, not to drive a real cutover.")
    L.append("")

    L.append("## 1. Sample size")
    L.append("")
    L.append("| Cell | Settled | Holdout | Decided | Abstain | Undecidable |")
    L.append("|---|--:|--:|--:|--:|--:|")
    for ck in target_cells:
        cs = cells.get(ck) or CellStats(cell=ck)
        L.append(f"| `{ck}` | {cs.settled} | {cs.holdout_n} | {cs.decided} | {cs.abstain} | {cs.undecidable} |")
    L.append(f"| **overall** | {overall.settled} | {overall.holdout_n} | {overall.decided} "
             f"| {overall.abstain} | {overall.undecidable} |")
    L.append("")

    L.append("## 2. EV delta (orchestrator − router)")
    L.append("")
    L.append("| Cell | Router EV/trade | Orchestrator EV/trade | Δ | 95% CI | Agreement |")
    L.append("|---|--:|--:|--:|:--:|--:|")
    for ck in target_cells:
        cs = cells.get(ck) or CellStats(cell=ck)
        agree = f"{cs.agreements / cs.decided:.0%}" if cs.decided else "N/A"
        L.append(f"| `{ck}` | {_f(cs.router_avg)} | {_f(cs.comp_avg)} | {_f(cs.ev_delta)} "
                 f"| {_ci(cs.ci95)} | {agree} |")
    o_agree = f"{overall.agreements / overall.decided:.0%}" if overall.decided else "N/A"
    L.append(f"| **overall** | {_f(overall.router_avg)} | {_f(overall.comp_avg)} | "
             f"{_f(overall.ev_delta)} | {_ci(overall.ci95)} | {o_agree} |")
    L.append("")

    L.append("## 3. Decision diff matrix (router → orchestrator, where they disagreed)")
    L.append("")
    any_disagree = False
    for ck in target_cells:
        cs = cells.get(ck)
        if not cs or not cs.disagreements:
            continue
        any_disagree = True
        parts = ", ".join(f"`{r}`→`{c}`: {n}" for (r, c), n in sorted(cs.disagreements.items()))
        L.append(f"- `{ck}`: {parts}")
    if not any_disagree:
        L.append("- (no disagreements in this sample)")
    L.append("")

    L.append("## 4. Factor contribution (top |weight| moving the orchestrator's pick)")
    L.append("")
    L.append("| Cell | `close_sweep` drivers | `flip_hunter` drivers |")
    L.append("|---|---|---|")
    for ck in target_cells:
        cs = cells.get(ck)
        cs_drv = _fmt_factors(cs.top_factors.get("close_sweep") if cs else None)
        fh_drv = _fmt_factors(cs.top_factors.get("flip_hunter") if cs else None)
        L.append(f"| `{ck}` | {cs_drv} | {fh_drv} |")
    L.append("")

    L.append("## 5. Cell-level safety check (Track C catastrophic gate)")
    L.append("")
    L.append(f"Catastrophic if cell Δ ≤ {crit.catastrophic_cell_delta:+.3f} OR cell "
             f"orchestrator EV ≤ {crit.catastrophic_cell_abs_ev:+.3f}.")
    L.append("")
    L.append("| Cell | Δ | Orchestrator EV/trade | Status |")
    L.append("|---|--:|--:|:--:|")
    for ck in target_cells:
        cs = cells.get(ck)
        if not cs or cs.decided == 0:
            L.append(f"| `{ck}` | N/A | N/A | ⚠️ INCONCLUSIVE |")
            continue
        bad = (cs.ev_delta is not None and cs.ev_delta <= crit.catastrophic_cell_delta) or (
            cs.comp_avg is not None and cs.comp_avg <= crit.catastrophic_cell_abs_ev)
        L.append(f"| `{ck}` | {_f(cs.ev_delta)} | {_f(cs.comp_avg)} | "
                 f"{'❌ CATASTROPHIC' if bad else '✅ OK'} |")
    L.append("")

    L.append("## 6. Final recommendation")
    L.append("")
    badge = {"PASS": "✅ PASS", "FAIL": "❌ FAIL", "RETRY": "🔁 RETRY"}[verdict]
    L.append(f"### {badge}")
    L.append("")
    L.append("| Gate | Result | Detail |")
    L.append("|---|:--:|---|")
    for name, ok, detail in gates:
        L.append(f"| {name} | {'✅' if ok else '❌'} | {detail} |")
    L.append("")
    L.append({
        "PASS": "→ Triggers the Track B code-cutover PR (activate orchestrator for "
                "`candle_auto`+`auto`). Operator follows `docs/runbooks/orchestrator-cutover.md`.",
        "FAIL": "→ Orchestrator stays inactive; precedence router retained. Phase 3 iterates "
                "(label / factor work) before re-proposing.",
        "RETRY": "→ Orchestrator stays inactive; accrue more `paper_real` rows and re-run. A "
                 "marginal-but-insignificant result never cuts over.",
    }[verdict])
    L.append("")
    return "\n".join(L)


def _fmt_factors(top: Optional[list[tuple[str, float]]]) -> str:
    if not top:
        return "N/A"
    return ", ".join(f"`{f}`={w:+.3f}" for f, w in top if w != 0.0) or "(none ≠ 0)"


# ---------------------------------------------------------------------------
# Demo fixture (small, in-memory; only to lock the template format)
# ---------------------------------------------------------------------------


def _demo_rows(seed: int = 78, per_cell: int = 220) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    out: list[dict[str, Any]] = []
    # Generate the full 4-cell grid so the demo also exercises off-scope exclusion
    # (the 15m cells are present in the data but dropped from the verdict scope).
    for ck in TARGET_CELLS:
        asset, tf = ck.split("/")
        asset = asset.lower()
        ttl_cap = 300.0 if tf == "5m" else 900.0
        for _ in range(per_cell):
            mom = rng.gauss(0.0, 0.6)
            fav_side = "YES" if rng.random() < 0.5 else "NO"
            fav_price = min(0.85, max(0.52, 0.5 + abs(rng.gauss(0.0, 0.12))))
            ttl = rng.uniform(8.0, ttl_cap)
            p_win = min(0.95, max(0.05, fav_price + 0.13 * (mom / 0.6)))
            fav_wins = rng.random() < p_win
            winner = fav_side if fav_wins else ("NO" if fav_side == "YES" else "YES")
            outcome = "UP" if winner == "YES" else "DOWN"
            router = "close_sweep" if ttl < 40 else ("safe_close" if ttl < 70 else "flip_hunter")
            out.append({
                "asset": asset, "timeframe": tf, "fav_side": fav_side,
                "fav_price": round(fav_price, 6), "ttl_sec": round(ttl, 3),
                "momentum": round(mom, 8), "volatility_sigma": 0.0009,
                "liquidity_usdc": round(math.exp(rng.gauss(math.log(3000), 0.5)), 2),
                "spread": round(abs(rng.gauss(0.012, 0.004)) + 1e-4, 6),
                "orderbook_depth_usdc": round(math.exp(rng.gauss(math.log(1500), 0.5)), 2),
                "oracle_edge": round(rng.gauss(0.0, 0.02), 8),
                "realized_outcome": outcome, "realized_outcome_safe_close": outcome,
                "router_selected_rule": router, "evaluated_rule": router,
                "outcome_source": "open_to_close", "settled": True,
                "data_source": "paper_synthetic",
            })
    return out


# The cutover report reads real rows only by default; the factor_vectors table
# still holds the paper_synthetic seed (WARP-77 #1655 data_source enum).
CUTOVER_DATA_SOURCE: str = "paper_real"
_DATA_SOURCE_CHOICES: tuple[str, ...] = ("paper_real", "paper_synthetic", "live_real", "all")


async def _fetch_real_rows(data_source: str | None = CUTOVER_DATA_SOURCE) -> list[dict[str, Any]]:
    from domain.strategy.scorer_trainer import fetch_settled_rows
    return await fetch_settled_rows(data_source=data_source)


def main(argv: Optional[Sequence[str]] = None) -> int:
    import asyncio
    import logging

    import structlog
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))

    p = argparse.ArgumentParser(prog="report_cutover_holdout", description=__doc__)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--demo", action="store_true", help="Render the template from a synthetic fixture.")
    src.add_argument("--from-db", action="store_true", help="Render from settled rows (CMD-gated).")
    p.add_argument("--margin", choices=list(_MARGIN_OPTIONS), default="C2", help="Track C margin option.")
    p.add_argument(
        "--data-source", choices=_DATA_SOURCE_CHOICES, default=CUTOVER_DATA_SOURCE,
        help="Provenance filter for --from-db (default paper_real; 'all' reads every provenance).",
    )
    p.add_argument(
        "--cells", default=",".join(CUTOVER_CELLS),
        help="Comma-separated cells the §1.7 verdict ranges over (default the confirmed "
             "5m-first scope BTC/5m,ETH/5m; 15m is terminal and excluded).",
    )
    p.add_argument("--out", default=None, help="Write markdown to this path (default: stdout).")
    args = p.parse_args(argv)

    margin, label = _MARGIN_OPTIONS[args.margin]
    crit = Criteria(margin=margin, margin_label=label)
    target_cells = tuple(c.strip() for c in args.cells.split(",") if c.strip())
    if not target_cells:
        p.error("At least one cell must be specified via --cells (empty scope would "
                "render empty tables and a misleading RETRY).")

    if args.demo:
        rows = _demo_rows()
        data_source = "paper_synthetic (DEMO — template only, not a real cutover signal)"
    else:
        ds = None if args.data_source == "all" else args.data_source
        rows = asyncio.run(_fetch_real_rows(ds))
        data_source = f"{ds or 'all'} (settled, open_to_close)"
        if not rows:
            print("No settled rows returned from DB — cannot render.", file=sys.stderr)
            return 2

    cells, overall, meta = compute_report(rows, target_cells=target_cells)
    verdict, gates = apply_criteria(cells, overall, crit, target_cells=target_cells)
    md = render_markdown(cells, overall, meta, verdict, gates, crit,
                         data_source=data_source, target_cells=target_cells)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md + "\n", encoding="utf-8")
        print(f"wrote {args.out}  (verdict={verdict})")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
