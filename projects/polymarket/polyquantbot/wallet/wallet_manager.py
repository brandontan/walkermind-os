"""WalletManager — custodial wallet system.

Provides per-user wallet creation and balance tracking.

Rules:
    - Custodial only: no key export, no withdraw.
    - All operations are idempotent.
    - Fee applied per-trade at backend; never surfaced in API responses.
    - No global mutable state — all state is instance-scoped.

Usage::

    wm = WalletManager()
    wallet_id = await wm.create_wallet(user_id=12345)
    balance   = await wm.get_balance(wallet_id)
    exposure  = await wm.get_exposure(wallet_id)

    # Called by execution layer only — not Telegram UI:
    await wm.record_trade(wallet_id, gross_pnl=10.50)
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

import structlog

log = structlog.get_logger()

# ── Fee constant (backend only — never exposed) ───────────────────────────────
_TRADE_FEE_RATE: float = 0.005   # 0.5 % of gross PnL per trade


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
    """In-process custodial wallet store.

    Thread-safety: asyncio single event-loop only.
    """

    def __init__(self) -> None:
        self._wallets: dict[str, _WalletRecord] = {}      # wallet_id → record
        self._user_index: dict[int, str] = {}              # user_id → wallet_id
        self._lock = asyncio.Lock()

        log.info("wallet_manager_initialized")

    # ── Public API ─────────────────────────────────────────────────────────────

    async def create_wallet(self, user_id: int) -> str:
        """Create and register a new wallet for *user_id*.

        Idempotent: returns the existing wallet_id if one already exists.

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
        gross_pnl: float,
        exposure_delta: float = 0.0,
    ) -> float:
        """Record a completed trade and apply the hidden platform fee.

        The net PnL (after fee deduction) is added to the wallet balance.
        This method is called by the execution layer — never by Telegram UI.

        Args:
            wallet_id: Wallet to credit/debit.
            gross_pnl: Gross trade PnL before fee.
            exposure_delta: Change in open exposure (positive = open, negative = close).

        Returns:
            Net PnL after fee (for internal use only).
        """
        net_pnl = self._apply_fee(gross_pnl)

        async with self._lock:
            record = self._wallets.get(wallet_id)
            if record is None:
                log.error("wallet_not_found_record_trade", wallet_id=wallet_id)
                return net_pnl

            record.balance += net_pnl
            record.exposure = max(0.0, record.exposure + exposure_delta)
            record.total_trades += 1

            log.info(
                "wallet_trade_recorded",
                wallet_id=wallet_id,
                gross_pnl=round(gross_pnl, 6),
                net_pnl=round(net_pnl, 6),
                new_balance=round(record.balance, 6),
                total_trades=record.total_trades,
            )

        return net_pnl

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
    def _apply_fee(gross_pnl: float) -> float:
        """Deduct platform fee from gross PnL.

        Fee is only applied when gross_pnl is positive (winning trade).
        Never surfaced in UI responses.

        Args:
            gross_pnl: Pre-fee trade PnL.

        Returns:
            Net PnL after fee.
        """
        if gross_pnl <= 0.0:
            return gross_pnl
        fee = gross_pnl * _TRADE_FEE_RATE
        return gross_pnl - fee
