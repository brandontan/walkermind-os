"""TP/SL calibration backtest — WARP-83 Sub-Lane E.1 (report-only).

Backtests the CrusaderBot paper trade history (mode='paper', strategy
late_entry_v3) against hypothetical Take-Profit / Stop-Loss bundles and
quantifies per-bundle Expected EV per trade, win rate, max drawdown and a
Sharpe-equivalent (mean / stdev of per-trade return on stake).

Semantics of tp_pct / sl_pct (verified against the live data + strategy code):
  These are RETURN-ON-STAKE thresholds, NOT price-move fractions.
    tp_pct = 1.5  ->  exit when unrealised PnL reaches +150% of stake.
    sl_pct = 0.5  ->  exit when unrealised PnL reaches -50% of stake.
  The realized cohort ran tp_pct=1.5 / sl_pct=0.5 on 1386 / 1437 rows, i.e.
  the task's "Balanced" bundle == the realized live policy.

Methodology + limitation (READ THIS):
  The `positions` table stores only entry_price and the realized exit
  (exit_reason + pnl_usdc). There is NO stored intra-trade price path and NO
  per-trade MFE/MAE excursion table (confirmed: no price/tick/candle/excursion
  table exists; strategy_metadata has no peak fields). A true counterfactual
  re-simulation of a *different* TP/SL is therefore impossible from this data.

  What IS recoverable is a *bounded* counterfactual using monotonic path
  reasoning anchored on the realized exit:
    - A trade that exited via `tp_hit` (+1.5) provably crossed every threshold
      below +1.5 on the way up  -> a TIGHTER TP (e.g. +0.6) is a CERTAIN hit.
    - A trade that exited via `sl_hit` (-0.5) provably crossed every threshold
      above -0.5 on the way down -> a TIGHTER SL (e.g. -0.3) is a CERTAIN hit.
    - A LOOSER SL (e.g. -0.75) on an sl_hit trade, or a HIGHER TP (e.g. +2.5)
      on a tp_hit trade, is UNKNOWABLE without the price path -> we report an
      explicit optimistic / pessimistic BOUND, never a single point estimate.

  Conclusions that rely ONLY on tighter thresholds (Conservative 60/30, and any
  SL=0.5 TP-variation) are CERTAIN point estimates with no path uncertainty.
  The Aggressive bundle (looser SL + higher TP) is genuinely bounded.

This script re-derives every number quoted in
  reports/forge/risk-profile-tpsl-calibration.md
directly from Supabase so the analysis is reproducible. It is a research/report
tool only: it does NOT import or touch any strategy, risk, ev_comparator,
scorer or orchestrator runtime path, and it changes no strategy default.

Run (read-only):
  DATABASE_URL=... python -m crusaderbot.scripts.tpsl_calibration_backtest
"""

from __future__ import annotations

import asyncio
import os
import statistics
from dataclasses import dataclass, field
from typing import Final

try:
    import asyncpg  # type: ignore
except ImportError:  # pragma: no cover - asyncpg always present in prod
    asyncpg = None  # type: ignore[assignment]

# Cohort filter: settled paper trades on real data (mode='paper'; the live
# late_entry_v3 cohort recorded under data_source semantics of paper_real).
_COHORT_SQL: Final[str] = (
    "SELECT opened_at, size_usdc, pnl_usdc, exit_reason "
    "FROM positions "
    "WHERE mode = 'paper' AND size_usdc > 0 AND pnl_usdc IS NOT NULL "
    "ORDER BY opened_at ASC"
)


@dataclass(frozen=True)
class Trade:
    """One settled paper position, reduced to backtest inputs."""

    opened_at: object
    size_usdc: float
    realized_return: float  # pnl_usdc / size_usdc (return on stake)
    exit_reason: str | None


@dataclass(frozen=True)
class Bundle:
    """A candidate TP/SL bundle in return-on-stake units."""

    name: str
    tp: float  # take-profit threshold, e.g. 1.5 == +150% of stake
    sl: float  # stop-loss threshold (positive magnitude), e.g. 0.5 == -50%


@dataclass
class BundleResult:
    """Backtest metrics for one bundle (a scenario = optimistic|pessimistic|certain)."""

    bundle: str
    scenario: str
    n: int
    ev_per_trade: float
    win_rate_pct: float
    max_drawdown_usdc: float
    sharpe_equiv: float | None
    sharpe_note: str = ""
    per_trade_returns: list[float] = field(default_factory=list)


# Required bundles (task-specified, in return-on-stake units).
CONSERVATIVE: Final[Bundle] = Bundle("Conservative", tp=0.60, sl=0.30)
BALANCED: Final[Bundle] = Bundle("Balanced", tp=1.50, sl=0.50)  # realized policy
AGGRESSIVE: Final[Bundle] = Bundle("Aggressive", tp=2.50, sl=0.75)


