"""Phase 11.4 — WalletManager: Per-user wallet with SQLite persistence.

Fee model: fee = trade_size * 0.005  (0.5% of trade size, never on PnL)

Key methods:
    create_wallet(user_id)           → wallet_id
    load_from_db(wallet_id)          → bool (False if not found)
    record_trade(...)                → persists trade + updates balance
    calculate_fee(trade_size) → float
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import structlog

log = structlog.get_logger(__name__)

_FEE_RATE = 0.005   # 0.5% of trade size


@dataclass
class WalletState:
    wallet_id: str
    balance: float = 0.0
    exposure: float = 0.0
    total_trades: int = 0
    trade_history: List[dict] = field(default_factory=list)


class WalletManager:
    """Per-user wallet manager with SQLite-backed persistence."""

    def __init__(self, db=None, initial_balance: float = 1000.0) -> None:
        """
        Args:
            db: SQLiteClient instance (optional — runs in-memory if None)
            initial_balance: Starting balance for new wallets
        """
        self._db = db
        self._initial_balance = initial_balance
        self._wallets: Dict[str, WalletState] = {}
        self._lock = asyncio.Lock()

    # ── Fee model ─────────────────────────────────────────────────────────────

    @staticmethod
    def calculate_fee(trade_size: float) -> float:
        """Calculate fee as 0.5% of trade size (never on PnL).

        Args:
            trade_size: Absolute size of the trade in USD.

        Returns:
            Non-negative fee amount.
        """
        if trade_size <= 0:
            return 0.0
        return max(0.0, trade_size * _FEE_RATE)

    # ── Wallet lifecycle ──────────────────────────────────────────────────────

    async def create_wallet(self, user_id: str) -> str:
        """Create a new wallet for user_id, persist to DB.

        Returns:
            wallet_id (UUID string)
        """
        wallet_id = str(uuid.uuid4())
        state = WalletState(wallet_id=wallet_id, balance=self._initial_balance)

        async with self._lock:
            self._wallets[wallet_id] = state

        if self._db:
            await self._db.upsert_wallet(
                wallet_id=wallet_id,
                balance=state.balance,
                exposure=state.exposure,
                total_trades=state.total_trades,
            )

        log.info("wallet_created", wallet_id=wallet_id, user_id=user_id,
                 initial_balance=self._initial_balance)
        return wallet_id

    async def load_from_db(self, wallet_id: str) -> bool:
        """Restore wallet state from DB. Returns False if not found."""
        if not self._db:
            return False

        row = await self._db.get_wallet(wallet_id)
        if not row:
            log.info("wallet_not_found_in_db", wallet_id=wallet_id)
            return False

        async with self._lock:
            self._wallets[wallet_id] = WalletState(
                wallet_id=wallet_id,
                balance=row["balance"],
                exposure=row["exposure"],
                total_trades=row["total_trades"],
            )

        log.info("wallet_loaded_from_db", wallet_id=wallet_id,
                 balance=row["balance"], total_trades=row["total_trades"])
        return True

    def get_wallet(self, wallet_id: str) -> Optional[WalletState]:
        return self._wallets.get(wallet_id)

    # ── Trade recording ───────────────────────────────────────────────────────

    async def record_trade(
        self,
        wallet_id: str,
        market_id: str,
        side: str,
        size: float,
        price: float,
        pnl_net: float,
        fee: Optional[float] = None,
        trade_id: Optional[str] = None,
    ) -> bool:
        """Record a trade and update wallet balance.

        Fee is pre-computed at execution layer and passed in.
        Falls back to calculate_fee(size) if not provided.

        Args:
            wallet_id: Target wallet ID.
            market_id: Polymarket condition ID.
            side: "BUY" or "SELL".
            size: Trade size in USD.
            price: Fill price (0–1).
            pnl_net: Net PnL after fee.
            fee: Pre-computed fee (defaults to calculate_fee(size)).
            trade_id: Unique trade ID (auto-generated if not provided).

        Returns:
            True on success, False if wallet not found.
        """
        state = self._wallets.get(wallet_id)
        if state is None:
            log.error("record_trade_wallet_not_found", wallet_id=wallet_id)
            return False

        if fee is None:
            fee = self.calculate_fee(size)

        tid = trade_id or str(uuid.uuid4())
        trade_record = {
            "trade_id": tid, "market_id": market_id, "side": side,
            "size": size, "price": price, "pnl_net": pnl_net, "fee": fee,
            "timestamp": time.time(),
        }

        async with self._lock:
            state.balance += pnl_net
            state.total_trades += 1
            state.trade_history.append(trade_record)

        # Persist to DB (fail-safe — never crash trading on DB error)
        if self._db:
            await self._db.insert_trade(
                trade_id=tid, wallet_id=wallet_id, market_id=market_id,
                side=side, size=size, price=price, pnl_net=pnl_net, fee=fee,
            )
            await self._db.upsert_wallet(
                wallet_id=wallet_id, balance=state.balance,
                exposure=state.exposure, total_trades=state.total_trades,
            )

        log.info("wallet_trade_recorded", wallet_id=wallet_id, trade_id=tid,
                 pnl_net=pnl_net, fee=fee, balance=state.balance)
        return True

    @property
    def total_trades(self) -> int:
        return sum(w.total_trades for w in self._wallets.values())
