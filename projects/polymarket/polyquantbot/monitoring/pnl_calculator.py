"""monitoring.pnl_calculator — Realized / unrealized PnL and performance metrics.

Provides a stateless :class:`PnLCalculator` with three static methods:

    ``calculate_realized_pnl``  — sum of settled trade PnL.
    ``calculate_unrealized_pnl`` — mark-to-market estimate using current prices.
    ``calculate_metrics``       — aggregated total_pnl, win_rate, drawdown.

All methods are pure functions over plain dicts — no database calls.  Callers
are responsible for fetching the necessary trade and position data.

Trade dict expected keys:
    ``pnl``     — realised PnL for the trade (float, positive = profit).
    ``won``     — boolean outcome; if absent, inferred from ``pnl > 0``.

Position dict expected keys:
    ``market_id``  — Polymarket condition ID.
    ``avg_price``  — weighted-average fill price.
    ``size``       — current open size in USD.

Usage::

    from monitoring.pnl_calculator import PnLCalculator

    realized = PnLCalculator.calculate_realized_pnl(trades)
    unrealized = PnLCalculator.calculate_unrealized_pnl(positions, current_prices)
    metrics = PnLCalculator.calculate_metrics(trades)
    print(metrics["win_rate"], metrics["drawdown"])
"""
from __future__ import annotations

from typing import Dict, List

import structlog

log = structlog.get_logger(__name__)


class PnLCalculator:
    """Stateless PnL computation helpers.

    All methods are static — instantiation is not required.
    """

    @staticmethod
    def calculate_realized_pnl(trades: List[Dict]) -> float:
        """Sum realised PnL across all completed trades.

        Args:
            trades: List of trade dicts; each must contain a ``pnl`` key.

        Returns:
            Total realised PnL as a float.
        """
        total = sum(float(t.get("pnl", 0.0)) for t in trades)
        log.debug("pnl_realized_calculated", total_pnl=round(total, 6), n_trades=len(trades))
        return round(total, 6)

    @staticmethod
    def calculate_unrealized_pnl(
        positions: List[Dict],
        current_prices: Dict[str, float],
    ) -> float:
        """Estimate mark-to-market PnL for open positions.

        For each position the unrealised PnL is:
            ``(current_price - avg_price) × size``

        When a market has no entry in *current_prices* the position is
        marked at its own ``avg_price`` (zero unrealised PnL).

        Args:
            positions: List of position dicts with ``market_id``,
                       ``avg_price``, and ``size``.
            current_prices: Mapping from market_id to current market price.

        Returns:
            Total unrealised PnL as a float.
        """
        total = 0.0
        for pos in positions:
            market_id = str(pos.get("market_id", ""))
            avg_price = float(pos.get("avg_price", 0.0))
            size = float(pos.get("size", 0.0))
            current_price = current_prices.get(market_id, avg_price)
            unrealized = (current_price - avg_price) * size
            total += unrealized

        log.debug(
            "pnl_unrealized_calculated",
            total_unrealized=round(total, 6),
            n_positions=len(positions),
        )
        return round(total, 6)

    @staticmethod
    def calculate_metrics(trades: List[Dict]) -> Dict:
        """Compute performance metrics from a list of trade records.

        Computes:
            ``total_pnl``    — sum of all pnl values.
            ``win_rate``     — fraction of winning trades.
            ``drawdown``     — maximum drawdown fraction from peak equity.
            ``total_trades`` — number of trades processed.
            ``wins``         — count of profitable trades.
            ``losses``       — count of unprofitable trades.

        Drawdown is computed over the equity curve
        (running sum of pnl values in trade order).

        Args:
            trades: List of trade dicts ordered by execution time.

        Returns:
            Dict with keys: total_pnl, win_rate, drawdown,
                            total_trades, wins, losses.
        """
        if not trades:
            return {
                "total_pnl": 0.0,
                "win_rate": 0.0,
                "drawdown": 0.0,
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
            }

        total_pnl = 0.0
        wins = 0
        losses = 0
        running_pnl = 0.0
        peak = 0.0
        max_drawdown = 0.0

        for trade in trades:
            pnl = float(trade.get("pnl", 0.0))
            total_pnl += pnl
            running_pnl += pnl

            # Track peak equity for drawdown calculation
            if running_pnl > peak:
                peak = running_pnl

            if peak > 0:
                dd = (peak - running_pnl) / peak
                if dd > max_drawdown:
                    max_drawdown = dd

            # Determine win/loss (use explicit `won` flag when available)
            won_flag = trade.get("won")
            if won_flag is not None:
                if won_flag:
                    wins += 1
                else:
                    losses += 1
            elif pnl > 0:
                wins += 1
            else:
                losses += 1

        total_trades = len(trades)
        win_rate = wins / total_trades if total_trades > 0 else 0.0

        result = {
            "total_pnl": round(total_pnl, 6),
            "win_rate": round(win_rate, 4),
            "drawdown": round(max_drawdown, 4),
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
        }

        log.info(
            "pnl_metrics_calculated",
            total_pnl=result["total_pnl"],
            win_rate=result["win_rate"],
            drawdown=result["drawdown"],
            total_trades=total_trades,
        )
        return result
