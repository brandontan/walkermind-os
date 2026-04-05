from dataclasses import dataclass
from typing import List
import time

@dataclass
class TradeRecord:
    entry_price: float
    exit_price: float
    pnl: float
    duration: float

class PerformanceTracker:
    def __init__(self):
        self._trades: List[TradeRecord] = []

    def record_trade(self, position) -> None:
        """Store trade details."""
        self._trades.append(
            TradeRecord(
                entry_price=position.entry_price,
                exit_price=position.current_price,
                pnl=position.pnl,
                duration=time.time() - position.created_at,
            )
        )

    def summary(self) -> dict:
        """Return performance metrics."""
        if not self._trades:
            return {"trades": 0, "win_rate": 0.0, "avg_pnl": 0.0, "max_drawdown": 0.0}
        wins = sum(1 for t in self._trades if t.pnl > 0)
        return {
            "trades": len(self._trades),
            "win_rate": wins / len(self._trades),
            "avg_pnl": sum(t.pnl for t in self._trades) / len(self._trades),
            "max_drawdown": min(t.pnl for t in self._trades),
        }