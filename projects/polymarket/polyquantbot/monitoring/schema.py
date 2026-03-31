"""Observability layer — Metrics schema.

Defines the canonical structure for the live metrics snapshot exposed by the
observability API server.  All fields use ``Optional`` to allow graceful
degradation when a source module is not yet available.

Schema::

    {
        "latency_p95_ms":         float | null,
        "avg_slippage_bps":       float | null,
        "fill_rate":              float | null,
        "execution_success_rate": float | null,
        "drawdown_pct":           float | null,
        "system_state":           "RUNNING" | "PAUSED" | "HALTED",
        "snapshot_ts":            float          # Unix timestamp (UTC)
    }
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Optional


class SystemState(str, Enum):
    """Top-level system operating state derived from RiskGuard."""

    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    HALTED = "HALTED"


@dataclass
class MetricsSnapshot:
    """Live metrics snapshot consumed by the HTTP /metrics endpoint.

    Attributes:
        latency_p95_ms: 95th-percentile execution latency in milliseconds.
                        ``None`` when no latency samples are available.
        avg_slippage_bps: Mean fill slippage in basis points.
                          ``None`` when no fill data is available.
        fill_rate: Fraction of submitted orders that were filled (0–1).
                   ``None`` when no order data is available.
        execution_success_rate: Fraction of submitted orders that reached a
                                terminal FILLED/PARTIAL state (0–1).
                                ``None`` when no order data is available.
        drawdown_pct: Current maximum peak-to-trough drawdown as a percentage
                      (e.g. 3.5 means 3.5%).  ``None`` when no PnL data
                      is available.
        system_state: High-level system state derived from RiskGuard.
        snapshot_ts: Unix timestamp (UTC) when this snapshot was taken.
    """

    latency_p95_ms: Optional[float]
    avg_slippage_bps: Optional[float]
    fill_rate: Optional[float]
    execution_success_rate: Optional[float]
    drawdown_pct: Optional[float]
    system_state: SystemState
    snapshot_ts: float

    def to_dict(self) -> dict:
        """Serialise to a JSON-safe dictionary.

        Returns:
            Plain dict suitable for ``json.dumps``.
        """
        raw = asdict(self)
        raw["system_state"] = self.system_state.value
        return raw
