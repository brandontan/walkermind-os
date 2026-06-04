"""Multi-asset crypto oracle layer for the late_entry_v3 candle strategy (WARP-61).

This package isolates the candle-market edge engine:

* ``rtds`` (WARP-62, Chunk 1) -- multi-asset (BTC/ETH/SOL) live price stream via
  the Polymarket RTDS WebSocket, keyed by symbol, with staleness handling.
* ``price_to_beat`` (WARP-62, Chunk 1) -- pure capture of the candle-open
  "Price to Beat" from Polymarket market metadata.
* ``fair_value`` (WARP-63, Chunk 2) -- pure, I/O-free fair-value / edge math with
  per-asset sigma.
* Strategy wiring (Chunk 3, WARP-64) lands separately.

The pure calculator and the price helpers carry no network/DB dependency; the
RTDS client opens a socket only when started, behind the ORACLE_ENABLED flag.
"""
from __future__ import annotations

from .fair_value import (
    CLOB_MIN_TICK,
    DEFAULT_SIGMA_PER_SQRT_SEC,
    EdgeResult,
    annual_vol_to_sigma,
    compute_delta,
    compute_edge,
    compute_fair_value,
    normal_cdf,
    sigma_for_asset,
)
from .price_to_beat import get_price_to_beat
from .rtds import (
    OracleConfigError,
    OracleDisabledError,
    OracleError,
    PolymarketRTDSOracle,
    normalize_symbol,
    oracle_from_settings,
    parse_symbols,
)

__all__ = [
    # Chunk 1 — RTDS multi-asset price stream + candle-open capture
    "PolymarketRTDSOracle",
    "OracleError",
    "OracleConfigError",
    "OracleDisabledError",
    "oracle_from_settings",
    "normalize_symbol",
    "parse_symbols",
    "get_price_to_beat",
    # Chunk 2 — pure fair-value / edge calculator (per-asset sigma)
    "CLOB_MIN_TICK",
    "DEFAULT_SIGMA_PER_SQRT_SEC",
    "EdgeResult",
    "annual_vol_to_sigma",
    "compute_delta",
    "compute_edge",
    "compute_fair_value",
    "normal_cdf",
    "sigma_for_asset",
]
