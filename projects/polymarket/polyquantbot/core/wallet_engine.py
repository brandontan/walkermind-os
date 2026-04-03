"""core.wallet_engine — Paper trading wallet engine for PolyQuantBot.

Tracks cash (available), locked (reserved for open positions), and equity
(total portfolio value) for paper-trading simulation.

Interfaces::

    WalletEngine.lock_funds(amount, trade_id)     → locks cash, idempotent
    WalletEngine.unlock_funds(amount, trade_id)   → releases locked cash
    WalletEngine.settle_trade(pnl, trade_id)      → settles PnL into cash
    WalletEngine.get_state()                      → WalletState
    WalletEngine.restore_state(state)             → restore after crash

Design:
  - All mutations are idempotent: duplicate trade_ids are silently skipped.
  - Raises InsufficientFundsError when cash < requested lock amount.
  - Structured JSON logging on every state change.
  - Initial balance read from PAPER_INITIAL_BALANCE env var (default 10 000).
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any, Set

import structlog

log = structlog.get_logger(__name__)

# ── Exceptions ────────────────────────────────────────────────────────────────


class InsufficientFundsError(Exception):
    """Raised when a lock_funds request exceeds available cash."""


# ── Data model ────────────────────────────────────────────────────────────────


@dataclass
class WalletState:
    """Snapshot of the paper wallet at a point in time.

    Attributes:
        cash:   Available (unlocked) funds in USD.
        locked: Funds reserved for open positions in USD.
        equity: Total portfolio value (cash + locked) in USD.
    """

    cash: float
    locked: float
    equity: float


# ── Engine ────────────────────────────────────────────────────────────────────


class WalletEngine:
    """Idempotent paper trading wallet.

    All state mutations are guarded by an asyncio Lock to prevent races when
    multiple coroutines execute concurrently.

    Args:
        initial_balance: Starting cash. Defaults to ``PAPER_INITIAL_BALANCE``
                         env var or 10 000.0.
    """

    def __init__(self, initial_balance: float | None = None) -> None:
        if initial_balance is None:
            initial_balance = float(
                os.environ.get("PAPER_INITIAL_BALANCE", "10000.0")
            )

        self._cash: float = round(initial_balance, 4)
        self._locked: float = 0.0

        # Idempotency sets — keyed by action type to avoid cross-action collisions
        self._locked_trade_ids: Set[str] = set()
        self._unlocked_trade_ids: Set[str] = set()
        self._settled_trade_ids: Set[str] = set()

        self._lock: asyncio.Lock = asyncio.Lock()

        log.info(
            "wallet_engine_initialized",
            cash=self._cash,
            locked=self._locked,
            equity=self._equity,
        )

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def _equity(self) -> float:
        return round(self._cash + self._locked, 4)

    # ── Writes ────────────────────────────────────────────────────────────────

    async def lock_funds(self, amount: float, trade_id: str) -> WalletState:
        """Reserve *amount* USD for an open position.

        Args:
            amount:   USD to lock.
            trade_id: Unique trade identifier — duplicate calls are no-ops.

        Returns:
            Updated :class:`WalletState`.

        Raises:
            InsufficientFundsError: When ``cash < amount``.
            ValueError: When ``amount <= 0``.
        """
        if amount <= 0:
            raise ValueError(f"lock_funds: amount must be positive, got {amount}")

        async with self._lock:
            if trade_id in self._locked_trade_ids:
                log.info(
                    "wallet_lock_duplicate",
                    trade_id=trade_id,
                    amount=amount,
                )
                return self.get_state()

            if self._cash < amount:
                log.warning(
                    "wallet_insufficient_funds",
                    trade_id=trade_id,
                    requested=amount,
                    available=self._cash,
                )
                raise InsufficientFundsError(
                    f"Insufficient funds: requested {amount:.4f} but only "
                    f"{self._cash:.4f} available."
                )

            self._cash = round(self._cash - amount, 4)
            self._locked = round(self._locked + amount, 4)
            self._locked_trade_ids.add(trade_id)

            state = self.get_state()
            log.info(
                "wallet_funds_locked",
                trade_id=trade_id,
                amount=amount,
                cash=state.cash,
                locked=state.locked,
                equity=state.equity,
            )
            return state

    async def unlock_funds(self, amount: float, trade_id: str) -> WalletState:
        """Release *amount* USD back to available cash.

        Idempotent by *trade_id*.  Does not raise on over-unlock — it clamps
        to zero and logs a warning instead (defensive against double-close).

        Args:
            amount:   USD to unlock.
            trade_id: Unique trade identifier — duplicate calls are no-ops.

        Returns:
            Updated :class:`WalletState`.
        """
        if amount <= 0:
            raise ValueError(f"unlock_funds: amount must be positive, got {amount}")

        async with self._lock:
            if trade_id in self._unlocked_trade_ids:
                log.info(
                    "wallet_unlock_duplicate",
                    trade_id=trade_id,
                    amount=amount,
                )
                return self.get_state()

            if self._locked < amount:
                log.warning(
                    "wallet_unlock_over_release",
                    trade_id=trade_id,
                    requested=amount,
                    locked=self._locked,
                )
                # Clamp: release only what is locked
                amount = self._locked

            self._locked = round(self._locked - amount, 4)
            self._cash = round(self._cash + amount, 4)
            self._unlocked_trade_ids.add(trade_id)

            state = self.get_state()
            log.info(
                "wallet_funds_unlocked",
                trade_id=trade_id,
                amount=amount,
                cash=state.cash,
                locked=state.locked,
                equity=state.equity,
            )
            return state

    async def settle_trade(self, pnl: float, trade_id: str) -> WalletState:
        """Apply realized PnL to cash after a position closes.

        This is called *after* :meth:`unlock_funds` returns principal.
        It adds the profit (or subtracts the loss) from *cash*.

        Idempotent by *trade_id*.

        Args:
            pnl:      Realized PnL in USD (positive = profit, negative = loss).
            trade_id: Unique trade identifier — duplicate calls are no-ops.

        Returns:
            Updated :class:`WalletState`.
        """
        async with self._lock:
            if trade_id in self._settled_trade_ids:
                log.info(
                    "wallet_settle_duplicate",
                    trade_id=trade_id,
                    pnl=pnl,
                )
                return self.get_state()

            self._cash = round(self._cash + pnl, 4)

            # Guard: cash must not go negative (defensive)
            if self._cash < 0:
                log.warning(
                    "wallet_cash_negative_clamped",
                    trade_id=trade_id,
                    pnl=pnl,
                    cash_before_clamp=self._cash,
                )
                self._cash = 0.0

            self._settled_trade_ids.add(trade_id)

            state = self.get_state()
            log.info(
                "wallet_trade_settled",
                trade_id=trade_id,
                pnl=round(pnl, 4),
                cash=state.cash,
                locked=state.locked,
                equity=state.equity,
            )
            return state

    async def withdraw(self, amount: float, reference: str = "manual") -> WalletState:
        """Simulate a paper-mode withdrawal by reducing available cash.

        This is a **paper simulation only** — no real blockchain transaction
        is performed.  The method reduces cash by *amount*, enforcing that
        the remaining cash stays ≥ 0.

        Args:
            amount:    USD amount to withdraw.  Must be > 0 and ≤ current cash.
            reference: Human-readable reference label (e.g. "manual", "test").

        Returns:
            Updated :class:`WalletState`.

        Raises:
            ValueError:              When ``amount <= 0``.
            InsufficientFundsError:  When ``cash < amount``.
        """
        if amount <= 0:
            raise ValueError(f"withdraw: amount must be positive, got {amount}")

        async with self._lock:
            if self._cash < amount:
                log.warning(
                    "wallet_withdraw_insufficient",
                    requested=amount,
                    available=self._cash,
                    reference=reference,
                )
                raise InsufficientFundsError(
                    f"Insufficient funds: requested {amount:.4f} but only "
                    f"{self._cash:.4f} available."
                )

            self._cash = round(self._cash - amount, 4)

            state = self.get_state()
            log.info(
                "wallet_paper_withdraw",
                amount=amount,
                reference=reference,
                cash=state.cash,
                locked=state.locked,
                equity=state.equity,
            )
            return state

    # ── Reads ─────────────────────────────────────────────────────────────────

    def get_state(self) -> WalletState:
        """Return current wallet state snapshot (non-blocking, no lock)."""
        return WalletState(
            cash=self._cash,
            locked=self._locked,
            equity=self._equity,
        )

    @property
    def buying_power(self) -> float:
        """Return available buying power (= free cash, non-blocking)."""
        return self._cash

    # ── Crash recovery ────────────────────────────────────────────────────────

    async def restore_state(self, state: WalletState) -> None:
        """Overwrite in-memory state — used for crash recovery.

        Args:
            state: Previously persisted :class:`WalletState`.
        """
        async with self._lock:
            self._cash = round(state.cash, 4)
            self._locked = round(state.locked, 4)

            log.info(
                "wallet_state_restored",
                cash=self._cash,
                locked=self._locked,
                equity=self._equity,
            )

    # ── DB persistence hooks ──────────────────────────────────────────────────

    async def persist(self, db: Any) -> None:
        """Persist current wallet state to the database.

        Called after every mutation so state survives restarts.

        Args:
            db: :class:`~infra.db.database.DatabaseClient` instance.
        """
        state = self.get_state()
        try:
            await db.save_wallet_state(
                cash=state.cash,
                locked=state.locked,
                equity=state.equity,
            )
            log.info(
                "persistence_write",
                entity="wallet_state",
                cash=state.cash,
                locked=state.locked,
                equity=state.equity,
            )
        except Exception as exc:
            log.error(
                "wallet_persist_failed",
                error=str(exc),
            )

    @classmethod
    async def restore_from_db(cls, db: Any, initial_balance: float | None = None) -> "WalletEngine":
        """Create a WalletEngine and restore state from the database.

        If no persisted state is found, uses *initial_balance* (or
        ``PAPER_INITIAL_BALANCE`` env var).

        Args:
            db:              :class:`~infra.db.database.DatabaseClient` instance.
            initial_balance: Fallback balance if DB is empty.

        Returns:
            A new :class:`WalletEngine` with state restored.
        """
        engine = cls(initial_balance=initial_balance)
        try:
            row = await db.load_latest_wallet_state()
            if row is not None:
                state = WalletState(
                    cash=float(row["cash"]),
                    locked=float(row["locked"]),
                    equity=float(row["equity"]),
                )
                await engine.restore_state(state)
                log.info(
                    "wallet_state_restored_from_db",
                    cash=state.cash,
                    locked=state.locked,
                    equity=state.equity,
                )
            else:
                log.info(
                    "wallet_no_persisted_state",
                    hint="Using initial balance",
                    cash=engine._cash,
                )
        except Exception as exc:
            log.warning(
                "wallet_restore_from_db_failed",
                error=str(exc),
                hint="Using initial balance as fallback",
            )
        return engine
