"""BTC/USD oracle layer for the late_entry_v3 candle strategy (WARP-61).

This package isolates the candle-market edge engine:

* ``fair_value`` (WARP-63, Chunk 2) -- pure, I/O-free fair-value / edge math.
* Chainlink client (Chunk 1) and strategy wiring (Chunk 3) land separately.

Only the pure calculator is exported here so importers never pull network or
DB dependencies transitively.
"""
from __future__ import annotations

from projects.polymarket.crusaderbot.domain.strategy.oracle.fair_value import (
    CLOB_MIN_TICK,
    EdgeResult,
    annual_vol_to_sigma,
    compute_delta,
    compute_edge,
    compute_fair_value,
    normal_cdf,
)

__all__ = [
    "CLOB_MIN_TICK",
    "EdgeResult",
    "annual_vol_to_sigma",
    "compute_delta",
    "compute_edge",
    "compute_fair_value",
    "normal_cdf",
]
