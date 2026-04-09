from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class ExecutionTracker:
    """Captures expected vs actual execution truth without changing execution behavior."""

    def __init__(self) -> None:
        self._records: dict[str, dict[str, Any]] = {}

    def record_order_submission(
        self,
        *,
        trade_id: str,
        expected_price: float,
        signal_data: dict[str, Any],
        decision_data: dict[str, Any],
        order_timestamp: datetime | None = None,
    ) -> None:
        now = order_timestamp or datetime.now(timezone.utc)
        self._records[trade_id] = {
            "trade_id": trade_id,
            "expected_price": float(expected_price),
            "actual_fill_price": None,
            "slippage": None,
            "order_timestamp": now.isoformat(),
            "fill_timestamp": None,
            "latency_ms": None,
            "signal_data": dict(signal_data),
            "decision_data": dict(decision_data),
        }

    def record_fill(
        self,
        *,
        trade_id: str,
        actual_fill_price: float,
        fill_timestamp: datetime | None = None,
    ) -> dict[str, Any]:
        record = self._records.get(trade_id)
        if record is None:
            raise ValueError(f"missing execution record for trade_id={trade_id}")
        fill_ts = fill_timestamp or datetime.now(timezone.utc)
        order_ts = datetime.fromisoformat(str(record["order_timestamp"]))
        slippage = float(actual_fill_price) - float(record["expected_price"])
        latency_ms = max((fill_ts - order_ts).total_seconds() * 1000.0, 0.0)
        record["actual_fill_price"] = float(actual_fill_price)
        record["slippage"] = round(slippage, 6)
        record["fill_timestamp"] = fill_ts.isoformat()
        record["latency_ms"] = round(latency_ms, 3)
        return dict(record)

    def get_execution_data(self, trade_id: str) -> dict[str, Any]:
        record = self._records.get(trade_id)
        if record is None:
            raise ValueError(f"missing execution record for trade_id={trade_id}")
        return dict(record)
