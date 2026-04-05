from dataclasses import dataclass
from typing import List, Dict, Optional
import time
import structlog

log = structlog.get_logger(__name__)


@dataclass
class TradeRecord:
    position_id: str
    entry_price: float
    exit_price: float
    pnl: float
    duration: float


class PerformanceTracker:
    def __init__(self):
        self._trades: List[TradeRecord] = []
        self._equity_curve: List[float] = []

    def record_trade(self, position: Dict) -> None:
        """Store trade details, prevent duplicates and handle edge cases."""
        if not position.get("position_id"):
            log.warning("analytics_skip", reason="missing_position_id")
            return
        if position.get("size", 0) <= 0:
            log.warning("analytics_skip", reason="size_zero_or_negative")
            return
        if any(t.position_id == position["position_id"] for t in self._trades):
            return  # Skip duplicates
        self._trades.append(
            TradeRecord(
                position_id=position["position_id"],
                entry_price=position["entry_price"],
                exit_price=position.get("current_price", position["entry_price"]),
                pnl=position["pnl"],
                duration=time.time() - getattr(position, "created_at", time.time()),
            )
        )
        self._update_equity_curve(position["pnl"])

    def _update_equity_curve(self, pnl: float):
        """Track equity for drawdown calculation."""
        self._equity_curve.append(self._equity_curve[-1] + pnl if self._equity_curve else pnl)

    def summary(self) -> Dict:
        """Return performance metrics."""
        if not self._trades:
            return {
                "trades": 0,
                "win_rate": 0.0,
                "avg_pnl": 0.0,
                "max_drawdown": 0.0,
                "sharpe": 0.0,
            }
        wins = sum(1 for t in self._trades if t.pnl > 0)
        peak = max(self._equity_curve)
        trough = min(self._equity_curve)
        drawdown = (peak - trough) / peak if peak > 0 else 0
        return {
            "trades": len(self._trades),
            "win_rate": wins / len(self._trades),
            "avg_pnl": sum(t.pnl for t in self._trades) / len(self._trades),
            "max_drawdown": drawdown,
            "sharpe": self._calculate_sharpe(),
        }

    def _calculate_sharpe(self) -> float:
        """Placeholder for Sharpe ratio."""
        return 0.0

    def reconcile(self, trace_engine: TradeTraceEngine) -> bool:
        """Verify analytics match trace data."""
        trace_pnl = sum(t.pnl for t in trace_engine.get_traces())
        analytics_pnl = sum(t.pnl for t in self._trades)
        if abs(trace_pnl - analytics_pnl) > 1e-6:
            raise ValueError(f"Reconciliation failed: trace_pnl={trace_pnl}, analytics_pnl={analytics_pnl}")
        return True