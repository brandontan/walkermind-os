"""late_entry_v3 out-of-sample (OOS) drift evaluator (WARP-81 Phase 2).

`late_entry_v3` produces ~95% of CrusaderBot's entries (1168 historical
positions) but has never been OOS-validated: if its out-of-sample realized edge
differs from in-sample, the strategy making most of the book has a hidden quality
issue. This module quantifies that drift with a chronological train/test split
per cell over the **settled** `factor_vectors` rows.

Method (per (asset, timeframe) cell):
  * Order the cell's settled rows chronologically (candle close time).
  * Split 70/30 → in-sample (older 70%) / OOS (newer 30%).
  * Compute mean realized per-trade EV on each split.
  * drift = OOS_ev − in_sample_ev, with a two-sample 95% CI on the difference.
  * Verdict: holds OOS / degrades / improves / inconclusive (thin sample or CI
    straddles 0).

Realized per-trade EV uses the SAME convention as the production scorer
(`domain/strategy/scorer.py`): a 1-unit binary position pays `1 − entry_price` on
a win and `−entry_price` on a loss, where the win is the entry side matching the
realized candle direction (UP→YES, DOWN→NO; FLAT/unresolved → undecidable, the
row is skipped — never a fabricated loss). It is **reimplemented independently
here on purpose**: an OOS proof must not depend on the very code it validates, and
WARP-79 locks `ev_comparator` / `scorer_trainer` / the scorer out of this lane.
This module is validation-only — it never runs in the scan loop, changes no
selection/threshold/risk logic, and reads `entry_side`/`entry_price` exactly as
`late_entry_v3` recorded them.

The DB path requires an explicit `--from-db` flag and defaults to the
`paper_real` provenance (WARP-77 #1655 enum) so the proof is run on real-market
rows, never the paper_synthetic seed. Tests exercise the pure evaluator with
in-memory synthetic rows — no DB.
"""
from __future__ import annotations

import argparse
import asyncio
import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

import structlog

logger = structlog.get_logger(__name__)

# Provenance default for the proof — real-market rows only (WARP-77 #1655 enum).
OOS_DATA_SOURCE: str = "paper_real"

# Test-split fraction (newest rows). 0.30 → 70/30 chronological train/test.
DEFAULT_TEST_FRACTION: float = 0.30

# Minimum rows per split for a cell verdict to be anything but inconclusive. A
# thin OOS slice cannot prove or disprove drift.
MIN_PER_SPLIT: int = 30

# Drift magnitude (EV/trade) below which a statistically-clean result is "holds"
# rather than a directional call. Mirrors the WARP-78 cutover catastrophic-cell
# scale (cell Δ ≤ −0.020 is materially bad).
MATERIAL_DRIFT: float = 0.020

# Rules whose realized label uses the safe-close horizon (open→close−30s), mirror
# of scorer._SAFE_CLOSE_HORIZON_RULES. Kept local so this validator does not
# import the locked scorer module.
_SAFE_CLOSE_RULES: frozenset[str] = frozenset({"safe_close"})

OUTCOME_UP: str = "UP"
OUTCOME_DOWN: str = "DOWN"


# ---------------------------------------------------------------------------
# Pure realized-EV convention (independent reimplementation of scorer.py)
# ---------------------------------------------------------------------------


def winning_side(realized_outcome: Optional[str]) -> Optional[str]:
    """UP→YES, DOWN→NO; FLAT/unknown → None (undecidable push, skip the row)."""
    if realized_outcome == OUTCOME_UP:
        return "YES"
    if realized_outcome == OUTCOME_DOWN:
        return "NO"
    return None


def row_rule(row: Mapping[str, Any]) -> Optional[str]:
    """The rule late_entry_v3 actually entered with for this row.

    Prefer the router-selected rule when the router picked it, else the evaluated
    rule. Used only to choose the realized-outcome horizon.
    """
    if row.get("selected_by_router") and row.get("router_selected_rule"):
        return str(row["router_selected_rule"])
    ev_rule = row.get("evaluated_rule")
    return str(ev_rule) if ev_rule else None


