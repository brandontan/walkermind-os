"""WARP-70 shadow runner — adaptive vs static sigma calibration (NO capital path).

Replays the settled candle-observation stream (``factor_vectors``, every candle —
traded or not, NEVER the positions table) chronologically through the online
:class:`SigmaCalibrator` and reports, per ``(asset, timeframe)`` cell:

  * the converged adaptive sigma vs the static per-asset prior,
  * the average Gaussian NLL of the realized returns under each (predict-THEN-
    update, so the adaptive number is an honest out-of-sample comparison),
  * the NLL improvement (static - adaptive; positive = adaptive calibrates the
    realized return spread better).

This is the WARP-70 shadow acceptance test. It changes NO runtime behaviour, gates
nothing, and writes nothing — it only reads and prints. Swapping the live oracle
sigma from static to adaptive is a deliberate FUTURE lane, gated separately.

Usage::

    python -m crusaderbot.scripts.sigma_calibration_shadow [--data-source paper_real]
                                                            [--alpha 0.05] [--min-samples 30]
"""
from __future__ import annotations

import argparse
import asyncio
from typing import Any, Iterable

from ..domain.research.sigma_calibrator import (
    SigmaCalibrator,
    gaussian_nll,
    prior_sigma_for_asset,
)


def _duration_sec(row: dict[str, Any]) -> float | None:
    o = row.get("candle_open_epoch")
    c = row.get("candle_close_epoch")
    if o is None or c is None:
        return None
    try:
        d = float(c) - float(o)
    except (TypeError, ValueError):
        return None
    return d if d > 0.0 else None


def evaluate_adaptive_vs_static(
    rows: Iterable[dict[str, Any]],
    *,
    alpha: float = 0.05,
    min_samples: int = 30,
) -> dict[str, Any]:
    """Pure evaluation core — feed settled candle rows (chronological), get the
    per-cell + overall adaptive-vs-static calibration report.

    Each row needs: ``asset``, ``timeframe``, ``realized_delta``,
    ``candle_open_epoch``, ``candle_close_epoch``. predict-THEN-update: the
    adaptive NLL for a candle uses the sigma the calibrator held BEFORE folding
    that candle in (no look-ahead), so it is a fair out-of-sample score.
    """
    cal = SigmaCalibrator(alpha=alpha, min_samples=min_samples)
    cells: dict[tuple[str, str], dict[str, float]] = {}

    for row in rows:
        asset = str(row.get("asset") or "").strip().lower()
        tf = str(row.get("timeframe") or "").strip().lower()
        if not asset or not tf:
            continue
        rd = row.get("realized_delta")
        dur = _duration_sec(row)
        if rd is None or dur is None:
            continue
        try:
            realized_delta = float(rd)
        except (TypeError, ValueError):
            continue

        sigma_static = prior_sigma_for_asset(asset)
        sigma_adaptive = cal.sigma(asset, tf)  # BEFORE update — out-of-sample

        nll_static = gaussian_nll(realized_delta, dur, sigma_static)
        nll_adaptive = gaussian_nll(realized_delta, dur, sigma_adaptive)

        cal.observe(asset, tf, realized_delta, dur)  # update AFTER scoring

        if nll_static is None or nll_adaptive is None:
            continue
        key = (asset, tf)
        agg = cells.setdefault(
            key, {"n": 0.0, "sum_static": 0.0, "sum_adaptive": 0.0}
        )
        agg["n"] += 1.0
        agg["sum_static"] += nll_static
        agg["sum_adaptive"] += nll_adaptive

    per_cell: list[dict[str, Any]] = []
    tot_n = tot_static = tot_adaptive = 0.0
    for (asset, tf), agg in sorted(cells.items()):
        n = agg["n"]
        if n <= 0:
            continue
        avg_static = agg["sum_static"] / n
        avg_adaptive = agg["sum_adaptive"] / n
        per_cell.append({
            "asset": asset,
            "timeframe": tf,
            "n": int(n),
            "prior_sigma": prior_sigma_for_asset(asset),
            "adaptive_sigma": cal.sigma(asset, tf),
            "avg_nll_static": avg_static,
            "avg_nll_adaptive": avg_adaptive,
            "nll_improvement": avg_static - avg_adaptive,
            "converged": cal.sigma(asset, tf) != prior_sigma_for_asset(asset),
        })
        tot_n += n
        tot_static += agg["sum_static"]
        tot_adaptive += agg["sum_adaptive"]

    overall = {
        "n": int(tot_n),
        "avg_nll_static": (tot_static / tot_n) if tot_n else None,
        "avg_nll_adaptive": (tot_adaptive / tot_n) if tot_n else None,
        "nll_improvement": ((tot_static - tot_adaptive) / tot_n) if tot_n else None,
    }
    return {"per_cell": per_cell, "overall": overall}


def render_report(report: dict[str, Any]) -> str:
    lines = ["WARP-70 — adaptive vs static sigma calibration (SHADOW)", ""]
    lines.append(
        f"{'cell':<10}{'n':>6}{'prior_σ':>12}{'adaptive_σ':>13}"
        f"{'nll_static':>13}{'nll_adapt':>12}{'Δnll':>10}{'conv':>6}"
    )
    for c in report["per_cell"]:
        lines.append(
            f"{c['asset'] + '/' + c['timeframe']:<10}{c['n']:>6}"
            f"{c['prior_sigma']:>12.6f}{c['adaptive_sigma']:>13.6f}"
            f"{c['avg_nll_static']:>13.4f}{c['avg_nll_adaptive']:>12.4f}"
            f"{c['nll_improvement']:>10.4f}{('yes' if c['converged'] else 'no'):>6}"
        )
    o = report["overall"]
    if o["avg_nll_static"] is not None:
        lines += [
            "",
            f"OVERALL n={o['n']} | nll_static={o['avg_nll_static']:.4f} "
            f"nll_adaptive={o['avg_nll_adaptive']:.4f} "
            f"Δnll={o['nll_improvement']:+.4f} "
            f"({'adaptive better' if o['nll_improvement'] > 0 else 'static better/equal'})",
        ]
    else:
        lines += ["", "OVERALL: no eligible settled candles in the selected window."]
    return "\n".join(lines)


_FETCH_SQL = """
    SELECT asset, timeframe, realized_delta, candle_open_epoch, candle_close_epoch
      FROM factor_vectors
     WHERE settled = TRUE
       AND realized_delta IS NOT NULL
       AND candle_open_epoch IS NOT NULL
       AND candle_close_epoch IS NOT NULL
       AND ($1::text IS NULL OR data_source = $1::text)
     ORDER BY candle_close_epoch ASC
"""


async def _fetch_rows(data_source: str | None) -> list[dict[str, Any]]:
    from ..database import close_pool, get_pool, init_pool

    await init_pool()
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            recs = await conn.fetch(_FETCH_SQL, data_source)
        return [dict(r) for r in recs]
    finally:
        await close_pool()


async def _amain(args: argparse.Namespace) -> int:
    ds = None if args.data_source == "all" else args.data_source
    rows = await _fetch_rows(ds)
    report = evaluate_adaptive_vs_static(
        rows, alpha=args.alpha, min_samples=args.min_samples
    )
    print(render_report(report))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="WARP-70 shadow sigma calibration (read-only).")
    p.add_argument("--data-source", default="paper_real",
                   help="factor_vectors provenance filter ('all' = unfiltered).")
    p.add_argument("--alpha", type=float, default=0.05, help="EWMA smoothing factor.")
    p.add_argument("--min-samples", type=int, default=30, help="cold-start convergence threshold.")
    args = p.parse_args()
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    raise SystemExit(main())
