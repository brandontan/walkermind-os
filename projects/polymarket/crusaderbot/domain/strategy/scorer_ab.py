"""SMART STRIKE scorer vs router A/B comparison (WARP-72 Phase 2).

Measures whether the data-derived :class:`StrategyScorer` selects winning candle
rules more often than the precedence-only router, on the SAME settled
``factor_vectors`` rows. Pure read-side analytics — never selects, sizes, or gates
a live trade.

For each settled ``open_to_close`` row both selectors pick a rule and the row's
realized outcome decides the win:
  * router pick = the rule the precedence router actually chose
    (``router_selected_rule``; ``evaluated_rule`` fallback).
  * scorer pick = ``StrategyScorer.select(...)`` over the full 3-rule menu, with
    the Oracle deny-gate applied.
  * win = ``rule_won(pick, fav_side, realized_outcome)`` — the pick's hypothetical
    entry side vs the realized winning side.

The cutover criterion (documented, NOT implemented here): scorer win-rate must
exceed router win-rate on HELD-OUT settled data with >= 20 rows per cell. Use
:func:`evaluate_holdout` for the out-of-sample read; :func:`compare` measures a
fixed model in-sample.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional, Sequence

import structlog

from .scorer import (
    RULE_PRECEDENCE,
    StrategyScorer,
    factors_from_row,
    normalize_cell_key,
    row_outcome_for_rule,
    rule_ev,
    rule_won,
)

log = structlog.get_logger(__name__)


@dataclass
class CellAB:
    """Per-cell scorer-vs-router comparison aggregates."""

    cell: str
    n_compared: int = 0          # rows where both selectors made a decidable pick
    router_wins: int = 0
    scorer_wins: int = 0
    router_ev_sum: float = 0.0   # Σ realized EV of the router's picks (ev-compared rows)
    scorer_ev_sum: float = 0.0   # Σ realized EV of the scorer's picks (ev-compared rows)
    n_ev_compared: int = 0       # compared rows where EV was decidable (valid fav_price)
    agreements: int = 0          # rows where scorer pick == router pick
    scorer_abstain: int = 0      # rows where the Oracle deny-gate left no pick
    undecidable: int = 0         # rows missing fav_side / realized winner / attributable rule

    @property
    def router_winrate(self) -> Optional[float]:
        return (self.router_wins / self.n_compared) if self.n_compared else None

    @property
    def scorer_winrate(self) -> Optional[float]:
        return (self.scorer_wins / self.n_compared) if self.n_compared else None

    @property
    def winrate_delta(self) -> Optional[float]:
        """scorer_winrate - router_winrate; ``None`` when nothing was compared."""
        if not self.n_compared:
            return None
        return (self.scorer_wins - self.router_wins) / self.n_compared

    @property
    def router_ev(self) -> Optional[float]:
        """Router's avg realized EV per trade (over EV-decidable compared rows)."""
        return (self.router_ev_sum / self.n_ev_compared) if self.n_ev_compared else None

    @property
    def scorer_ev(self) -> Optional[float]:
        """Scorer's avg realized EV per trade (over EV-decidable compared rows)."""
        return (self.scorer_ev_sum / self.n_ev_compared) if self.n_ev_compared else None

    @property
    def ev_delta(self) -> Optional[float]:
        """avg EV/trade delta (scorer - router); ``None`` when no EV-decidable rows.

        Divides by ``n_ev_compared`` (rows with a valid ``fav_price``) so rows that
        are win-rate-decidable but EV-undecidable cannot dilute the average toward
        zero. This is the cutover metric: the scorer is preferred only when this is
        positive (scorer earns more expected PnL per trade than the router).
        """
        if not self.n_ev_compared:
            return None
        return (self.scorer_ev_sum - self.router_ev_sum) / self.n_ev_compared

    @property
    def agreement_rate(self) -> Optional[float]:
        return (self.agreements / self.n_compared) if self.n_compared else None


@dataclass
class ABReport:
    """Full A/B result: per-cell aggregates + a rolled-up overall cell."""

    cells: dict[str, CellAB] = field(default_factory=dict)
    overall: CellAB = field(default_factory=lambda: CellAB(cell="ALL"))


def _attributable_router_rule(row: Mapping[str, Any]) -> Optional[str]:
    """The rule to credit the router with for this row, or ``None`` if unknowable."""
    for key in ("router_selected_rule", "evaluated_rule"):
        r = row.get(key)
        if r in RULE_PRECEDENCE:
            return str(r)
    return None


