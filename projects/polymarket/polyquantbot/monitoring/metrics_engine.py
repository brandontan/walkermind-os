"""Phase 24 — MetricsEngine: Core trading-performance metric computations.

Computes:
    win_rate        — WR  = winning_trades / total_trades
    profit_factor   — PF  = gross_profit / gross_loss
    expectancy      — E   = (WR × avg_win) − ((1 − WR) × avg_loss)
    max_drawdown    — MDD = (peak − trough) / peak  on the equity curve

Rules:
    - Divide-by-zero handled safely; returns 0.0 rather than NaN/inf.
    - No NaN outputs allowed — every return value is a finite float.
    - Empty trade list returns neutral zero-valued metrics dict.
"""
from __future__ import annotations

from typing import Any

import structlog

log = structlog.get_logger()


class MetricsEngine:
    """Stateless metric computation helper.

    All methods accept a ``trades`` list of dicts containing at least the
    ``pnl`` key.  No internal state is stored between calls.
    """

    # ── Primitive computations ────────────────────────────────────────────────

    @staticmethod
    def compute_win_rate(trades: list[dict[str, Any]]) -> float:
        """Return the fraction of trades with pnl > 0.

        Args:
            trades: List of trade dicts, each with a ``pnl`` key.

        Returns:
            Float in [0.0, 1.0].  Returns 0.0 when ``trades`` is empty.
        """
        if not trades:
            return 0.0
        wins = sum(1 for t in trades if t.get("pnl", 0.0) > 0.0)
        return wins / len(trades)

    @staticmethod
    def compute_profit_factor(trades: list[dict[str, Any]]) -> float:
        """Return gross_profit / gross_loss.

        Args:
            trades: List of trade dicts with a ``pnl`` key.

        Returns:
            Float ≥ 0.  Returns 0.0 when there are no trades or all trades
            are breakeven (both gross_profit and gross_loss are zero).
            Returns 999.0 as a large-but-finite sentinel value when
            gross_loss is zero but gross_profit > 0 (all-win window) — this
            prevents a false ValidationEngine WARNING on a perfect system.
        """
        if not trades:
            return 0.0
        gross_profit = sum(t.get("pnl", 0.0) for t in trades if t.get("pnl", 0.0) > 0.0)
        gross_loss = abs(sum(t.get("pnl", 0.0) for t in trades if t.get("pnl", 0.0) < 0.0))
        if gross_loss == 0.0:
            # All-win window: return large finite sentinel to avoid false WARNING
            if gross_profit > 0.0:
                return 999.0
            # No trades with any PnL (all breakeven or empty after filter)
            return 0.0
        return gross_profit / gross_loss

    @staticmethod
    def compute_expectancy(trades: list[dict[str, Any]]) -> float:
        """Return E = (WR × avg_win) − ((1 − WR) × avg_loss).

        Args:
            trades: List of trade dicts with a ``pnl`` key.

        Returns:
            Float (may be negative).  Returns 0.0 for empty input.
        """
        if not trades:
            return 0.0

        wins = [t.get("pnl", 0.0) for t in trades if t.get("pnl", 0.0) > 0.0]
        losses = [abs(t.get("pnl", 0.0)) for t in trades if t.get("pnl", 0.0) < 0.0]

        wr = len(wins) / len(trades)
        avg_win = (sum(wins) / len(wins)) if wins else 0.0
        avg_loss = (sum(losses) / len(losses)) if losses else 0.0

        return (wr * avg_win) - ((1.0 - wr) * avg_loss)

    @staticmethod
    def build_equity_curve(trades: list[dict[str, Any]]) -> list[float]:
        """Return a cumulative PnL curve starting at 0.

        Args:
            trades: List of trade dicts with a ``pnl`` key (ordered oldest→newest).

        Returns:
            List of cumulative PnL values with length ``len(trades) + 1``.
            The first element is always 0.0.
        """
        curve: list[float] = [0.0]
        running = 0.0
        for t in trades:
            running += t.get("pnl", 0.0)
            curve.append(running)
        return curve

    @staticmethod
    def compute_drawdown(equity_curve: list[float]) -> float:
        """Return the maximum peak-to-trough drawdown fraction.

        MDD = (peak − trough) / peak   (absolute peak value used for normalisation).

        Args:
            equity_curve: Ordered sequence of cumulative PnL values.

        Returns:
            Float in [0.0, 1.0].  Returns 0.0 when the curve is empty, has a
            single point, or when the running peak is ≤ 0 throughout (avoids
            divide-by-zero on a flat/negative curve).
        """
        if len(equity_curve) < 2:
            return 0.0

        peak = equity_curve[0]
        max_dd = 0.0

        for value in equity_curve[1:]:
            if value > peak:
                peak = value
            if peak > 0.0:
                dd = (peak - value) / peak
                if dd > max_dd:
                    max_dd = dd

        return max_dd

    # ── Composite ────────────────────────────────────────────────────────────

    def compute(self, trades: list[dict[str, Any]]) -> dict[str, float]:
        """Compute all metrics from a trade list.

        Args:
            trades: List of trade dicts with at minimum a ``pnl`` key.

        Returns:
            Dict with keys: ``win_rate``, ``profit_factor``, ``expectancy``,
            ``max_drawdown``, ``last_pnl``.  All values are finite floats.
            ``last_pnl`` is the PnL of the most recent trade, or 0.0 when
            the trade list is empty.
        """
        equity_curve = self.build_equity_curve(trades)
        last_pnl: float = trades[-1].get("pnl", 0.0) if trades else 0.0
        metrics: dict[str, float] = {
            "win_rate": self.compute_win_rate(trades),
            "profit_factor": self.compute_profit_factor(trades),
            "expectancy": self.compute_expectancy(trades),
            "max_drawdown": self.compute_drawdown(equity_curve),
            "last_pnl": last_pnl,
        }

        log.debug(
            "metrics_engine_computed",
            trade_count=len(trades),
            **{k: round(v, 6) for k, v in metrics.items()},
        )
        return metrics
