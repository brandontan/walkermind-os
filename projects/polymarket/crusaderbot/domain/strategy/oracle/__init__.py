"""Chainlink BTC/USD oracle layer (WARP-62, Chunk 1/4 — foundation).

Public surface for the candle edge engine. Chunk 1 ships only the price read +
candle-open capture; fair-value calc and strategy wiring land in later chunks.
"""
from __future__ import annotations

from .chainlink import (
    ChainlinkDataStreamsClient,
    OracleConfigError,
    OracleDisabledError,
    OracleError,
    OracleUnavailableError,
    build_hmac_signature,
    client_from_settings,
    decode_benchmark_price,
    get_btc_price,
)
from .price_to_beat import get_price_to_beat

__all__ = [
    "ChainlinkDataStreamsClient",
    "OracleError",
    "OracleConfigError",
    "OracleDisabledError",
    "OracleUnavailableError",
    "build_hmac_signature",
    "client_from_settings",
    "decode_benchmark_price",
    "get_btc_price",
    "get_price_to_beat",
]
