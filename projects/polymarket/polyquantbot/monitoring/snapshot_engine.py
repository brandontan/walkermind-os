"""monitoring.snapshot_engine — safe periodic validation snapshot builder."""

from __future__ import annotations

from typing import Any


class SnapshotEngine:
    """Builds read-only system snapshots from validation metrics.

    This class is intentionally defensive:
    - provides safe defaults for all keys
    - tolerates missing/non-numeric values
    - never raises exceptions to callers
    """

    def _to_int(self, value: Any, default: int = 0) -> int:
        """Best-effort integer conversion with safe fallback."""
        try:
            if value is None:
                return default
            return int(float(value))
        except (TypeError, ValueError):
            return default

    def _to_float(self, value: Any, default: float = 0.0) -> float:
        """Best-effort float conversion with safe fallback."""
        try:
            if value is None:
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def build_snapshot(self, metrics: dict[str, Any], state: str) -> dict[str, Any]:
        """Return periodic validation snapshot payload with safe defaults."""
        try:
            _metrics = metrics if isinstance(metrics, dict) else {}
            return {
                "trade_count": self._to_int(_metrics.get("trade_count", 0), 0),
                "win_rate": self._to_float(_metrics.get("win_rate", 0.0), 0.0),
                "profit_factor": self._to_float(_metrics.get("profit_factor", 0.0), 0.0),
                "drawdown": self._to_float(_metrics.get("max_drawdown", 0.0), 0.0),
                "state": str(state) if state is not None else "UNKNOWN",
                "last_pnl": self._to_float(_metrics.get("last_pnl", 0.0), 0.0),
            }
        except Exception:
            return {
                "trade_count": 0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "drawdown": 0.0,
                "state": str(state) if state is not None else "UNKNOWN",
                "last_pnl": 0.0,
            }