def counterfactual_return(
    trade: Trade, bundle: Bundle, *, optimistic: bool
) -> float:
    """Map a realized trade onto a candidate bundle's return on stake.

    `optimistic` only affects trades whose counterfactual is UNKNOWABLE
    (higher-TP on a tp_hit, or looser-SL on an sl_hit). For all certain cases
    the two scenarios coincide.
    """
    r = trade.realized_return
    reason = trade.exit_reason
    tp, sl = bundle.tp, bundle.sl

    # --- Take-profit side ---------------------------------------------------
    if reason == "tp_hit":
        # Price provably reached +1.5 (the realized TP) and overshot to r.
        if tp <= 1.5:
            # Tighter/equal TP: certain hit at +tp (price crossed it earlier).
            return tp
        # Higher TP than realized: unknown if it continued past +1.5.
        if r >= tp:
            return tp  # already overshot beyond the higher TP -> locks +tp
        # pessimistic: assume reversed after +1.5, keep realized overshoot r.
        # optimistic: assume continued up to +tp.
        return max(r, tp) if optimistic else r

    # --- Stop-loss side -----------------------------------------------------
    if reason == "sl_hit":
        # Price provably reached -0.5 (the realized SL).
        if sl <= 0.5:
            # Tighter/equal SL: certain hit at -sl (price crossed it earlier).
            return -sl
        # Looser SL than realized: unknown if it recovered or sank further.
        if optimistic:
            return tp  # assume it recovered all the way to take-profit
        return -sl  # assume it sank to the looser stop

    # --- Trades that never hit TP/SL under the realized policy --------------
    # (resolution_win / resolution_loss / strategy_exit / market_expired)
    # A tighter SL or TP could now trigger mid-path, but we lack the path.
    # Apply the deterministic threshold crossings we CAN prove from the
    # realized endpoint r; otherwise keep r (held to the same end).
    if r >= tp:
        return tp
    if r <= -sl:
        return -sl
    return r


def max_drawdown_usdc(per_trade_pnl: list[float]) -> float:
    """Peak-to-trough max drawdown ($) on the cumulative equity curve."""
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for pnl in per_trade_pnl:
        equity += pnl
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return worst


def evaluate(
    trades: list[Trade], bundle: Bundle, *, optimistic: bool, scenario: str
) -> BundleResult:
    returns = [counterfactual_return(t, bundle, optimistic=optimistic) for t in trades]
    pnl = [ret * t.size_usdc for ret, t in zip(returns, trades, strict=True)]
    n = len(returns)
    ev = statistics.fmean(returns) if returns else 0.0
    wins = sum(1 for ret in returns if ret > 0)
    win_rate = 100.0 * wins / n if n else 0.0
    if n >= 2:
        sd = statistics.stdev(returns)
        sharpe: float | None = (ev / sd) if sd > 0 else None
        note = "" if sharpe is not None else "zero variance"
    else:
        sharpe = None
        note = "n<2"
    return BundleResult(
        bundle=bundle.name,
        scenario=scenario,
        n=n,
        ev_per_trade=ev,
        win_rate_pct=win_rate,
        max_drawdown_usdc=max_drawdown_usdc(pnl),
        sharpe_equiv=sharpe,
        sharpe_note=note,
        per_trade_returns=returns,
    )


def run_all(trades: list[Trade]) -> list[BundleResult]:
    """Evaluate every required bundle. Tighter-only bundles report one CERTAIN
    scenario; looser/higher bundles report optimistic + pessimistic bounds."""
    results: list[BundleResult] = []
    # Conservative: tp<=1.5 and sl<=0.5 -> fully certain (no path uncertainty).
    results.append(evaluate(trades, CONSERVATIVE, optimistic=False, scenario="certain"))
    # Balanced: this IS the realized policy -> certain.
    results.append(evaluate(trades, BALANCED, optimistic=False, scenario="certain"))
    # Aggressive: looser SL + higher TP -> genuinely bounded.
    results.append(
        evaluate(trades, AGGRESSIVE, optimistic=False, scenario="pessimistic")
    )
    results.append(
        evaluate(trades, AGGRESSIVE, optimistic=True, scenario="optimistic")
    )
    return results


async def _load_trades() -> list[Trade]:  # pragma: no cover - needs live DB
    if asyncpg is None:
        raise RuntimeError("asyncpg not installed")
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL not set")
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(_COHORT_SQL)
    finally:
        await conn.close()
    return [
        Trade(
            opened_at=row["opened_at"],
            size_usdc=float(row["size_usdc"]),
            realized_return=float(row["pnl_usdc"]) / float(row["size_usdc"]),
            exit_reason=row["exit_reason"],
        )
        for row in rows
    ]


def _format(results: list[BundleResult]) -> str:
    lines = [
        f"{'Bundle':<14}{'Scenario':<13}{'n':>5}{'EV/trade':>10}"
        f"{'Win%':>8}{'MaxDD$':>11}{'Sharpe':>9}",
    ]
    for r in results:
        sharpe = f"{r.sharpe_equiv:.4f}" if r.sharpe_equiv is not None else r.sharpe_note
        lines.append(
            f"{r.bundle:<14}{r.scenario:<13}{r.n:>5}{r.ev_per_trade:>10.4f}"
            f"{r.win_rate_pct:>8.2f}{r.max_drawdown_usdc:>11.2f}{sharpe:>9}"
        )
    return "\n".join(lines)


async def _main() -> None:  # pragma: no cover - CLI entrypoint
    trades = await _load_trades()
    print(f"Loaded {len(trades)} settled paper trades.")
    print(_format(run_all(trades)))


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(_main())
