"""execution.types — Shared order and position type definitions.

Provides dataclasses used across the execution pipeline and Telegram UI
layers to avoid circular imports.

Types:
    OrderInput       — input to the paper engine
    WalletState      — re-exported from core.wallet_engine
    PositionState    — lightweight position snapshot
    LedgerEntry      — re-exported from core.ledger
"""
from __future__ import annotations

from dataclasses import dataclass

# Re-export core types so callers can import from one place
from ..core.wallet_engine import WalletState as WalletState  # noqa: F401
from ..core.ledger import LedgerEntry as LedgerEntry  # noqa: F401


# ── Order input ───────────────────────────────────────────────────────────────


@dataclass
class OrderInput:
    """Input parameters for a paper order execution.

    Attributes:
        market_id: Polymarket condition ID.
        side:      "YES" or "NO".
        price:     Limit price (0–1 range for prediction markets).
        size:      Order size in USD.
    """

    market_id: str
    side: str
    price: float
    size: float


# ── Position snapshot ─────────────────────────────────────────────────────────


@dataclass
class PositionState:
    """Lightweight read-only snapshot of a position.

    Attributes:
        market_id:      Polymarket condition ID.
        side:           "YES" or "NO".
        size:           Position size in USD.
        entry_price:    Weighted average entry price.
        current_price:  Latest mark price.
        unrealized_pnl: Current unrealized PnL in USD.
    """

    market_id: str
    side: str
    size: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
