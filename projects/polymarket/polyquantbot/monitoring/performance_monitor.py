import json
from dataclasses import dataclass
from typing import List, Dict, Optional
import time
import structlog

log = structlog.get_logger(__name__)


@dataclass
class PerformanceSnapshot:
    total_trades: int
    win_rate: float
    avg_pnl: float
    total_pnl: float
    max_drawdown: float
    equity_curve: List[float]
    timestamp: str


class PerformanceMonitor:
    def __init__(self):
        self._history: List[PerformanceSnapshot] = []
        self._alert_thresholds = {
            "drawdown": -0.05,  # 5%
            "win_rate_drop": 0.2,  # 20%
            "consecutive_losses": 3
        }

    def update(self, snapshot: PerformanceSnapshot) -> None:
        """Update performance history."""
        self._history.append(snapshot)
        self._check_alerts(snapshot)

    def _check_alerts(self, snapshot: PerformanceSnapshot) -> None:
        """Check for alert conditions."""
        if snapshot.max_drawdown < self._alert_thresholds["drawdown"]:
            log.warning("alert_drawdown_exceeded", drawdown=snapshot.max_drawdown)
        if len(self._history) > 1:
            prev = self._history[-2]
            if snapshot.win_rate < prev.win_rate - self._alert_thresholds["win_rate_drop"]:
                log.warning("alert_win_rate_drop", current=snapshot.win_rate, previous=prev.win_rate)

    def daily_summary(self) -> Dict:
        """Generate daily summary."""
        if not self._history:
            return {}
        latest = self._history[-1]
        return {
            "trades": latest.total_trades,
            "win_rate": f"{latest.win_rate:.2%}",
            "total_pnl": f"${latest.total_pnl:,.2f}",
            "drawdown": f"{latest.max_drawdown:.2%}"
        }

    def save_history(self, file_path: str) -> None:
        """Save performance history to JSON."""
        with open(file_path, "w") as f:
            json.dump([s.__dict__ for s in self._history], f, indent=2)

    def detect_anomalies(self) -> List[str]:
        """Detect anomalies in performance."""
        anomalies = []
        if len(self._history) < 2:
            return anomalies
        current = self._history[-1]
        previous = self._history[-2]
        if abs(current.total_pnl - previous.total_pnl) > 1000:  # Example threshold
            anomalies.append("Sudden PnL change detected")
        if current.total_trades - previous.total_trades > 10:  # Example threshold
            anomalies.append("Unusual trade frequency detected")
        return anomalies