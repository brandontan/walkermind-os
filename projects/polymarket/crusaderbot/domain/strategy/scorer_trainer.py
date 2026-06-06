"""Offline weight derivation for the SMART STRIKE scorer (WARP-72 Phase 2).

Reads the settled ``factor_vectors`` dataset and derives the per-cell, per-rule
linear-scorer weights consumed by ``StrategyScorer``, writing them to
``config/scorer_weights.json``. This is an OFFLINE CLI tool — it never runs in the
scan loop and has zero capital-path effect.

TRAINING CONTRACT (locked by the directive):
  * Train ONLY on rows with ``outcome_source = 'open_to_close'`` AND
    ``settled = TRUE``. Provisional / warming_up / unresolved rows are never used.
  * Derive weights for the data-bearing cells (BTC/5m, ETH/5m). SOL/5m has zero
    usable data → skip with an explicit log, never fabricate a weight vector.
  * The label for a rule on a settled row is its HYPOTHETICAL win:
    ``rule_won(rule, fav_side, realized_outcome)`` — computable for ANY rule from
    the stored ``fav_side`` + realized direction — so every cell row contributes
    to all three rules' weight derivation (max data use on a tiny dataset).

MODEL (per cell):
  * ``norm[factor] = {mean, std}`` over the cell's rows (for z-standardization).
  * ``rules[rule] = {n, base_winrate, weights[factor]}`` where ``base_winrate`` is
    the rule's mean hypothetical win-rate in the cell and ``weights[factor]`` is the
    point-biserial (Pearson) correlation of the factor with that win, shrunk toward
    zero by ``n/(n+K)`` so a tiny sample cannot mint an overconfident weight.

SAFETY: the DB path requires an explicit ``--from-db`` flag so the tool can never
silently read a production database; the WARP-72 directive requires WARP🔹CMD
approval before training against prod. Tests exercise :func:`build_weights` with
in-memory rows — no DB.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

import structlog

from .scorer import (
    FACTORS,
    MIN_FACTOR_STD,
    MODEL_SCHEMA_VERSION,
    RULE_PRECEDENCE,
    normalize_cell_key,
    row_outcome_for_rule,
    rule_ev,
    rule_won,
)

# Training label: realized per-trade EV (``is_win - entry_price``) rather than
# binary win/loss. EV correctly prices the favorite/underdog asymmetry — a cheap
# underdog entry that loses costs little, an expensive favorite that loses costs a
# lot — so the scorer optimizes selection for expected PnL, not raw hit-rate.
LABEL_TYPE: str = "ev"

log = structlog.get_logger(__name__)

# Cells the scorer is trained for and the cells explicitly skipped (no data).
TARGET_CELLS: tuple[str, ...] = ("BTC/5m", "ETH/5m")
SKIP_CELLS: tuple[str, ...] = ("SOL/5m",)

# Small-sample shrinkage constant: weight = pearson * n/(n+K). K=10 keeps a
# ~20-row cell at ~2/3 of the raw correlation, a ~60-row cell at ~6/7.
DEFAULT_SHRINKAGE_K: float = 10.0

# Cutover-readiness floor (directive): a cell needs >= this many settled rows
# before its derived weights are trustworthy enough to consider cutover. Recorded
# per cell as ``sufficient`` — informational; does NOT block weight derivation.
MIN_ROWS_PER_CELL: int = 20

_DEFAULT_OUT_PATH: Path = (
    Path(__file__).resolve().parents[2] / "config" / "scorer_weights.json"
)


# ---------------------------------------------------------------------------
# Small pure stats helpers (stdlib only — numpy is not a dependency)
# ---------------------------------------------------------------------------


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _pop_std(xs: Sequence[float], mean: Optional[float] = None) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs) if mean is None else mean
    var = sum((x - m) ** 2 for x in xs) / len(xs)
    return math.sqrt(var) if var > 0.0 else 0.0


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Pearson correlation of paired samples; 0.0 when undefined (n<2 or zero var)."""
    n = len(xs)
    if n < 2 or n != len(ys):
        return 0.0
    mx, my = _mean(xs), _mean(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx <= 0.0 or sy <= 0.0:
        return 0.0
    r = cov / (sx * sy)
    if not math.isfinite(r):
        return 0.0
    # Numerical guard: clamp to [-1, 1].
    return max(-1.0, min(1.0, r))


# ---------------------------------------------------------------------------
# Per-cell derivation
# ---------------------------------------------------------------------------


def derive_cell(rows: Sequence[Mapping[str, Any]], *, shrinkage_k: float = DEFAULT_SHRINKAGE_K) -> dict[str, Any]:
    """Derive one cell's model from its settled rows.

    Returns ``{n_rows, sufficient, norm, rules}``. Each rule's weights are the
    shrunk point-biserial correlations of the 7 factors with the rule's
    hypothetical win. Pure / deterministic.
    """
    n_rows = len(rows)

    # Per-factor normalization stats over the whole cell.
    norm: dict[str, dict[str, float]] = {}
    factor_values: dict[str, list[tuple[int, float]]] = {f: [] for f in FACTORS}
    for idx, r in enumerate(rows):
        for f in FACTORS:
            v = r.get(f)
            if v is None:
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if math.isfinite(fv):
                factor_values[f].append((idx, fv))
    for f in FACTORS:
        vals = [v for _, v in factor_values[f]]
        mean = _mean(vals)
        std = _pop_std(vals, mean)
        # Collapse a near-constant factor's std to exactly 0.0 so the scorer's
        # MIN_FACTOR_STD guard zeroes it cleanly (e.g. volatility_sigma is a
        # per-asset constant → std ~1e-19 of float noise; standardizing against
        # it would inflate any live deviation into an extreme z-score). Its
        # weight is forced to 0.0 below too.
        if std < MIN_FACTOR_STD:
            std = 0.0
        norm[f] = {"mean": mean, "std": std}

    rules_model: dict[str, Any] = {}
    for rule in RULE_PRECEDENCE:
        # Per-row EV label for this rule (None = undecidable → skipped). The EV
        # label (is_win - entry_price) is the realized per-trade PnL; the binary
        # win is kept alongside as the informational base_winrate.
        evs: dict[int, float] = {}
        wins: dict[int, float] = {}
        for idx, r in enumerate(rows):
            _outcome = row_outcome_for_rule(rule, r)
            ev = rule_ev(rule, r.get("fav_side"), r.get("fav_price"), _outcome)
            if ev is None:
                continue
            evs[idx] = ev
            won = rule_won(rule, r.get("fav_side"), _outcome)
            wins[idx] = 1.0 if won else 0.0
        n = len(evs)
        base = _mean(list(evs.values())) if evs else 0.0
        base_winrate = _mean(list(wins.values())) if wins else 0.0

        weights: dict[str, float] = {}
        for f in FACTORS:
            # Near-constant factor (std collapsed to 0 above): non-discriminative,
            # so its weight is exactly 0 — never a tiny Pearson-noise coefficient
            # that the scorer would divide by a near-zero std.
            if norm[f]["std"] <= 0.0:
                weights[f] = 0.0
                continue
            # Paired (factor, EV) samples over decidable rows that have the factor.
            xs: list[float] = []
            ys: list[float] = []
            for idx, fv in factor_values[f]:
                if idx in evs:
                    xs.append(fv)
                    ys.append(evs[idx])
            n_pairs = len(xs)
            if n_pairs < 2:
                weights[f] = 0.0
                continue
            corr = _pearson(xs, ys)
            shrink = n_pairs / (n_pairs + shrinkage_k) if (n_pairs + shrinkage_k) > 0 else 0.0
            w = corr * shrink
            weights[f] = w if math.isfinite(w) else 0.0

        rules_model[rule] = {
            "n": n,
            "base": base,
            "base_winrate": base_winrate,
            "weights": weights,
        }

    return {
        "n_rows": n_rows,
        "sufficient": n_rows >= MIN_ROWS_PER_CELL,
        "norm": norm,
        "rules": rules_model,
    }


def _bucket_rows_by_cell(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group rows by canonical cell key, dropping rows with no asset/timeframe."""
    buckets: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        cell = normalize_cell_key(r.get("asset"), r.get("timeframe"))
        if cell is None:
            continue
        buckets.setdefault(cell, []).append(dict(r))
    return buckets


def build_weights(
    rows: Iterable[Mapping[str, Any]],
    *,
    target_cells: Sequence[str] = TARGET_CELLS,
    skip_cells: Sequence[str] = SKIP_CELLS,
    shrinkage_k: float = DEFAULT_SHRINKAGE_K,
    generated_at: Optional[str] = None,
) -> dict[str, Any]:
    """Derive the full weights model from settled ``factor_vectors`` rows.

    Pure / deterministic. Only ``target_cells`` get a derived model; ``skip_cells``
    (and any target cell with zero rows) are recorded under ``skipped`` with an
    explicit reason and logged. Rows for cells outside both lists are ignored.
    """
    buckets = _bucket_rows_by_cell(rows)

    cells: dict[str, Any] = {}
    skipped: dict[str, str] = {}

    for cell in skip_cells:
        n = len(buckets.get(cell, []))
        reason = "no_data" if n == 0 else "skip_cell_configured"
        skipped[cell] = reason
        log.info("scorer_trainer_cell_skipped", cell=cell, reason=reason, rows=n)

    for cell in target_cells:
        cell_rows = buckets.get(cell, [])
        if not cell_rows:
            skipped[cell] = "no_data"
            log.info("scorer_trainer_cell_skipped", cell=cell, reason="no_data", rows=0)
            continue
        cells[cell] = derive_cell(cell_rows, shrinkage_k=shrinkage_k)
        log.info(
            "scorer_trainer_cell_derived",
            cell=cell,
            n_rows=cells[cell]["n_rows"],
            sufficient=cells[cell]["sufficient"],
        )

    return {
        "schema_version": MODEL_SCHEMA_VERSION,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "trained": bool(cells),
        "label_type": LABEL_TYPE,
        "train_filter": {"outcome_source": "open_to_close", "settled": True},
        "shrinkage_k": shrinkage_k,
        "factors": list(FACTORS),
        "rules": list(RULE_PRECEDENCE),
        "cells": cells,
        "skipped": skipped,
    }


def write_weights(model: Mapping[str, Any], out_path: str | Path | None = None) -> Path:
    """Write the model JSON to ``out_path`` (default config/scorer_weights.json)."""
    p = Path(out_path) if out_path is not None else _DEFAULT_OUT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        json.dump(model, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return p


# ---------------------------------------------------------------------------
# DB source (explicit opt-in only)
# ---------------------------------------------------------------------------

_FETCH_SQL = """
SELECT condition_id, asset, timeframe, fav_side, entry_side,
       fav_price, entry_price, realized_outcome, realized_delta,
       realized_outcome_safe_close, realized_delta_safe_close,
       momentum, volatility_sigma, liquidity_usdc, spread,
       orderbook_depth_usdc, ttl_sec, oracle_edge,
       oracle_edge_status, router_selected_rule, evaluated_rule
  FROM factor_vectors
 WHERE settled = TRUE
   AND outcome_source = 'open_to_close'
"""


async def fetch_settled_rows(
    pool: object | None = None, *, data_source: str | None = None
) -> list[dict[str, Any]]:
    """Read settled open->close rows from ``factor_vectors``. Fail-soft → [].

    When ``data_source`` is provided (e.g. ``"paper_real"``) the read is
    restricted to that provenance (the WARP-77 #1655 ``data_source`` enum), so a
    cutover model trains ONLY on real rows and never the ``paper_synthetic`` seed.
    ``None`` (the default) reads every provenance — back-compat for the parked
    WARP-72 scorer / A/B callers.
    """
    sql = _FETCH_SQL
    args: list[Any] = []
    if data_source is not None:
        sql = sql + "   AND data_source = $1\n"
        args.append(data_source)
    try:
        if pool is None:
            from ...database import get_pool

            pool = get_pool()
        async with pool.acquire() as conn:  # type: ignore[attr-defined]
            rows = await conn.fetch(sql, *args)
        return [dict(r) for r in rows]
    except Exception as exc:  # noqa: BLE001 — research read must not crash the CLI
        log.warning("scorer_trainer_fetch_failed", error=str(exc))
        return []


async def train_from_db(
    *, out_path: str | Path | None = None, shrinkage_k: float = DEFAULT_SHRINKAGE_K
) -> dict[str, Any]:
    """Fetch settled rows from the configured DB, derive weights, write the file."""
    rows = await fetch_settled_rows()
    model = build_weights(rows, shrinkage_k=shrinkage_k)
    path = write_weights(model, out_path)
    log.info(
        "scorer_trainer_written",
        path=str(path),
        cells=list(model.get("cells", {}).keys()),
        skipped=model.get("skipped", {}),
    )
    return model


def format_summary(model: Mapping[str, Any]) -> str:
    """Human-readable one-screen summary of a derived model (CLI / report use)."""
    lines: list[str] = []
    lines.append(f"schema_version : {model.get('schema_version')}")
    lines.append(f"generated_at   : {model.get('generated_at')}")
    lines.append(f"trained        : {model.get('trained')}")
    lines.append(f"label_type     : {model.get('label_type')}")
    lines.append(f"shrinkage_k    : {model.get('shrinkage_k')}")
    cells = model.get("cells", {}) or {}
    for cell, cm in cells.items():
        lines.append(
            f"  cell {cell}: n_rows={cm.get('n_rows')} sufficient={cm.get('sufficient')}"
        )
        for rule in RULE_PRECEDENCE:
            rm = (cm.get("rules", {}) or {}).get(rule, {})
            wv = rm.get("weights", {}) or {}
            top = sorted(wv.items(), key=lambda kv: -abs(kv[1]))[:3]
            top_s = ", ".join(f"{k}={v:+.3f}" for k, v in top)
            lines.append(
                f"    {rule:<12} n={rm.get('n', 0):>3} base_ev={rm.get('base', 0.0):+.4f} "
                f"winrate={rm.get('base_winrate', 0.0):.3f}  top:[{top_s}]"
            )
    for cell, reason in (model.get("skipped", {}) or {}).items():
        lines.append(f"  cell {cell}: SKIPPED ({reason})")
    return "\n".join(lines)


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="scorer_trainer",
        description="Derive SMART STRIKE scorer weights from settled factor_vectors.",
    )
    p.add_argument(
        "--from-db",
        action="store_true",
        help="Read rows from the configured database. Requires WARP🔹CMD approval "
        "before running against a production DB.",
    )
    p.add_argument(
        "--out",
        default=None,
        help="Output path for the weights JSON (default config/scorer_weights.json).",
    )
    p.add_argument(
        "--shrinkage-k",
        type=float,
        default=DEFAULT_SHRINKAGE_K,
        help=f"Small-sample shrinkage constant K (default {DEFAULT_SHRINKAGE_K}).",
    )
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    if not args.from_db:
        print(
            "Refusing to run without a data source. Pass --from-db to read the "
            "configured database (WARP🔹CMD approval required for prod), or import "
            "build_weights() with your own rows.\n"
            "Example: python -m projects.polymarket.crusaderbot.domain.strategy."
            "scorer_trainer --from-db"
        )
        return 2
    model = asyncio.run(train_from_db(out_path=args.out, shrinkage_k=args.shrinkage_k))
    print(format_summary(model))
    return 0


if __name__ == "__main__":  # pragma: no cover — manual / CI invocation
    raise SystemExit(main())


__all__ = [
    "TARGET_CELLS",
    "SKIP_CELLS",
    "DEFAULT_SHRINKAGE_K",
    "MIN_ROWS_PER_CELL",
    "derive_cell",
    "build_weights",
    "write_weights",
    "fetch_settled_rows",
    "train_from_db",
    "format_summary",
    "main",
    # re-exported for consumers that only import scorer_trainer
    "row_outcome_for_rule",
]