def compare(
    rows: Iterable[Mapping[str, Any]],
    scorer: StrategyScorer,
    *,
    candidate_rules: Sequence[str] = RULE_PRECEDENCE,
) -> ABReport:
    """Compare ``scorer`` against the router across settled rows. Pure.

    The scorer ranks the full ``candidate_rules`` menu per row (the live router
    only sees the rules whose windows matched; on a settled row that subset is not
    recoverable, so the menu is the faithful proxy — documented approximation).
    Rows where ``fav_side`` / the realized winner / an attributable router rule are
    missing are counted as ``undecidable`` and excluded from win-rates.
    """
    report = ABReport()

    for row in rows:
        cell_key = normalize_cell_key(row.get("asset"), row.get("timeframe"))
        cell = report.cells.setdefault(cell_key or "UNKNOWN", CellAB(cell=cell_key or "UNKNOWN"))

        fav = row.get("fav_side")
        router_rule = _attributable_router_rule(row)

        # Need an attributable router rule to compare at all.
        if router_rule is None:
            cell.undecidable += 1
            report.overall.undecidable += 1
            continue

        # Per-rule horizon label: safe_close uses the 30-s-before-close outcome.
        router_outcome = row_outcome_for_rule(router_rule, row)
        if rule_won(router_rule, fav, router_outcome) is None:
            cell.undecidable += 1
            report.overall.undecidable += 1
            continue

        scorer_rule = scorer.select(
            cell_key,
            factors_from_row(row),
            candidate_rules,
            oracle_edge=row.get("oracle_edge"),
            oracle_edge_status=row.get("oracle_edge_status"),
        )
        if scorer_rule is None:
            # Every candidate denied by the Oracle gate — scorer makes no pick.
            cell.scorer_abstain += 1
            report.overall.scorer_abstain += 1
            continue

        scorer_outcome = row_outcome_for_rule(scorer_rule, row)
        router_win = bool(rule_won(router_rule, fav, router_outcome))
        scorer_win = bool(rule_won(scorer_rule, fav, scorer_outcome))
        fav_price = row.get("fav_price")
        router_ev = rule_ev(router_rule, fav, fav_price, router_outcome)
        scorer_ev = rule_ev(scorer_rule, fav, fav_price, scorer_outcome)

        for agg in (cell, report.overall):
            agg.n_compared += 1
            agg.router_wins += int(router_win)
            agg.scorer_wins += int(scorer_win)
            # EV is decidable only with a valid fav_price (both picks share it, so
            # they are None together). Gate on both + a dedicated counter so an
            # EV-undecidable row never dilutes the avg-EV denominator.
            if router_ev is not None and scorer_ev is not None:
                agg.router_ev_sum += router_ev
                agg.scorer_ev_sum += scorer_ev
                agg.n_ev_compared += 1
            agg.agreements += int(scorer_rule == router_rule)

    return report


def evaluate_holdout(
    rows: Sequence[Mapping[str, Any]],
    *,
    train_fraction: float = 0.7,
    shrinkage_k: Optional[float] = None,
) -> ABReport:
    """Out-of-sample A/B: train the scorer on a row split, evaluate on the rest.

    Deterministic per-cell split (first ``train_fraction`` of each cell's rows
    train; the remainder is the held-out test set) so the comparison is the honest
    out-of-sample read the cutover criterion calls for. Falls back to in-sample
    :func:`compare` for any cell too small to split.
    """
    # Imported here to avoid a circular import at module load (trainer imports
    # scorer; this module imports both).
    from .scorer_trainer import DEFAULT_SHRINKAGE_K, build_weights

    k = DEFAULT_SHRINKAGE_K if shrinkage_k is None else shrinkage_k

    by_cell: dict[str, list[Mapping[str, Any]]] = {}
    for r in rows:
        ck = normalize_cell_key(r.get("asset"), r.get("timeframe"))
        by_cell.setdefault(ck or "UNKNOWN", []).append(r)

    train_rows: list[Mapping[str, Any]] = []
    test_rows: list[Mapping[str, Any]] = []
    for cell_rows in by_cell.values():
        if len(cell_rows) < 4:
            # Too small to split — evaluate in-sample (documented degenerate case).
            train_rows.extend(cell_rows)
            test_rows.extend(cell_rows)
            continue
        cut = max(1, int(len(cell_rows) * train_fraction))
        train_rows.extend(cell_rows[:cut])
        test_rows.extend(cell_rows[cut:] or cell_rows[:cut])

    model = build_weights(train_rows, shrinkage_k=k)
    scorer = StrategyScorer.from_model(model)
    return compare(test_rows, scorer)


