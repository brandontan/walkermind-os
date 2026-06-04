"""Multi-asset crypto oracle layer (WARP-62, Chunk 1/4 — foundation).

Public surface for the candle edge engine. Chunk 1 ships only the live price
stream (BTC/ETH/SOL via Polymarket RTDS, keyed by symbol) + candle-open capture;
fair-value calc and strategy wiring land in later chunks.
"""
from __future__ import annotations

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
    "PolymarketRTDSOracle",
    "OracleError",
    "OracleConfigError",
    "OracleDisabledError",
    "oracle_from_settings",
    "normalize_symbol",
    "parse_symbols",
    "get_price_to_beat",
]
