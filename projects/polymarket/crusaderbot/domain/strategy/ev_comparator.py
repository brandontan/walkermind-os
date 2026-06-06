"""Phase 2 EV-comparator: per-rule empirical EV estimation, argmax selection (shadow).

ORCHESTRATOR_ACTIVE = False by default. Shadow mode: computes the comparator's
preferred rule alongside the precedence router, logs the pick, never routes.
Cutover to True requires explicit WARP🔹CMD greenlight — this module never flips it.

Estimator: shrunk mean realized EV per rule per cell, computed offline from
settled ``factor_vectors`` rows (same source as ``scorer_trainer``). Uses the
per-rule horizon labels via ``row_outcome_for_rule`` so safe_close is judged at
its real 30 s force-exit, not at open→close. Model is stored in
``config/ev_comparator_model.json`` and loaded once at first use.

Abstain: comparator picks nothing when every rule's shrunk EV ≤
``ABSTAIN_EV_THRESHOLD`` (default 0.0) — never selects a rule the data says
loses money in expectation.

Factor-weighted EV estimation (conditioning EV on the factor surface) is deferred
to Phase 3 once more paper_real rows accumulate. This phase nails the base-rate.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

import structlog

from .scorer import RULE_PRECEDENCE, normalize_cell_key, rule_ev, rule_won
from .scorer_trainer import DEFAULT_SHRINKAGE_K, row_outcome_for_rule

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EV_COMPARATOR_SCHEMA_VERSION: int = 1

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


def derive_ev_model(
    rows: Iterable[Mapping[str, Any]],
    *,
    shrinkage_k: float = DEFAULT_SHRINKAGE_K,
    abstain_threshold: float = ABSTAIN_EV_THRESHOLD,
    generated_at: Optional[str] = None,
) -> dict[str, Any]:
    """Derive the per-rule EV model from settled factor_vectors rows.

    For each (cell, rule) pair computes the mean realized EV using the
    per-rule horizon label (safe_close → realized_outcome_safe_close, others →
    realized_outcome), then shrinks toward 0.0 with ``n / (n + shrinkage_k)``
    to prevent thin-data rules from dominating selection. Pure / deterministic.
    """
    # Group by cell.
    cells_rows: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        ck = normalize_cell_key(r.get("asset"), r.get("timeframe"))
        if ck:
            cells_rows.setdefault(ck, []).append(dict(r))

    cells_out: dict[str, dict[str, Any]] = {}
    for ck, cell_rows in cells_rows.items():
        rule_stats: dict[str, Any] = {}
        for rule in RULE_PRECEDENCE:
            evs: list[float] = []
            for r in cell_rows:
                outcome = row_outcome_for_rule(rule, r)
                ev = rule_ev(rule, r.get("fav_side"), r.get("fav_price"), outcome)
                if ev is not None:
                    evs.append(ev)
            n = len(evs)
            mean_ev = _mean(evs)
            shrink = n / (n + shrinkage_k) if (n + shrinkage_k) > 0 else 0.0
            shrunk_ev = mean_ev * shrink
            rule_stats[rule] = {
                "n": n,
                "mean_ev": round(mean_ev, 6) if math.isfinite(mean_ev) else 0.0,
                "shrunk_ev": round(shrunk_ev, 6) if math.isfinite(shrunk_ev) else 0.0,
            }
            log.debug(
                "ev_comparator_derive_rule",
                cell=ck, rule=rule, n=n,
                mean_ev=rule_stats[rule]["mean_ev"],
                shrunk_ev=rule_stats[rule]["shrunk_ev"],
            )
        cells_out[ck] = rule_stats

    return {
        "schema_version": EV_COMPARATOR_SCHEMA_VERSION,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "shrinkage_k": shrinkage_k,
        "abstain_threshold": abstain_threshold,
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

    def estimate_ev(self, cell_key: Optional[str], rule: str) -> Optional[float]:
        """Shrunk estimated EV for ``rule`` in ``cell_key``. ``None`` when unknown."""
        if not cell_key:
            return None
        cell = self._cells.get(cell_key)
        if not isinstance(cell, Mapping):
            return None
        rule_stats = cell.get(rule)
        if not isinstance(rule_stats, Mapping):
            return None
        ev = rule_stats.get("shrunk_ev")
        if ev is None:
            return None
        try:
            v = float(ev)
            return v if math.isfinite(v) else None
        except (TypeError, ValueError):
            return None

    def rank(
        self,
        cell_key: Optional[str],
        candidate_rules: Sequence[str],
        *,
        threshold: Optional[float] = None,
    ) -> list[EVRankedRule]:
        """Rank ``candidate_rules`` by shrunk EV (highest first), mark threshold pass."""
        t = threshold if threshold is not None else self._threshold
        ranked: list[EVRankedRule] = []
        for rule in candidate_rules:
            if rule not in RULE_PRECEDENCE:
                continue
            ev = self.estimate_ev(cell_key, rule)
            shrunk = ev if ev is not None else 0.0
            ranked.append(EVRankedRule(
                rule=rule,
                shrunk_ev=shrunk,
                passes_threshold=shrunk > t,
            ))
        # Sort by shrunk_ev descending; tie-break by precedence.
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
        threshold: Optional[float] = None,
    ) -> Optional[str]:
        """The rule with the highest shrunk EV that exceeds threshold, or ``None`` (abstain)."""
        for r in self.rank(cell_key, candidate_rules, threshold=threshold):
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
# Offline CLI
# ---------------------------------------------------------------------------


def format_ev_model_summary(model: Mapping[str, Any]) -> str:
    """One-screen human-readable summary of the derived EV model."""
    lines: list[str] = []
    lines.append(f"schema_version    : {model.get('schema_version')}")
    lines.append(f"generated_at      : {model.get('generated_at')}")
    lines.append(f"shrinkage_k       : {model.get('shrinkage_k')}")
    lines.append(f"abstain_threshold : {model.get('abstain_threshold')}")
    for ck, rule_stats in sorted((model.get("cells") or {}).items()):
        lines.append(f"  cell {ck}:")
        for rule in RULE_PRECEDENCE:
            rs = (rule_stats or {}).get(rule, {})
            lines.append(
                f"    {rule:<12} n={rs.get('n', 0):>4} "
                f"mean_ev={rs.get('mean_ev', 0.0):+.4f}  "
                f"shrunk_ev={rs.get('shrunk_ev', 0.0):+.4f}"
            )
    return "\n".join(lines)


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
    "get_ev_comparator",
    "format_ev_model_summary",
    "main",
]