def format_report(report: ABReport) -> str:
    """Render the A/B report as a fixed-width text table."""
    head = (
        f"{'cell':<10} {'n':>5} {'router_wr':>10} {'scorer_wr':>10} "
        f"{'delta':>8} {'agree':>7} {'abstain':>8} {'undec':>6}"
    )
    lines = [head, "-" * len(head)]

    def _row(c: CellAB) -> str:
        rw = f"{c.router_winrate:.3f}" if c.router_winrate is not None else "N/A"
        sw = f"{c.scorer_winrate:.3f}" if c.scorer_winrate is not None else "N/A"
        dl = f"{c.winrate_delta:+.3f}" if c.winrate_delta is not None else "N/A"
        ag = f"{c.agreement_rate:.3f}" if c.agreement_rate is not None else "N/A"
        return (
            f"{c.cell:<10} {c.n_compared:>5} {rw:>10} {sw:>10} "
            f"{dl:>8} {ag:>7} {c.scorer_abstain:>8} {c.undecidable:>6}"
        )

    for cell in sorted(report.cells):
        lines.append(_row(report.cells[cell]))
    lines.append("-" * len(head))
    lines.append(_row(report.overall))
    return "\n".join(lines)


def format_ev_report(report: ABReport) -> str:
    """Render the avg-EV/trade comparison (the cutover metric) as a text table.

    ``router_ev`` / ``scorer_ev`` are average realized per-trade EV
    (``is_win - entry_price``) over the compared rows; ``ev_delta`` is
    ``scorer - router``. The scorer is preferred only when ``ev_delta > 0``.
    """
    head = (
        f"{'cell':<10} {'n':>5} {'router_ev':>11} {'scorer_ev':>11} "
        f"{'ev_delta':>10} {'abstain':>8}"
    )
    lines = [head, "-" * len(head)]

    def _row(c: CellAB) -> str:
        rev = f"{c.router_ev:+.4f}" if c.router_ev is not None else "N/A"
        sev = f"{c.scorer_ev:+.4f}" if c.scorer_ev is not None else "N/A"
        dl = f"{c.ev_delta:+.4f}" if c.ev_delta is not None else "N/A"
        return (
            f"{c.cell:<10} {c.n_ev_compared:>5} {rev:>11} {sev:>11} "
            f"{dl:>10} {c.scorer_abstain:>8}"
        )

    for cell in sorted(report.cells):
        lines.append(_row(report.cells[cell]))
    lines.append("-" * len(head))
    lines.append(_row(report.overall))
    return "\n".join(lines)


async def _fetch_rows() -> list[dict[str, Any]]:
    """Read settled open->close rows for the A/B (reuses the trainer's query)."""
    from .scorer_trainer import fetch_settled_rows

    return await fetch_settled_rows()


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="scorer_ab",
        description="A/B: SMART STRIKE scorer vs precedence router on settled rows.",
    )
    parser.add_argument(
        "--from-db",
        action="store_true",
        help="Read settled rows from the configured DB (WARP🔹CMD approval for prod).",
    )
    parser.add_argument(
        "--holdout",
        action="store_true",
        help="Out-of-sample: train on a split, evaluate on the held-out remainder.",
    )
    parser.add_argument("--weights", default=None, help="Path to a weights JSON (in-sample mode).")
    args = parser.parse_args(argv)

    if not args.from_db:
        print("Refusing to run without a data source. Pass --from-db (prod needs CMD approval).")
        return 2

    rows = asyncio.run(_fetch_rows())
    if not rows:
        print("No settled open_to_close rows found — nothing to compare.")
        return 0

    if args.holdout:
        report = evaluate_holdout(rows)
    else:
        scorer = StrategyScorer.from_file(args.weights)
        report = compare(rows, scorer)
    print(format_report(report))
    print()
    print(format_ev_report(report))
    return 0


if __name__ == "__main__":  # pragma: no cover — manual / CI invocation
    raise SystemExit(main())


__all__ = [
    "CellAB",
    "ABReport",
    "compare",
    "evaluate_holdout",
    "format_report",
    "format_ev_report",
    "main",
]