def row_outcome(row: Mapping[str, Any]) -> Optional[str]:
    """Per-rule horizon label: safe_close rows use realized_outcome_safe_close."""
    rule = row_rule(row)
    if rule in _SAFE_CLOSE_RULES:
        sc = row.get("realized_outcome_safe_close")
        if sc is not None:
            return str(sc)
    out = row.get("realized_outcome")
    return str(out) if out is not None else None


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def realized_ev(row: Mapping[str, Any]) -> Optional[float]:
    """Realized per-trade EV of the recorded entry, or None if undecidable.

    ev = (1 if entry_side won else 0) − entry_price, using the row's own
    recorded `entry_side`/`entry_price` and the horizon-correct realized outcome.
    None when the entry side, the entry price, or the realized winner is missing.
    """
    entry_side = row.get("entry_side")
    if entry_side not in ("YES", "NO"):
        return None
    price = _as_float(row.get("entry_price"))
    if price is None or not (0.0 <= price <= 1.0):
        return None
    winner = winning_side(row_outcome(row))
    if winner is None:
        return None
    return (1.0 if entry_side == winner else 0.0) - price


def normalize_cell_key(asset: Optional[str], timeframe: Optional[str]) -> Optional[str]:
    """Canonical ``ASSET/timeframe`` cell key (asset upper-cased); None if missing."""
    if not asset or not timeframe:
        return None
    a = str(asset).strip().upper()
    tf = str(timeframe).strip()
    if not a or not tf:
        return None
    return f"{a}/{tf}"


# ---------------------------------------------------------------------------
# Pure stats (stdlib only — numpy/scipy are not dependencies)
# ---------------------------------------------------------------------------


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _sample_var(xs: Sequence[float]) -> float:
    """Unbiased (n−1) sample variance; 0.0 for n < 2."""
    n = len(xs)
    if n < 2:
        return 0.0
    m = _mean(xs)
    return sum((x - m) ** 2 for x in xs) / (n - 1)


def two_sample_diff_ci(
    a: Sequence[float], b: Sequence[float], *, z: float = 1.96
) -> tuple[float, float, float, float]:
    """(mean_b − mean_a) with a Welch standard error and a z-based CI.

    Returns ``(diff, se, lo, hi)``. ``diff = mean(b) − mean(a)`` (b = OOS,
    a = in-sample). A normal (z) approximation is used for the interval — sample
    sizes here are ≥ MIN_PER_SPLIT so the t/z gap is small and scipy is avoided.
    """
    na, nb = len(a), len(b)
    diff = _mean(b) - _mean(a)
    if na < 2 or nb < 2:
        return diff, 0.0, diff, diff
    se = math.sqrt(_sample_var(a) / na + _sample_var(b) / nb)
    return diff, se, diff - z * se, diff + z * se


# ---------------------------------------------------------------------------
# Per-cell OOS result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CellOOSResult:
    """In-sample vs OOS realized-EV comparison for one (asset, timeframe) cell."""

    cell: str
    n_total: int
    n_in: int
    n_oos: int
    in_sample_ev: float
    oos_ev: float
    drift: float                 # oos_ev − in_sample_ev
    drift_se: float
    drift_ci_low: float
    drift_ci_high: float
    significant: bool            # CI excludes 0
    in_hit_rate: float
    oos_hit_rate: float
    verdict: str                 # holds | degrades | improves | inconclusive_thin


@dataclass(frozen=True)
class OOSReport:
    """Full OOS proof: per-cell results + an overall (pooled) row."""

    cells: list[CellOOSResult] = field(default_factory=list)
    overall: Optional[CellOOSResult] = None
    data_source: str = OOS_DATA_SOURCE
    test_fraction: float = DEFAULT_TEST_FRACTION


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------


def _chronological_key(row: Mapping[str, Any]) -> float:
    """Sort key for the train/test split: candle close epoch, then settled_at.

    Falls back to +inf so rows with no timestamp sort last (and are therefore
    placed in the OOS slice, never silently dropped from ordering).
    """
    epoch = _as_float(row.get("candle_close_epoch"))
    if epoch is not None:
        return epoch
    settled = row.get("settled_at")
    if settled is not None:
        ts = getattr(settled, "timestamp", None)
        if callable(ts):
            try:
                return float(ts())
            except Exception:  # noqa: BLE001
                return math.inf
    return math.inf


