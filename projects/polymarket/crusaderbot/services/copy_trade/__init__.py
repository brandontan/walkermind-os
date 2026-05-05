"""Copy-trade support services.

Public surface (P3b):
    fetch_recent_wallet_trades       — rate-limited, timeout-bounded poll of
                                       Polymarket Data API trades for a wallet
    fetch_leader_open_condition_ids  — current open condition_ids for a wallet
    scale_size                       — proportional scaling with cap + $1 floor

Foundation contract: these helpers never place orders, never touch the risk
gate, never write to the execution path. They are pure I/O + arithmetic.
"""

from .scaler import MIN_TRADE_SIZE_USDC, mirror_size_direct, scale_size
from .wallet_watcher import (
    GLOBAL_RATE_LIMIT_INTERVAL_SEC,
    POLYMARKET_FETCH_TIMEOUT_SEC,
    fetch_leader_open_condition_ids,
    fetch_recent_wallet_trades,
)

__all__ = [
    "scale_size",
    "mirror_size_direct",
    "MIN_TRADE_SIZE_USDC",
    "fetch_recent_wallet_trades",
    "fetch_leader_open_condition_ids",
    "GLOBAL_RATE_LIMIT_INTERVAL_SEC",
    "POLYMARKET_FETCH_TIMEOUT_SEC",
]
