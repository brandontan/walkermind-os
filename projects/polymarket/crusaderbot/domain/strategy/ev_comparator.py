"""Phase 3 EV-comparator: factor-weighted per-rule EV estimation, argmax selection (shadow).

ORCHESTRATOR_ACTIVE = False by default. Shadow mode: computes the comparator's
preferred rule alongside the precedence router, logs the pick, never routes.
Cutover to True requires explicit WARP🔹CMD greenlight — this module never flips it.

Estimator: per-cell, per-rule linear EV model derived offline from settled
``factor_vectors`` rows. For each (cell, rule) pair:
  ``estimated_ev = base_ev + Σ_f  weight[f] * z_f``
where ``base_ev`` is the shrunk mean realized EV, ``weight[f]`` is the shrunk
Pearson correlation of factor ``f`` with the per-rule EV label, and ``z_f`` is
the live factor value standardized by the cell's (mean, std). Uses per-rule
horizon labels via ``row_outcome_for_rule`` so safe_close is judged at its real
30 s force-exit, not at open→close. Model is stored in
``config/ev_comparator_model.json`` and loaded once at first use.

Abstain: comparator picks nothing when every rule's estimated EV ≤
``ABSTAIN_EV_THRESHOLD`` (default 0.0) — never selects a rule the data says
loses money in expectation.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

import structlog

from .scorer import FACTORS, MIN_FACTOR_STD, RULE_PRECEDENCE, normalize_cell_key, rule_ev, rule_won
from .scorer_trainer import DEFAULT_SHRINKAGE_K, row_outcome_for_rule

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EV_COMPARATOR_SCHEMA_VERSION: int = 2

# Abstain when every rule's shrunk EV is at or below this level (no positive edge).
ABSTAIN_EV_THRESHOLD: float = 0.0

# Default model path: <project_root>/config/ev_comparator_model.json
_DEFAULT_MODEL_PATH: Path = (
    Path(__file__).resolve().parents[2] / "config" / "ev_comparator_model.json"
)

# ---------------------------------------------------------------------------
# Model derivation (offline)
# ---------------------------------------------------------------------------


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _pop_std(xs: Sequence[float], mean: float | None = None) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs) if mean is None else mean
    var = sum((x - m) ** 2 for x in xs) / len(xs)
    return math.sqrt(var) if var > 0.0 else 0.0


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float:
    n = len(xs)
    if n < 2 or n != len(ys):
        return 0.0
    mx, my = _mean(xs), _mean(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx <= 0.0 or sy <= 0.0:
        return 0.0
    denom = sx * sy
    if denom <= 0.0:  # underflow guard: tiny-but-positive sx*sy can flush to 0.0
        return 0.0
    r = cov / denom
    if not math.isfinite(r):
        return 0.0
    return max(-1.0, min(1.0, r))


def derive_ev_model(
    rows: Iterable[Mapping[str, Any]],
    *,
    shrinkage_k: float = DEFAULT_SHRINKAGE_K,
    abstain_threshold: float = ABSTAIN_EV_THRESHOLD,
    generated_at: Optional[str] = None,
) -> dict[str, Any]:
    """Derive the factor-weighted per-rule EV model from settled factor_vectors rows.

    For each (cell, rule) pair:
    1. Compute base_ev = shrunk mean realized EV (per-rule horizon labels).
    2. Compute per-factor z-normalization (mean, std over the cell).
    3. Compute per-factor EV weight = shrunk Pearson(factor, rule_ev).
    The runtime uses ``estimated_ev = base_ev + Σ weight[f] * z[f]``.
    Pure / deterministic.
    """
    cells_rows: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        ck = normalize_cell_key(r.get("asset"), r.get("timeframe"))
        if ck:
            cells_rows.setdefault(ck, []).append(dict(r))

    cells_out: dict[str, dict[str, Any]] = {}
    for ck, cell_rows in cells_rows.items():
        # Per-factor normalization stats over the whole cell.
        factor_values: dict[str, list[tuple[int, float]]] = {f: [] for f in FACTORS}
        for idx, r in enumerate(cell_rows):
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

        norm: dict[str, dict[str, float]] = {}
        for f in FACTORS:
            vals = [v for _, v in factor_values[f]]
            mean = _mean(vals)
            std = _pop_std(vals, mean)
            if std < MIN_FACTOR_STD:
                std = 0.0
            # round to 10dp (> MIN_FACTOR_STD precision) so valid small stds survive
            norm[f] = {"mean": round(mean, 10), "std": round(std, 10)}

        rule_stats: dict[str, Any] = {}
        for rule in RULE_PRECEDENCE:
            evs: dict[int, float] = {}
            for idx, r in enumerate(cell_rows):
                outcome = row_outcome_for_rule(rule, r)
                ev = rule_ev(rule, r.get("fav_side"), r.get("fav_price"), outcome)
                if ev is not None:
                    evs[idx] = ev

            n = len(evs)
            mean_ev = _mean(list(evs.values())) if evs else 0.0
            shrink = n / (n + shrinkage_k) if (n + shrinkage_k) > 0 else 0.0
            base_ev = mean_ev * shrink

            weights: dict[str, float] = {}
            for f in FACTORS:
                if norm[f]["std"] <= 0.0:
                    weights[f] = 0.0
                    continue
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
                w = corr * (n_pairs / (n_pairs + shrinkage_k) if (n_pairs + shrinkage_k) > 0 else 0.0)
                weights[f] = round(w, 6) if math.isfinite(w) else 0.0

            rule_stats[rule] = {
                "n": n,
                "mean_ev": round(mean_ev, 6) if math.isfinite(mean_ev) else 0.0,
                "base_ev": round(base_ev, 6) if math.isfinite(base_ev) else 0.0,
                "weights": weights,
            }
            log.debug(
                "ev_comparator_derive_rule",
                cell=ck, rule=rule, n=n,
                mean_ev=rule_stats[rule]["mean_ev"],
                base_ev=rule_stats[rule]["base_ev"],
            )
        cells_out[ck] = {"norm": norm, "rules": rule_stats}

    return {
        "schema_version": EV_COMPARATOR_SCHEMA_VERSION,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "shrinkage_k": shrinkage_k,
        "abstain_threshold": abstain_threshold,
        "factors": list(FACTORS),
        "rules": list(RULE_PRECEDENCE),
        "cells": cells_out,
    }


def write_ev_model(model: Mapping[str, Any], out_path: str | Path | None = None) -> Path:
    """Write the EV model JSON to ``out_path`` (default config/ev_comparator_model.json)."""
    p = Path(out_path) if out_path is not None else _DEFAULT_MODEL_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        json.dump(model, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return p


# ---------------------------------------------------------------------------
# Comparator (runtime, stateless after construction)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EVRankedRule:
    """One ranked rule: its shrunk estimated EV and whether it passes the threshold."""

    rule: str
    shrunk_ev: float
    passes_threshold: bool


class EVComparator:
    """Ranks candidate rules by per-cell shrunk EV, abstains when none exceed threshold.

    Stateless after construction. Fail-soft — a missing/malformed model returns
    an empty ranking so the caller can decide to abstain gracefully.
    """

    def __init__(self, model: Mapping[str, Any]):
        self._model: dict[str, Any] = dict(model or {})
        cells = self._model.get("cells")
        self._cells: dict[str, Any] = dict(cells) if isinstance(cells, dict) else {}
        try:
            self._threshold = float(
                self._model.get("abstain_threshold", ABSTAIN_EV_THRESHOLD)
            )
        except (TypeError, ValueError):
            self._threshold = ABSTAIN_EV_THRESHOLD
        self.trained: bool = bool(self._cells)

    @classmethod
    def neutral(cls) -> "EVComparator":
        """A model-free comparator — always abstains (no positive edge estimated)."""
        return cls({})

    @classmethod
    def from_model(cls, model: Mapping[str, Any]) -> "EVComparator":
        return cls(model)

    @classmethod
    def from_file(cls, path: str | Path | None = None) -> "EVComparator":
        """Load model from ``path``. Fail-soft — returns :meth:`neutral` on error."""
        p = Path(path) if path is not None else _DEFAULT_MODEL_PATH
        try:
            if not p.exists():
                log.info("ev_comparator_model_absent", path=str(p))
                return cls.neutral()
            with p.open("r", encoding="utf-8") as fh:
                model = json.load(fh)
            if not isinstance(model, dict):
                log.warning("ev_comparator_model_malformed", path=str(p))
                return cls.neutral()
            return cls(model)
        except Exception as exc:  # noqa: BLE001
            log.warning("ev_comparator_model_load_failed", path=str(p), error=str(exc))
            return cls.neutral()

    def _z(self, cell: Mapping[str, Any], factor: str, value: Optional[float]) -> float:
        """Standardize ``value`` against the cell's per-factor (mean, std).

        Returns 0.0 when the value is missing/non-finite, the cell lacks norm
        stats for the factor, or the factor is near-constant.
        """
        if value is None:
            return 0.0
        try:
            v = float(value)
        except (TypeError, ValueError):
            return 0.0
        if not math.isfinite(v):
            return 0.0
        norm = cell.get("norm") if isinstance(cell, Mapping) else None
        stats = norm.get(factor) if isinstance(norm, Mapping) else None
        if not isinstance(stats, Mapping):
            return 0.0
        try:
            mean = float(stats.get("mean", 0.0))
            std = float(stats.get("std", 0.0))
        except (TypeError, ValueError):
            return 0.0
        if not math.isfinite(std) or std < MIN_FACTOR_STD:
            return 0.0
        z = (v - mean) / std
        if not math.isfinite(z):
            return 0.0
        # clamp: a tiny-but-valid std could blow a slight deviation into a huge
        # z-score that dominates the EV estimate — cap outliers at ±10 sigma
        return max(-10.0, min(10.0, z))

    def estimate_ev(
        self,
        cell_key: Optional[str],
        rule: str,
        factors: Optional[Mapping[str, Any]] = None,
    ) -> Optional[float]:
        """Factor-weighted estimated EV for ``rule`` in ``cell_key``.

        ``estimated_ev = base_ev + Σ weight[f] * z[f]`` when ``factors`` is
        provided. Without factors falls back to ``base_ev`` (the shrunk mean).
        Returns ``None`` when the cell/rule is unknown.
        """
        if not cell_key:
            return None
        cell = self._cells.get(cell_key)
        if not isinstance(cell, Mapping):
            return None
        rules = cell.get("rules") if isinstance(cell, Mapping) else None
        rule_stats = rules.get(rule) if isinstance(rules, Mapping) else None
        # v1 compat: rules at cell root (no "rules" wrapper)
        if rule_stats is None:
            rule_stats = cell.get(rule)
        if not isinstance(rule_stats, Mapping):
            return None
        try:
            base = float(rule_stats.get("base_ev", rule_stats.get("shrunk_ev", 0.0)))
        except (TypeError, ValueError):
            return None
        if not math.isfinite(base):
            return None
        if factors is None:
            return base
        # Factor adjustment.
        weights = rule_stats.get("weights")
        if isinstance(weights, Mapping):
            for f in FACTORS:
                try:
                    w = float(weights.get(f, 0.0))
                except (TypeError, ValueError):
                    continue
                if w == 0.0 or not math.isfinite(w):
                    continue
                base += w * self._z(cell, f, factors.get(f))
        return base if math.isfinite(base) else None

    def rank(
        self,
        cell_key: Optional[str],
        candidate_rules: Sequence[str],
        *,
        factors: Optional[Mapping[str, Any]] = None,
        threshold: Optional[float] = None,
    ) -> list[EVRankedRule]:
        """Rank ``candidate_rules`` by estimated EV (highest first), mark threshold pass."""
        t = threshold if threshold is not None else self._threshold
        ranked: list[EVRankedRule] = []
        for rule in candidate_rules:
            if rule not in RULE_PRECEDENCE:
                continue
            ev = self.estimate_ev(cell_key, rule, factors)
            est = ev if ev is not None else 0.0
            ranked.append(EVRankedRule(
                rule=rule,
                shrunk_ev=est,
                passes_threshold=est > t,
            ))

        def _precedence(r: EVRankedRule) -> int:
            try:
                return RULE_PRECEDENCE.index(r.rule)
            except ValueError:
                return len(RULE_PRECEDENCE)

        ranked.sort(key=lambda r: (-r.shrunk_ev, _precedence(r)))
        return ranked

    def select(
        self,
        cell_key: Optional[str],
        candidate_rules: Sequence[str],
        *,
        factors: Optional[Mapping[str, Any]] = None,
        threshold: Optional[float] = None,
    ) -> Optional[str]:
        """The rule with the highest estimated EV that exceeds threshold, or ``None`` (abstain)."""
        for r in self.rank(cell_key, candidate_rules, factors=factors, threshold=threshold):
            if r.passes_threshold:
                return r.rule
        return None


# ---------------------------------------------------------------------------
# Process-wide singleton + flag
# ---------------------------------------------------------------------------

# Shadow flag: when False the comparator computes and logs but never routes.
# Cutover to True requires WARP🔹CMD greenlight — this module never flips it.
ORCHESTRATOR_ACTIVE: bool = False

_DEFAULT_COMPARATOR: Optional[EVComparator] = None


def get_ev_comparator(*, reload: bool = False) -> EVComparator:
    """Process-wide singleton loaded from the default model file."""
    global _DEFAULT_COMPARATOR
    if _DEFAULT_COMPARATOR is None or reload:
        _DEFAULT_COMPARATOR = EVComparator.from_file()
    return _DEFAULT_COMPARATOR


# ---------------------------------------------------------------------------
# Cutover kill-switch (WARP-78) — the emergency fallback gate
# ---------------------------------------------------------------------------

# The candle_auto preset key + the rule value that engages the orchestrator.
CANDLE_AUTO_PRESET: str = "candle_auto"
ORCHESTRATOR_RULE: str = "auto"


async def orchestrator_kill_switch_active() -> bool:
    """Runtime emergency kill-switch for the EV-comparator orchestrator.

    Reads the ``ORCHESTRATOR_KILL_SWITCH`` runtime-config overlay (precedence: DB
    override → env/Fly ``Settings`` → code default ``False``), mirroring the
    ``SCAN_SNAPSHOT_ENABLED`` pattern (#1663). When ``True`` the orchestrator is
    halted and ``candle_auto`` + rule ``auto`` users fall back to the precedence
    router — instantly, with NO redeploy (flip the web-admin toggle /
    ``system_settings`` ``cfg:ORCHESTRATOR_KILL_SWITCH`` row).

    Fail-soft: any read error returns the static env/Fly default
    (``Settings.ORCHESTRATOR_KILL_SWITCH``, default ``False``). For a
    redeploy-proof hard halt that survives a DB outage, set that env default
    ``true`` (Fly secret) — it becomes the backstop the overlay layers on top of.
    """
    # env_default is the redeploy-proof backstop; resolve it first so the except
    # branch can fall back to it (returning a hardcoded False would defeat a Fly
    # secret ORCHESTRATOR_KILL_SWITCH=true during a DB outage).
    env_default = False
    try:
        from ...config import get_settings
        from ..ops import runtime_config

        env_default = bool(getattr(get_settings(), "ORCHESTRATOR_KILL_SWITCH", False))
        return await runtime_config.resolve_bool("ORCHESTRATOR_KILL_SWITCH", env_default)
    except Exception:  # noqa: BLE001 — gate read must never break selection
        return env_default


async def orchestrator_routes(preset: Optional[str], rule: Optional[str]) -> bool:
    """Whether the EV-comparator orchestrator should drive selection for a user.

    ``True`` iff the user is on the ``candle_auto`` (Smart Strike) preset with rule
    ``auto`` AND the runtime kill-switch is OFF. Any other preset, a pinned rule,
    or an engaged kill-switch routes via the precedence router instead.

    This is the single gate the cutover wire consults before using
    :meth:`EVComparator.select`. It is dormant today — the
    ``candle_auto``+``auto`` routing wire lands with the cutover PR, so nothing
    calls this yet and it changes no behavior on its own.
    """
    if preset != CANDLE_AUTO_PRESET or rule != ORCHESTRATOR_RULE:
        return False
    return not await orchestrator_kill_switch_active()


# ---------------------------------------------------------------------------
# Offline CLI
# ---------------------------------------------------------------------------


def format_ev_model_summary(model: Mapping[str, Any]) -> str:
    """One-screen human-readable summary of the derived EV model."""
    lines: list[str] = []
    lines.append(f"schema_version    : {model.get('schema_version')}")
    lines.append(f"generated_at      : {model.get('generated_at')}")
    lines.append(f"shrinkage_k       : {model.get('shrinkage_k')}")
    lines.append(f"abstain_threshold : {model.get('abstain_threshold')}")
    for ck, cell_data in sorted((model.get("cells") or {}).items()):
        lines.append(f"  cell {ck}:")
        rule_block = cell_data.get("rules", cell_data) if isinstance(cell_data, dict) else cell_data
        for rule in RULE_PRECEDENCE:
            rs = (rule_block or {}).get(rule, {})
            wv = rs.get("weights", {}) or {}
            top = sorted(wv.items(), key=lambda kv: -abs(kv[1]))[:3]
            top_s = ", ".join(f"{k}={v:+.4f}" for k, v in top) if top else "none"
            lines.append(
                f"    {rule:<12} n={rs.get('n', 0):>4} "
                f"base_ev={rs.get('base_ev', rs.get('shrunk_ev', 0.0)):+.4f}  "
                f"top:[{top_s}]"
            )
    return "\n".join(lines)


def ev_ab_compare(
    rows: Iterable[Mapping[str, Any]],
    comparator: "EVComparator",
) -> dict[str, Any]:
    """Compare EV-comparator selection vs router on settled rows.

    For each row where the router's pick is decidable, the comparator picks
    with factor conditioning, and we compare the realized per-rule EV of each
    pick. Returns per-cell + overall aggregates.
    """
    from .scorer import factors_from_row

    cells: dict[str, dict[str, Any]] = {}
    overall = {"n": 0, "router_ev_sum": 0.0, "comp_ev_sum": 0.0, "agreements": 0, "undecidable": 0, "abstain": 0}

    for row in rows:
        ck = normalize_cell_key(row.get("asset"), row.get("timeframe"))
        cell = cells.setdefault(ck or "UNKNOWN", {"n": 0, "router_ev_sum": 0.0, "comp_ev_sum": 0.0, "agreements": 0, "undecidable": 0, "abstain": 0})

        fav = row.get("fav_side")
        router_rule = row.get("router_selected_rule") or row.get("evaluated_rule")
        if router_rule not in RULE_PRECEDENCE:
            cell["undecidable"] += 1
            overall["undecidable"] += 1
            continue

        router_outcome = row_outcome_for_rule(router_rule, row)
        r_ev = rule_ev(router_rule, fav, row.get("fav_price"), router_outcome)
        if r_ev is None:
            cell["undecidable"] += 1
            overall["undecidable"] += 1
            continue

        factors = factors_from_row(row)
        comp_rule = comparator.select(ck, list(RULE_PRECEDENCE), factors=factors)
        if comp_rule is None:
            cell["abstain"] += 1
            overall["abstain"] += 1
            continue

        comp_outcome = row_outcome_for_rule(comp_rule, row)
        c_ev = rule_ev(comp_rule, fav, row.get("fav_price"), comp_outcome)
        if c_ev is None:
            cell["undecidable"] += 1
            overall["undecidable"] += 1
            continue

        for agg in (cell, overall):
            agg["n"] += 1
            agg["router_ev_sum"] += r_ev
            agg["comp_ev_sum"] += c_ev
            agg["agreements"] += int(comp_rule == router_rule)

    result: dict[str, Any] = {}
    for key, agg in [("overall", overall)] + [(k, v) for k, v in sorted(cells.items())]:
        n = agg["n"]
        result[key] = {
            "n": n,
            "router_avg_ev": round(agg["router_ev_sum"] / n, 6) if n else None,
            "comp_avg_ev": round(agg["comp_ev_sum"] / n, 6) if n else None,
            "ev_delta": round((agg["comp_ev_sum"] - agg["router_ev_sum"]) / n, 6) if n else None,
            "agreement_rate": round(agg["agreements"] / n, 4) if n else None,
            "abstain": agg["abstain"],
            "undecidable": agg["undecidable"],
        }
    return result


def evaluate_ev_holdout(
    rows: Sequence[Mapping[str, Any]],
    *,
    train_fraction: float = 0.7,
    shrinkage_k: float = DEFAULT_SHRINKAGE_K,
) -> dict[str, Any]:
    """Out-of-sample: train on a cell split, evaluate comparator on the rest."""
    by_cell: dict[str, list[Mapping[str, Any]]] = {}
    for r in rows:
        ck = normalize_cell_key(r.get("asset"), r.get("timeframe"))
        by_cell.setdefault(ck or "UNKNOWN", []).append(r)

    train_rows: list[Mapping[str, Any]] = []
    test_rows: list[Mapping[str, Any]] = []
    for cell_rows in by_cell.values():
        if len(cell_rows) < 4:
            train_rows.extend(cell_rows)
            test_rows.extend(cell_rows)
            continue
        cut = max(1, int(len(cell_rows) * train_fraction))
        train_rows.extend(cell_rows[:cut])
        test_rows.extend(cell_rows[cut:] or cell_rows[:cut])

    model = derive_ev_model(train_rows, shrinkage_k=shrinkage_k)
    comparator = EVComparator.from_model(model)
    ab = ev_ab_compare(test_rows, comparator)
    ab["_model_summary"] = {
        "train_rows": len(train_rows),
        "test_rows": len(test_rows),
        "shrinkage_k": shrinkage_k,
        "schema_version": model.get("schema_version"),
    }
    return ab


async def _fetch_and_derive(
    out_path: str | Path | None = None,
    *,
    shrinkage_k: float = DEFAULT_SHRINKAGE_K,
) -> dict[str, Any]:
    from .scorer_trainer import fetch_settled_rows

    rows = await fetch_settled_rows()
    model = derive_ev_model(rows, shrinkage_k=shrinkage_k)
    path = write_ev_model(model, out_path)
    log.info("ev_comparator_model_written", path=str(path), cells=list((model.get("cells") or {}).keys()))
    return model


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    import asyncio

    p = argparse.ArgumentParser(
        prog="ev_comparator",
        description="Derive Phase-2 EV-comparator model from settled factor_vectors.",
    )
    p.add_argument("--from-db", action="store_true", help="Read rows from the configured DB.")
    p.add_argument("--out", default=None, help="Output path for the model JSON.")
    p.add_argument("--shrinkage-k", type=float, default=DEFAULT_SHRINKAGE_K)
    args = p.parse_args(argv)
    if not args.from_db:
        print("Pass --from-db to read the configured database (CMD approval required for prod).")
        return 2
    model = asyncio.run(_fetch_and_derive(args.out, shrinkage_k=args.shrinkage_k))
    print(format_ev_model_summary(model))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "EV_COMPARATOR_SCHEMA_VERSION",
    "ABSTAIN_EV_THRESHOLD",
    "ORCHESTRATOR_ACTIVE",
    "EVRankedRule",
    "EVComparator",
    "derive_ev_model",
    "write_ev_model",
    "ev_ab_compare",
    "evaluate_ev_holdout",
    "get_ev_comparator",
    "orchestrator_kill_switch_active",
    "orchestrator_routes",
    "CANDLE_AUTO_PRESET",
    "ORCHESTRATOR_RULE",
    "format_ev_model_summary",
    "main",
]