def _split_evs(
    evs_chrono: Sequence[float], *, test_fraction: float
) -> tuple[list[float], list[float]]:
    """Chronological train/test split of an ordered EV sequence → (in_sample, oos)."""
    n = len(evs_chrono)
    if n == 0:
        return [], []
    n_oos = max(1, int(round(n * test_fraction))) if n >= 2 else 0
    n_oos = min(n_oos, n - 1) if n >= 2 else 0
    split = n - n_oos
    return list(evs_chrono[:split]), list(evs_chrono[split:])


def _verdict(n_in: int, n_oos: int, drift: float, significant: bool) -> str:
    if n_in < MIN_PER_SPLIT or n_oos < MIN_PER_SPLIT:
        return "inconclusive_thin"
    if not significant or abs(drift) < MATERIAL_DRIFT:
        return "holds"
    return "degrades" if drift < 0 else "improves"


def _result_for(cell: str, rows_chrono: Sequence[Mapping[str, Any]], *, test_fraction: float) -> Optional[CellOOSResult]:
    """Build a CellOOSResult from a cell's chronologically-ordered decidable rows."""
    pairs = [(realized_ev(r), r) for r in rows_chrono]
    decidable = [(ev, r) for ev, r in pairs if ev is not None]
    if not decidable:
        return None
    evs = [ev for ev, _ in decidable]
    in_evs, oos_evs = _split_evs(evs, test_fraction=test_fraction)
    if not in_evs or not oos_evs:
        return None
    diff, se, lo, hi = two_sample_diff_ci(in_evs, oos_evs)
    significant = (lo > 0.0) or (hi < 0.0)
    # The decidable list is already chronologically ordered (caller sorts), so the
    # same split index partitions rows for the hit-rate as for the EV means.
    in_hit = _hit_rate(decidable[:len(in_evs)])
    oos_hit = _hit_rate(decidable[len(in_evs):])
    return CellOOSResult(
        cell=cell,
        n_total=len(decidable),
        n_in=len(in_evs),
        n_oos=len(oos_evs),
        in_sample_ev=_mean(in_evs),
        oos_ev=_mean(oos_evs),
        drift=diff,
        drift_se=se,
        drift_ci_low=lo,
        drift_ci_high=hi,
        significant=significant,
        in_hit_rate=in_hit,
        oos_hit_rate=oos_hit,
        verdict=_verdict(len(in_evs), len(oos_evs), diff, significant),
    )


def _hit_rate(decidable: Sequence[tuple[float, Mapping[str, Any]]]) -> float:
    """Fraction of trades whose recorded entry side matched the realized winner."""
    if not decidable:
        return 0.0
    wins = 0
    for _, r in decidable:
        if r.get("entry_side") == winning_side(row_outcome(r)):
            wins += 1
    return wins / len(decidable)


def evaluate_oos(
    rows: Sequence[Mapping[str, Any]],
    *,
    test_fraction: float = DEFAULT_TEST_FRACTION,
    data_source: str = OOS_DATA_SOURCE,
) -> OOSReport:
    """Run the per-cell chronological OOS drift evaluation over settled rows.

    ``rows`` are settled factor_vectors rows (any order — they are sorted here).
    Returns an :class:`OOSReport` with one :class:`CellOOSResult` per cell plus a
    pooled overall row.
    """
    by_cell: dict[str, list[Mapping[str, Any]]] = {}
    for r in rows:
        cell = normalize_cell_key(r.get("asset"), r.get("timeframe"))
        if cell is None:
            continue
        by_cell.setdefault(cell, []).append(r)

    cells: list[CellOOSResult] = []
    for cell in sorted(by_cell):
        ordered = sorted(by_cell[cell], key=_chronological_key)
        res = _result_for(cell, ordered, test_fraction=test_fraction)
        if res is not None:
            cells.append(res)

    # Overall = pooled across all cells (each cell ordered chronologically, then
    # concatenated cell-major). Reuse _result_for over the union so the split is
    # well-defined; cell label "OVERALL".
    all_ordered = sorted(
        (r for cell_rows in by_cell.values() for r in cell_rows),
        key=_chronological_key,
    )
    overall = _result_for("OVERALL", all_ordered, test_fraction=test_fraction)
    return OOSReport(cells=cells, overall=overall, data_source=data_source, test_fraction=test_fraction)


# ---------------------------------------------------------------------------
# DB loader (gated; paper_real by default) + report rendering
# ---------------------------------------------------------------------------


