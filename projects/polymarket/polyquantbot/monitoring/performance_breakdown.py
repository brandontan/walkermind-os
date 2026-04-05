"""monitoring.performance_breakdown — grouped closed-trade edge analytics."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


class PerformanceBreakdown:
    """Compute grouped edge metrics by market type, signal, and edge bucket."""

    _EMPTY: dict[str, dict[str, dict[str, float | int | str]]] = {
        "by_market": {},
        "by_signal": {},
        "by_edge": {},
    }

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

    def _is_closed_trade(self, trade: dict[str, Any]) -> bool:
        """Return True only for explicitly closed trades."""
        return self._normalize_label(trade.get("status"), default="").lower() == "closed"

    def _is_valid_trade(self, trade: Any) -> bool:
        """Require dict shape + required grouping and pnl fields."""
        if not isinstance(trade, dict):
            return False
        required = ("status", "pnl", "market_type", "signal", "edge")
        return all(key in trade for key in required)

    def _safe_profit_factor(self, total_profit: float, total_loss_abs: float) -> float:
        """Return PF with divide-safe behavior for all-win groups."""
        if total_loss_abs == 0.0:
            return total_profit
        return total_profit / total_loss_abs

    def _build_group_metrics(
        self,
        trades: list[dict[str, Any]],
        key: str,
    ) -> dict[str, dict[str, float | int | str]]:
        """Aggregate trade metrics by a single grouping key."""
        buckets: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "trades": 0,
                "wins": 0,
                "losses": 0,
                "total_profit": 0.0,
                "total_loss_abs": 0.0,
                "sum_win": 0.0,
                "sum_loss_abs": 0.0,
            }
        )

        for trade in trades:
            label = self._normalize_label(trade.get(key))
            pnl = self._to_float(trade.get("pnl"), 0.0)
            b = buckets[label]
            b["trades"] += 1
            if pnl > 0.0:
                b["wins"] += 1
                b["total_profit"] += pnl
                b["sum_win"] += pnl
            elif pnl < 0.0:
                b["losses"] += 1
                loss_abs = abs(pnl)
                b["total_loss_abs"] += loss_abs
                b["sum_loss_abs"] += loss_abs

        output: dict[str, dict[str, float | int | str]] = {}
        for label, b in buckets.items():
            trades_count = int(b["trades"])
            if trades_count == 0:
                continue

            wins = int(b["wins"])
            losses = int(b["losses"])
            win_rate = wins / trades_count
            total_profit = float(b["total_profit"])
            total_loss_abs = float(b["total_loss_abs"])
            avg_win = total_profit / wins if wins > 0 else 0.0
            avg_loss = float(b["sum_loss_abs"]) / losses if losses > 0 else 0.0
            expectancy = (avg_win * win_rate) - (avg_loss * (1.0 - win_rate))

            output[label] = {
                "trades": trades_count,
                "wins": wins,
                "losses": losses,
                "win_rate": win_rate,
                "profit_factor": self._safe_profit_factor(total_profit, total_loss_abs),
                "avg_win": avg_win,
                "avg_loss": avg_loss,
                "expectancy": expectancy,
                "quality": "OK" if trades_count >= 10 else "LOW_SAMPLE",
            }
        return output

    def analyze(self, trades: list[dict[str, Any]] | None) -> dict[str, dict[str, dict[str, float | int | str]]]:
        """Return grouped performance from closed trades only."""
        safe_trades = [t for t in (trades or []) if self._is_valid_trade(t)]
        valid_trades = [t for t in safe_trades if self._is_closed_trade(t)]

        if not valid_trades:
            return dict(self._EMPTY)

        return {
            "by_market": self._build_group_metrics(valid_trades, "market_type"),
            "by_signal": self._build_group_metrics(valid_trades, "signal"),
            "by_edge": self._build_group_metrics(valid_trades, "edge"),
        }
