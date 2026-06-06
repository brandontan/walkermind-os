"""WARP-78 cutover pipeline dry-run (synthetic, in-memory).

Proves the EV model-generation + holdout pipeline is bug-free BEFORE the
real ``paper_real`` rows land, by feeding synthetic-but-realistic
``factor_vectors`` rows with a KNOWN injected ground truth through the real
production code paths:

    derive_ev_model -> EVComparator -> ev_ab_compare / evaluate_ev_holdout

Scope-lock: everything is in-memory. This script NEVER touches Supabase or
writes a synthetic row to ``factor_vectors``. It exercises the offline model
pipeline only; it does not flip ``ORCHESTRATOR_ACTIVE`` and changes no prod
behaviour.

Injected ground truth (so pipeline output is checkable):
  * ``momentum`` drives the favorite's win probability (favorite rules
    close_sweep / safe_close gain +EV with momentum; the underdog rule
    flip_hunter is its mirror image and gains +EV when momentum is negative).
  * ``oracle_edge`` is a weaker second driver with the same sign pattern.
  * ``volatility_sigma`` is a per-asset constant (dead signal) -> weight 0.
  * the router pick is ttl-window-driven and momentum-blind, so a
    momentum-aware comparator should beat it out-of-sample.

Expected, checkable signature:
  1. recovered ``momentum`` weight is positive for favorite rules, negative
     for flip_hunter, and dominates the non-injected factors;
  2. ``volatility_sigma`` weight is exactly 0.0 (near-constant std floor);
  3. no NaN / non-finite anywhere in the model;
  4. JSON serialize -> reload -> identical comparator picks;
  5. holdout overall ev_delta > 0 with a computed 95% confidence interval.

Run:  python scripts/cutover_pipeline_dryrun.py [--rows-per-cell N] [--seed S]
Exit: 0 = all checks pass, 1 = a check failed.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import random
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

import structlog

# Make the project root importable when run as a bare script.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# NB: structlog config is deferred to main() — configuring it at import scope
# would mutate the global logging level for the whole test runner process, so
# importing this module from a test would silence other tests' captured logs.

from domain.strategy.ev_comparator import (  # noqa: E402
    EVComparator,
    derive_ev_model,
    evaluate_ev_holdout,
    ev_ab_compare,
    format_ev_model_summary,
    write_ev_model,
)
from domain.strategy.scorer import (  # noqa: E402
    FACTORS,
    RULE_PRECEDENCE,
    factors_from_row,
    normalize_cell_key,
    row_outcome_for_rule,
    rule_ev,
)

# Cells mirror the WARP-78 target grid (asset stored lower-case in the DB).
CELLS: tuple[tuple[str, str], tuple[str, str], tuple[str, str], tuple[str, str]] = (
    ("btc", "5m"),
    ("btc", "15m"),
    ("eth", "5m"),
    ("eth", "15m"),
)

# Per-asset constant "dead" volatility sigma (mirrors the real near-constant).
_ASSET_SIGMA: dict[str, float] = {"btc": 0.00090, "eth": 0.00120}
_ASSET_RVOL: dict[str, float] = {"btc": 0.0289, "eth": 0.0364}

# Injected ground-truth coefficients (favorite-win-probability tilt per 1 sigma).
GAMMA_MOMENTUM: float = 0.13
GAMMA_ORACLE: float = 0.06
_MOM_SD: float = 0.6
_OE_SD: float = 0.02
_SAFE_CLOSE_FLIP_P: float = 0.08  # final-30s reversal rate vs open->close label
# Shared train/test split so evaluate_ev_holdout and _paired_holdout_deltas
# always agree (keeps the holdout_vs_paired_delta_consistent check robust even
# if ev_comparator's own default ever changes).
_TRAIN_FRACTION: float = 0.7


@dataclass(frozen=True)
class GroundTruth:
    """The injected signal the recovered model is checked against."""

    favorite_rules: tuple[str, ...] = ("close_sweep", "safe_close")
    underdog_rules: tuple[str, ...] = ("flip_hunter",)
    dead_factor: str = "volatility_sigma"
    driver: str = "momentum"
    second_driver: str = "oracle_edge"
    non_injected: tuple[str, ...] = ("liquidity_usdc", "spread", "orderbook_depth_usdc", "ttl_sec")


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""
    # Informational checks are a statistical SIGNATURE (effect-size / power
    # dependent), reported but NOT counted toward the pass/fail verdict. The
    # hard gate is pipeline CORRECTNESS (no NaN, weight recovery, serialization).
    informational: bool = False


def _flip(outcome: str) -> str:
    return "DOWN" if outcome == "UP" else "UP"


def _router_rule_for_ttl(ttl_sec: float) -> str:
    """Momentum-blind, time-window precedence pick (what the comparator improves on)."""
    if ttl_sec < 40.0:
        return "close_sweep"
    if ttl_sec < 70.0:
        return "safe_close"
    return "flip_hunter"


def generate_synthetic_rows(
    *, rows_per_cell: int, seed: int
) -> list[dict[str, Any]]:
    """Build settled, realistically-distributed factor_vectors rows with injected EV signal."""
    rng = random.Random(seed)
    rows: list[dict[str, Any]] = []
    for asset, timeframe in CELLS:
        sigma = _ASSET_SIGMA[asset]
        rvol_base = _ASSET_RVOL[asset]
        ttl_cap = 300.0 if timeframe == "5m" else 900.0
        for _ in range(rows_per_cell):
            momentum = rng.gauss(0.0, _MOM_SD)
            oracle_edge = rng.gauss(0.0, _OE_SD)
            z_mom = momentum / _MOM_SD
            z_oe = oracle_edge / _OE_SD

            fav_side = "YES" if rng.random() < 0.5 else "NO"
            fav_price = min(0.85, max(0.52, 0.5 + abs(rng.gauss(0.0, 0.12))))
            ttl_sec = rng.uniform(8.0, ttl_cap)

            # Injected: P(favorite wins) tilts with momentum + oracle_edge.
            p_fav_win = min(0.95, max(0.05, fav_price + GAMMA_MOMENTUM * z_mom + GAMMA_ORACLE * z_oe))
            fav_wins = rng.random() < p_fav_win
            winner_side = fav_side if fav_wins else ("NO" if fav_side == "YES" else "YES")
            realized_outcome = "UP" if winner_side == "YES" else "DOWN"
            # safe_close horizon (close-30s): occasionally reverses the final 30s.
            sc_outcome = _flip(realized_outcome) if rng.random() < _SAFE_CLOSE_FLIP_P else realized_outcome

            delta_mag = abs(rng.gauss(0.0, 0.003))
            realized_delta = delta_mag if realized_outcome == "UP" else -delta_mag
            sc_delta = delta_mag if sc_outcome == "UP" else -delta_mag

            router_rule = _router_rule_for_ttl(ttl_sec)
            rows.append(
                {
                    "condition_id": f"syn-{asset}-{timeframe}-{len(rows)}",
                    "market_id": f"mkt-{len(rows)}",
                    "asset": asset,
                    "timeframe": timeframe,
                    # --- 7 model factors ---
                    "momentum": round(momentum, 8),
                    "volatility_sigma": round(sigma + rng.gauss(0.0, 1e-12), 12),
                    "liquidity_usdc": round(math.exp(rng.gauss(math.log(3000.0), 0.5)), 6),
                    "spread": round(abs(rng.gauss(0.012, 0.004)) + 1e-4, 6),
                    "orderbook_depth_usdc": round(math.exp(rng.gauss(math.log(1500.0), 0.5)), 6),
                    "ttl_sec": round(ttl_sec, 3),
                    "oracle_edge": round(oracle_edge, 8),
                    # --- broader schema columns (faithful shape; not model factors) ---
                    "momentum_delta": round(rng.gauss(0.0, 0.3), 8),
                    "momentum_span_sec": 30.0,
                    "momentum_samples": rng.randint(5, 20),
                    "realized_vol": round(abs(rng.gauss(rvol_base, rvol_base * 0.25)), 10),
                    "oracle_edge_status": "computed",
                    "ask_diff": round(rng.gauss(0.0, 0.01), 6),
                    "complete_set_edge": round(rng.gauss(0.0, 0.01), 6),
                    "fav_side": fav_side,
                    "entry_side": fav_side,
                    "fav_price": round(fav_price, 6),
                    "entry_price": round(fav_price, 6),
                    "underdog_mode": router_rule == "flip_hunter",
                    # --- labels ---
                    "realized_outcome": realized_outcome,
                    "realized_delta": round(realized_delta, 10),
                    "realized_outcome_safe_close": sc_outcome,
                    "realized_delta_safe_close": round(sc_delta, 10),
                    "outcome_source": "open_to_close",
                    "settled": True,
                    "router_selected_rule": router_rule,
                    "evaluated_rule": router_rule,
                    "data_source": "paper_synthetic",
                }
            )
    return rows


def _paired_holdout_deltas(
    rows: Sequence[dict[str, Any]], *, train_fraction: float
) -> dict[str, Any]:
    """Replay the A/B decision per holdout row to get paired EV deltas for a CI.

    Mirrors ``ev_ab_compare``'s row logic exactly (same public helpers), but
    keeps the per-row paired delta so a confidence interval can be computed.
    """
    by_cell: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        ck = normalize_cell_key(r.get("asset"), r.get("timeframe")) or "UNKNOWN"
        by_cell.setdefault(ck, []).append(r)

    train_rows: list[dict[str, Any]] = []
    test_rows: list[dict[str, Any]] = []
    for cell_rows in by_cell.values():
        if len(cell_rows) < 4:
            train_rows.extend(cell_rows)
            test_rows.extend(cell_rows)
            continue
        cut = max(1, int(len(cell_rows) * train_fraction))
        train_rows.extend(cell_rows[:cut])
        test_rows.extend(cell_rows[cut:] or cell_rows[:cut])

    comparator = EVComparator.from_model(derive_ev_model(train_rows))
    deltas: list[float] = []
    abstain = undecidable = 0
    for row in test_rows:
        router_rule = row.get("router_selected_rule") or row.get("evaluated_rule")
        if router_rule not in RULE_PRECEDENCE:
            undecidable += 1
            continue
        fav = row.get("fav_side")
        r_ev = rule_ev(router_rule, fav, row.get("fav_price"), row_outcome_for_rule(router_rule, row))
        if r_ev is None:
            undecidable += 1
            continue
        ck = normalize_cell_key(row.get("asset"), row.get("timeframe"))
        comp_rule = comparator.select(ck, list(RULE_PRECEDENCE), factors=factors_from_row(row))
        if comp_rule is None:
            abstain += 1
            continue
        c_ev = rule_ev(comp_rule, fav, row.get("fav_price"), row_outcome_for_rule(comp_rule, row))
        if c_ev is None:
            undecidable += 1
            continue
        deltas.append(c_ev - r_ev)

    n = len(deltas)
    mean = sum(deltas) / n if n else 0.0
    if n > 1:
        var = sum((d - mean) ** 2 for d in deltas) / (n - 1)
        se = math.sqrt(var / n)
    else:
        se = 0.0
    half = 1.96 * se
    return {
        "n": n,
        "mean_delta": mean,
        "se": se,
        "ci95": (mean - half, mean + half),
        "ci_excludes_zero": n > 1 and (mean - half) > 0.0,
        "abstain": abstain,
        "undecidable": undecidable,
    }


def _finite(x: Any) -> bool:
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def validate_no_nan(model: dict[str, Any]) -> list[Check]:
    checks: list[Check] = []
    bad: list[str] = []
    for ck, cell in (model.get("cells") or {}).items():
        for f, stats in (cell.get("norm") or {}).items():
            if not (_finite(stats.get("mean")) and _finite(stats.get("std"))):
                bad.append(f"{ck}.norm.{f}")
        for rule, rs in (cell.get("rules") or {}).items():
            if not _finite(rs.get("base_ev")):
                bad.append(f"{ck}.{rule}.base_ev")
            for f, w in (rs.get("weights") or {}).items():
                if not _finite(w):
                    bad.append(f"{ck}.{rule}.weights.{f}")
    checks.append(Check("no_nan_or_nonfinite", not bad, "clean" if not bad else f"non-finite: {bad[:5]}"))
    return checks


def validate_weight_recovery(model: dict[str, Any], gt: GroundTruth) -> list[Check]:
    checks: list[Check] = []
    cells = model.get("cells") or {}
    fav_pos = under_neg = dead_zero = dominates = 0
    cell_count = 0
    for ck, cell in cells.items():
        rules = cell.get("rules") or {}
        cell_count += 1
        for rule in gt.favorite_rules:
            w = (rules.get(rule, {}).get("weights") or {}).get(gt.driver, 0.0)
            fav_pos += int(w > 0.0)
        for rule in gt.underdog_rules:
            w = (rules.get(rule, {}).get("weights") or {}).get(gt.driver, 0.0)
            under_neg += int(w < 0.0)
        # dead factor std must be floored to 0 -> weight 0
        dead_w = (rules.get("close_sweep", {}).get("weights") or {}).get(gt.dead_factor, 1.0)
        dead_zero += int(dead_w == 0.0)
        # momentum should dominate non-injected factors for close_sweep
        cs_w = rules.get("close_sweep", {}).get("weights") or {}
        mom = abs(cs_w.get(gt.driver, 0.0))
        noise = max((abs(cs_w.get(f, 0.0)) for f in gt.non_injected), default=0.0)
        dominates += int(mom > noise)

    n_fav = cell_count * len(gt.favorite_rules)
    n_und = cell_count * len(gt.underdog_rules)
    checks.append(Check("momentum_positive_for_favorite_rules", fav_pos == n_fav, f"{fav_pos}/{n_fav}"))
    checks.append(Check("momentum_negative_for_flip_hunter", under_neg == n_und, f"{under_neg}/{n_und}"))
    checks.append(Check("dead_volatility_weight_zero", dead_zero == cell_count, f"{dead_zero}/{cell_count}"))
    checks.append(Check("momentum_dominates_noise_factors", dominates == cell_count, f"{dominates}/{cell_count}"))
    return checks


def validate_serialization(model: dict[str, Any], rows: Sequence[dict[str, Any]]) -> list[Check]:
    with tempfile.TemporaryDirectory() as tmp:
        path = write_ev_model(model, Path(tmp) / "ev_model.json")
        reloaded = json.loads(path.read_text(encoding="utf-8"))
        live = EVComparator.from_model(model)
        disk = EVComparator.from_file(path)
        mismatches = 0
        for row in rows[:200]:
            ck = normalize_cell_key(row.get("asset"), row.get("timeframe"))
            f = factors_from_row(row)
            if live.select(ck, list(RULE_PRECEDENCE), factors=f) != disk.select(
                ck, list(RULE_PRECEDENCE), factors=f
            ):
                mismatches += 1
    ok = reloaded.get("schema_version") == model.get("schema_version") and mismatches == 0
    return [Check("json_roundtrip_identical_picks", ok, f"mismatches={mismatches}")]


def validate_holdout(holdout: dict[str, Any], ci: dict[str, Any], gt: GroundTruth) -> list[Check]:
    checks: list[Check] = []
    overall = holdout.get("overall") or {}
    delta = overall.get("ev_delta")
    checks.append(
        Check("holdout_ev_delta_positive", bool(delta is not None and delta > 0.0), f"ev_delta={delta}")
    )
    finite_cells = all(
        _finite(v.get("router_avg_ev")) and _finite(v.get("comp_avg_ev"))
        for k, v in holdout.items()
        if k != "_model_summary" and (v.get("n") or 0) > 0
    )
    checks.append(Check("holdout_per_cell_avgs_finite", finite_cells))
    checks.append(Check("holdout_ci_computed", _finite(ci.get("mean_delta")) and ci.get("n", 0) > 1,
                        f"n={ci.get('n')} ci95={tuple(round(x,5) for x in ci.get('ci95', (0,0)))}"))
    checks.append(Check("holdout_ci_excludes_zero", bool(ci.get("ci_excludes_zero")),
                        f"excludes_zero={ci.get('ci_excludes_zero')}", informational=True))
    # Anti-column-mapping-bug: the independent paired-delta mean must agree with
    # ev_ab_compare's overall ev_delta (same rows, same helpers, two code paths).
    consistent = (
        delta is not None
        and _finite(ci.get("mean_delta"))
        and abs(float(delta) - float(ci["mean_delta"])) < 1e-6
    )
    checks.append(Check("holdout_vs_paired_delta_consistent", bool(consistent),
                        f"ab={delta} paired={round(ci.get('mean_delta', 0.0), 6)}"))
    return checks


def run_dryrun(*, rows_per_cell: int, seed: int) -> tuple[list[Check], dict[str, Any]]:
    gt = GroundTruth()
    rows = generate_synthetic_rows(rows_per_cell=rows_per_cell, seed=seed)
    full_model = derive_ev_model(rows)
    comparator = EVComparator.from_model(full_model)
    in_sample_ab = ev_ab_compare(rows, comparator)
    holdout = evaluate_ev_holdout(rows, train_fraction=_TRAIN_FRACTION)
    ci = _paired_holdout_deltas(rows, train_fraction=_TRAIN_FRACTION)

    checks: list[Check] = []
    checks += validate_no_nan(full_model)
    checks += validate_weight_recovery(full_model, gt)
    checks += validate_serialization(full_model, rows)
    checks += validate_holdout(holdout, ci, gt)

    artifacts = {
        "rows": len(rows),
        "cells": list((full_model.get("cells") or {}).keys()),
        "model_summary": format_ev_model_summary(full_model),
        "in_sample_overall": in_sample_ab.get("overall"),
        "holdout": holdout,
        "ci": ci,
    }
    return checks, artifacts


def main(argv: Optional[Sequence[str]] = None) -> int:
    # Quiet the pipeline's shadow DEBUG logs so the CLI report is clean. Done
    # here (not at import) so importing this module never mutates global logging.
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))

    p = argparse.ArgumentParser(prog="cutover_pipeline_dryrun", description=__doc__)
    p.add_argument("--rows-per-cell", type=int, default=200)
    p.add_argument("--seed", type=int, default=78)
    p.add_argument("--verbose", action="store_true", help="Print the full model summary.")
    args = p.parse_args(argv)

    checks, art = run_dryrun(rows_per_cell=args.rows_per_cell, seed=args.seed)

    print("=" * 72)
    print(f"WARP-78 CUTOVER PIPELINE DRY-RUN  (synthetic, in-memory, no DB)")
    print(f"rows={art['rows']}  cells={art['cells']}  seed={args.seed}")
    print("=" * 72)
    if args.verbose:
        print(art["model_summary"])
        print("-" * 72)
    ho = art["holdout"].get("overall") or {}
    print(f"in-sample overall : {art['in_sample_overall']}")
    print(f"holdout overall   : router_ev={ho.get('router_avg_ev')} comp_ev={ho.get('comp_avg_ev')} "
          f"ev_delta={ho.get('ev_delta')} agree={ho.get('agreement_rate')} "
          f"abstain={ho.get('abstain')} undecidable={ho.get('undecidable')}")
    ci = art["ci"]
    print(f"holdout paired CI : n={ci['n']} mean_delta={ci['mean_delta']:+.5f} "
          f"95%CI=[{ci['ci95'][0]:+.5f}, {ci['ci95'][1]:+.5f}] excludes_zero={ci['ci_excludes_zero']}")
    print("-" * 72)
    failed = 0
    for c in checks:
        if c.informational:
            mark = "INFO" if c.passed else "WARN"
        else:
            mark = "PASS" if c.passed else "FAIL"
            failed += int(not c.passed)
        print(f"  [{mark}] {c.name:<38} {c.detail}")
    print("-" * 72)
    verdict = "PIPELINE READY" if failed == 0 else f"FAILED ({failed} correctness check(s))"
    print(f"VERDICT: {verdict}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