async def load_settled_rows(
    *,
    data_source: str = OOS_DATA_SOURCE,
    pool: Any | None = None,
) -> list[dict[str, Any]]:
    """Fetch settled factor_vectors rows for the proof. Fail-soft → [] on error.

    ``data_source='all'`` reads every provenance (no filter); otherwise filters
    by the provenance enum so the proof never mixes the paper_synthetic seed in.
    """
    from ...database import get_pool

    where = "settled = TRUE"
    args: list[Any] = []
    if data_source and data_source != "all":
        where += " AND data_source = $1"
        args.append(data_source)
    sql = (
        "SELECT asset, timeframe, entry_side, entry_price, fav_side, fav_price, "
        "realized_outcome, realized_outcome_safe_close, evaluated_rule, "
        "router_selected_rule, selected_by_router, candle_close_epoch, "
        "settled_at, outcome_source, data_source "
        f"FROM factor_vectors WHERE {where} "
        "ORDER BY candle_close_epoch ASC NULLS LAST, settled_at ASC"
    )
    try:
        pool = pool or get_pool()
        async with pool.acquire() as conn:  # type: ignore[attr-defined]
            records = await conn.fetch(sql, *args)
    except Exception as exc:  # noqa: BLE001 — research tool, fail-soft to empty
        logger.warning("late_entry_oos_load_failed", error=str(exc))
        return []
    return [dict(r) for r in records]


def _fmt(x: float) -> str:
    return f"{x:+.4f}"


def render_report(report: OOSReport) -> str:
    """Render the OOS proof as the Phase-4 markdown report body."""
    lines: list[str] = []
    lines.append("| cell | n (in/oos) | in-sample EV/trade | OOS EV/trade | drift | 95% CI | hit (in→oos) | verdict |")
    lines.append("|---|---|---:|---:|---:|---|---:|---|")
    rows = list(report.cells)
    if report.overall is not None:
        rows.append(report.overall)
    for r in rows:
        ci = f"[{_fmt(r.drift_ci_low)}, {_fmt(r.drift_ci_high)}]"
        sig = "*" if r.significant else ""
        lines.append(
            f"| {r.cell} | {r.n_in}/{r.n_oos} | {_fmt(r.in_sample_ev)} | "
            f"{_fmt(r.oos_ev)} | {_fmt(r.drift)}{sig} | {ci} | "
            f"{r.in_hit_rate:.2%}→{r.oos_hit_rate:.2%} | {r.verdict} |"
        )
    lines.append("")
    lines.append("`*` = drift 95% CI excludes 0 (statistically significant). "
                 f"data_source={report.data_source}, test_fraction={report.test_fraction:.0%}.")
    return "\n".join(lines)


async def _amain(args: argparse.Namespace) -> int:
    if not args.from_db:
        print(
            "late_entry_v3 OOS evaluator (WARP-81). No DB read without --from-db.\n"
            "Run: python -m projects.polymarket.crusaderbot.domain.research."
            "late_entry_oos_evaluator --from-db [--data-source paper_real] [--test-fraction 0.30]"
        )
        return 0
    rows = await load_settled_rows(data_source=args.data_source)
    report = evaluate_oos(rows, test_fraction=args.test_fraction, data_source=args.data_source)
    print(render_report(report))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="late_entry_v3 OOS drift proof (WARP-81)")
    parser.add_argument("--from-db", action="store_true",
                        help="read settled factor_vectors from the DB (gated; CMD-approved)")
    parser.add_argument("--data-source", default=OOS_DATA_SOURCE,
                        choices=["paper_real", "paper_synthetic", "live_real", "all"],
                        help="provenance filter (default paper_real)")
    parser.add_argument("--test-fraction", type=float, default=DEFAULT_TEST_FRACTION,
                        help="OOS (newest) fraction of the chronological split")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_amain(args)))


if __name__ == "__main__":
    main()


__all__ = [
    "CellOOSResult",
    "OOSReport",
    "evaluate_oos",
    "realized_ev",
    "winning_side",
    "row_outcome",
    "row_rule",
    "normalize_cell_key",
    "two_sample_diff_ci",
    "load_settled_rows",
    "render_report",
    "OOS_DATA_SOURCE",
    "DEFAULT_TEST_FRACTION",
    "MIN_PER_SPLIT",
]
