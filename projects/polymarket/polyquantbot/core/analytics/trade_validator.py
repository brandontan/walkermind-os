from __future__ import annotations

from typing import Any


class TradeValidator:
    """Validates realized outcomes against expected edge after trade close."""

    def validate_closed_trade(
        self,
        *,
        trade_id: str,
        expected_edge: float,
        entry_price: float,
        exit_price: float,
        side: str,
        execution_data: dict[str, Any],
    ) -> dict[str, Any]:
        entry = max(float(entry_price), 1e-9)
        raw_return = (float(exit_price) - entry) / entry
        direction = 1.0 if str(side).upper() == "YES" else -1.0
        actual_return = raw_return * direction
        expected = max(float(expected_edge), 0.0)
        edge_captured = (actual_return / expected) if expected > 0.0 else 0.0
        return {
            "trade_id": trade_id,
            "expected_edge": round(expected, 6),
            "actual_return": round(actual_return, 6),
            "edge_captured": round(edge_captured, 6),
            "execution_degradation": edge_captured < 0.5,
            "execution_data": dict(execution_data),
        }
