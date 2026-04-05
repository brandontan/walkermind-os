"""monitoring.performance_breakdown — grouped trade performance analytics."""

from __future__ import annotations

from typing import Any


class PerformanceBreakdown:
    """Compute grouped WR/PF metrics by market type, signal, and edge."""

    def _to_float(self, value: Any, default: float = 0.0) -> float:
        """Best-effort float conversion with safe fallback."""
        try:
            if value is None:
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def _normalize_label(self, value: Any, default: str = "UNKNOWN") -> str:
        """Return a clean upper-case label for grouping keys."""
        if value is None:
            return default
        text = str(value).strip().upper()
        return text or default

    def _safe_profit_factor(self, total_profit: float, total_loss: float) -> float:
        """Return safe PF: profit/loss, or profit when loss is zero."""
        if total_loss == 0.0:
            return total_profit
        return total_profit / total_loss

    def _build_group_metrics(self, trades: list[dict[str, Any]], key: str) -> dict[str, dict[str, float | int]]:
        """Aggregate trade metrics by a single string key."""
        grouped: dict[str, dict[str, float | int]] = {}
        for trade in trades:
            label = self._normalize_label(trade.get(key))
            pnl = self._to_float(trade.get("pnl"), 0.0)

            if label not in grouped:
                grouped[label] = {
                    "trades": 0,
                    "wins": 0,
                    "total_profit": 0.0,
                    "total_loss": 0.0,
                }

            grouped[label]["trades"] = int(grouped[label]["trades"]) + 1
            if pnl > 0.0:
                grouped[label]["wins"] = int(grouped[label]["wins"]) + 1
                grouped[label]["total_profit"] = float(grouped[label]["total_profit"]) + pnl
            elif pnl < 0.0:
                grouped[label]["total_loss"] = float(grouped[label]["total_loss"]) + abs(pnl)

        metrics: dict[str, dict[str, float | int]] = {}
        for label, bucket in grouped.items():
            trades_count = int(bucket["trades"])
            wins = int(bucket["wins"])
            total_profit = float(bucket["total_profit"])
            total_loss = float(bucket["total_loss"])
            win_rate = (wins / trades_count) if trades_count > 0 else 0.0
            metrics[label] = {
                "trades": trades_count,
                "win_rate": win_rate,
                "profit_factor": self._safe_profit_factor(total_profit, total_loss),
            }
        return metrics

    def analyze(self, trades: list[dict[str, Any]] | None) -> dict[str, dict[str, dict[str, float | int]]]:
        """Return grouped breakdown from the rolling trades list.

        Expected trade shape:
            {
              "pnl": float,
              "result": "win" | "loss",
              "market_type": str,
              "signal": str,
              "edge": str
            }
        """
        safe_trades = [t for t in (trades or []) if isinstance(t, dict)]
        if not safe_trades:
            return {
                "by_market": {},
                "by_signal": {},
                "by_edge": {},
            }

        return {
            "by_market": self._build_group_metrics(safe_trades, "market_type"),
            "by_signal": self._build_group_metrics(safe_trades, "signal"),
            "by_edge": self._build_group_metrics(safe_trades, "edge"),
        }
