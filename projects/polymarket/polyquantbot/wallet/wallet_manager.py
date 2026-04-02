"""WalletManager — custodial wallet system.

Provides per-user wallet creation and balance tracking with SQLite persistence.

Rules:
    - Custodial only: no key export, no withdraw.
    - All operations are idempotent.
    - Fee applied per-trade at execution layer — fee = trade_size * fee_rate.
    - No global mutable state — all state is instance-scoped.
    - Persists balance and exposure to SQLite on every write.

Usage::

    wm = WalletManager()
    wallet_id = await wm.create_wallet(user_id=12345)
    balance   = await wm.get_balance(wallet_id)
    exposure  = await wm.get_exposure(wallet_id)

    # Called by execution layer only — not Telegram UI:
    await wm.record_trade(wallet_id, size=100.0, pnl_net=5.25, fee=0.50)
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

import structlog

from ..infra.db.sqlite_client import SQLiteClient

log = structlog.get_logger()

# ── Fee constant (backend only — never exposed) ───────────────────────────────
_TRADE_FEE_RATE: float = 0.005   # 0.5 % of trade size per trade


@dataclass
class _WalletRecord:
    """Internal wallet state."""
    wallet_id: str
    user_id: int
    balance: float = 0.0
    exposure: float = 0.0
    total_trades: int = 0
    created_at: float = field(default_factory=time.time)


class WalletManager:
    """In-process custodial wallet store with SQLite persistence.

    Thread-safety: asyncio single event-loop only.

    Args:
        db: Optional SQLiteClient for persistence.  When provided, wallets
            are loaded from the DB on creation and persisted on every write.
            When None, operates in in-memory mode (no persistence).
    """

    def __init__(self, db: Optional[SQLiteClient] = None) -> None:
        self._wallets: dict[str, _WalletRecord] = {}      # wallet_id → record
        self._user_index: dict[int, str] = {}              # user_id → wallet_id
        self._lock = asyncio.Lock()
        self._db = db

        log.info("wallet_manager_initialized", persistent=db is not None)

    # ── Public API ─────────────────────────────────────────────────────────────

    async def create_wallet(self, user_id: int) -> str:
        """Create and register a new wallet for *user_id*.

        Idempotent: returns the existing wallet_id if one already exists.
        Persists the wallet record to SQLite when a DB client is configured.

        Args:
            user_id: Telegram user ID.

        Returns:
            wallet_id string.
        """
        async with self._lock:
            if user_id in self._user_index:
                existing_id = self._user_index[user_id]
                log.debug("wallet_already_exists", user_id=user_id, wallet_id=existing_id)
                return existing_id

            wallet_id = f"wlt_{uuid.uuid4().hex[:16]}"
            record = _WalletRecord(wallet_id=wallet_id, user_id=user_id)
            self._wallets[wallet_id] = record
            self._user_index[user_id] = wallet_id

            log.info(
                "wallet_created",
                user_id=user_id,
                wallet_id=wallet_id,
            )

        # Persist outside the lock to avoid blocking
        if self._db is not None:
            await self._db.upsert_wallet(
                wallet_id=wallet_id,
                balance=record.balance,
                exposure=record.exposure,
                updated_at=record.created_at,
            )

        return wallet_id

    async def get_balance(self, wallet_id: str) -> float:
        """Return net balance for *wallet_id*.

        Args:
            wallet_id: Wallet identifier.

        Returns:
            Net balance in USD (float).  Returns 0.0 if not found.
        """
        async with self._lock:
            record = self._wallets.get(wallet_id)
            if record is None:
                log.warning("wallet_not_found_get_balance", wallet_id=wallet_id)
                return 0.0
            return record.balance

    async def get_exposure(self, wallet_id: str) -> float:
        """Return current open exposure for *wallet_id*.

        Args:
            wallet_id: Wallet identifier.

        Returns:
            Open exposure in USD (float).  Returns 0.0 if not found.
        """
        async with self._lock:
            record = self._wallets.get(wallet_id)
            if record is None:
                log.warning("wallet_not_found_get_exposure", wallet_id=wallet_id)
                return 0.0
            return record.exposure

    async def record_trade(
        self,
        wallet_id: str,
        size: float,
        pnl_net: float,
        fee: float,
        exposure_delta: float = 0.0,
        user_id: Optional[int] = None,
    ) -> None:
        """Record a completed trade and update wallet balance.

        The fee is calculated as ``size * _TRADE_FEE_RATE`` at the execution
        layer and passed in here for logging.  This method does NOT re-apply
        a fee — it only records the trade.

        Args:
            wallet_id: Wallet to credit/debit.
            size: Trade size in USD (used for fee calculation reference).
            pnl_net: Net PnL after fee (applied to wallet balance).
            fee: Fee amount already deducted (= size * fee_rate).
            exposure_delta: Change in open exposure (positive = open, negative = close).
            user_id: Optional Telegram user ID for DB trade record.
        """
        async with self._lock:
            record = self._wallets.get(wallet_id)
            if record is None:
                log.error("wallet_not_found_record_trade", wallet_id=wallet_id)
                return

            record.balance += pnl_net
            record.exposure = max(0.0, record.exposure + exposure_delta)
            record.total_trades += 1

            balance_snapshot = record.balance
            exposure_snapshot = record.exposure

            log.info(
                "wallet_trade_recorded",
                wallet_id=wallet_id,
                size=round(size, 6),
                fee=round(fee, 6),
                pnl_net=round(pnl_net, 6),
                new_balance=round(balance_snapshot, 6),
                total_trades=record.total_trades,
            )

        # Persist outside the lock to avoid blocking
        if self._db is not None:
            await self._db.upsert_wallet(
                wallet_id=wallet_id,
                balance=balance_snapshot,
                exposure=exposure_snapshot,
            )
            if user_id is not None:
                await self._db.insert_trade(
                    user_id=user_id,
                    size=size,
                    fee=fee,
                    pnl_net=pnl_net,
                )

    async def wallet_id_for_user(self, user_id: int) -> Optional[str]:
        """Look up wallet_id for *user_id*.

        Args:
            user_id: Telegram user ID.

        Returns:
            wallet_id string or None if no wallet exists.
        """
        async with self._lock:
            return self._user_index.get(user_id)

    # ── Private ────────────────────────────────────────────────────────────────

    @staticmethod
    def calculate_fee(trade_size: float) -> float:
        """Calculate the platform fee for a given trade size.

        Fee is a fixed percentage of trade size (not PnL).
        This is the canonical fee calculation — always use this method.

        Negative ``trade_size`` values are clamped to zero (no fee charged
        on zero-size or invalid trades).

        Args:
            trade_size: Trade size in USD.  Must be >= 0 in normal usage.

        Returns:
            Fee amount in USD (>= 0).
        """
        return max(0.0, trade_size) * _TRADE_FEE_RATE

    async def load_from_db(self, wallet_id: str, user_id: int) -> bool:
        """Reload wallet state from the DB into memory.

        Called on startup to restore persisted state so that in-memory
        records reflect the last persisted values after a restart.

        Args:
            wallet_id: Wallet identifier to load.
            user_id: Telegram user ID that owns this wallet.

        Returns:
            True if the wallet was found and loaded, False otherwise.
        """
        if self._db is None:
            return False
        row = await self._db.get_wallet(wallet_id)
        if row is None:
            return False

        async with self._lock:
            if wallet_id not in self._wallets:
                record = _WalletRecord(wallet_id=wallet_id, user_id=user_id)
                self._wallets[wallet_id] = record
                self._user_index[user_id] = wallet_id
            else:
                record = self._wallets[wallet_id]

            record.balance = float(row.get("balance", 0.0))
            record.exposure = float(row.get("exposure", 0.0))

            log.info(
                "wallet_loaded_from_db",
                wallet_id=wallet_id,
                balance=record.balance,
                exposure=record.exposure,
            )
        return True
