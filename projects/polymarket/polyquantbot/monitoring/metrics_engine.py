"""Phase 24 — MetricsEngine for rolling validation metrics."""
from __future__ import annotations

from typing import Any


class MetricsEngine:
    """Compute validation metrics from recent closed trades."""

    @staticmethod
    def compute_win_rate(trades: list[dict[str, Any]]) -> float:
        if not trades:
            return 0.0
        wins = sum(1 for t in trades if float(t.get("pnl", 0.0)) > 0.0)
        return wins / len(trades)

    @staticmethod
    def compute_profit_factor(trades: list[dict[str, Any]]) -> float:
        gross_profit = sum(float(t.get("pnl", 0.0)) for t in trades if float(t.get("pnl", 0.0)) > 0.0)
        gross_loss = sum(-float(t.get("pnl", 0.0)) for t in trades if float(t.get("pnl", 0.0)) < 0.0)

        if gross_loss == 0.0:
            return 999.0 if gross_profit > 0.0 else 0.0
        return gross_profit / gross_loss

    @staticmethod
    def compute_expectancy(trades: list[dict[str, Any]]) -> float:
        if not trades:
            return 0.0

        wins = [float(t.get("pnl", 0.0)) for t in trades if float(t.get("pnl", 0.0)) > 0.0]
        losses = [-float(t.get("pnl", 0.0)) for t in trades if float(t.get("pnl", 0.0)) < 0.0]
        win_rate = len(wins) / len(trades)

        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        return (win_rate * avg_win) - ((1.0 - win_rate) * avg_loss)

    @staticmethod
    def compute_drawdown(equity_curve: list[float]) -> float:
        if len(equity_curve) < 2:
            return 0.0

        peak = equity_curve[0]
        max_drawdown = 0.0

        for value in equity_curve:
            if value > peak:
                peak = value
            if peak > 0.0:
                drawdown = (peak - value) / peak
                if drawdown > max_drawdown:
                    max_drawdown = drawdown

        return max_drawdown

    def compute(self, trades: list[dict[str, Any]]) -> dict[str, float]:
        equity_curve = []
        running = 0.0
        for trade in trades:
            running += float(trade.get("pnl", 0.0))
            equity_curve.append(running)

        return {
            "win_rate": self.compute_win_rate(trades),
            "profit_factor": self.compute_profit_factor(trades),
            "expectancy": self.compute_expectancy(trades),
            "max_drawdown": self.compute_drawdown(equity_curve),
            "last_pnl": float(trades[-1].get("pnl", 0.0)) if trades else 0.0,
            "trade_count": len(trades),
        }
