"""execution.paper_engine — Paper trading execution engine for PolyQuantBot.

Simulates order fills with realistic behavior (slippage, partial fills) and
integrates with the wallet engine, position manager, and trade ledger.

Interfaces::

    PaperOrderResult(trade_id, market_id, side, requested_size, filled_size,
                     fill_price, fee, status, reason)
    PaperEngine.execute_order(order)         → PaperOrderResult
    PaperEngine.close_order(market_id, ...)  → PaperOrderResult

Pipeline for execute_order:
    1. Validate order fields
    2. Check sufficient cash balance
    3. Simulate partial fill (80–100 % of requested size)
    4. Apply slippage (±0.5 % of price)
    5. Lock funds in WalletEngine
    6. Open / update position via PaperPositionManager
    7. Record OPEN entry in TradeLedger
    8. Return PaperOrderResult

Pipeline for close_order:
    1. Close position → realized PnL
    2. Unlock locked principal in WalletEngine
    3. Settle realized PnL in WalletEngine
    4. Record CLOSE entry in TradeLedger
    5. Update PnLTracker (if available)
    6. Return PaperOrderResult

Design:
  - Idempotent: duplicate trade_ids are silently skipped.
  - Timeout guard: logs a warning when execution exceeds 500 ms.
  - Structured JSON logging on every step.
  - asyncio only — no threading.
"""
from __future__ import annotations

import asyncio
import datetime
import random
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Set

import structlog

from ..core.wallet_engine import WalletEngine, InsufficientFundsError
from ..core.positions import PaperPositionManager
from ..core.ledger import TradeLedger, LedgerEntry, LedgerAction

log = structlog.get_logger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_EXECUTION_TIMEOUT_S: float = 0.5       # warn if execution takes > 500 ms
_SLIPPAGE_PCT: float = 0.005            # ±0.5 % slippage
_FILL_MIN_PCT: float = 0.80             # minimum partial fill fraction
_DEFAULT_FEE_PCT: float = 0.001         # 0.1 % fee on filled size


# ── Result types ──────────────────────────────────────────────────────────────


class OrderStatus(str, Enum):
    """Status of a paper order execution attempt."""

    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"


@dataclass
class PaperOrderResult:
    """Result of a single paper order execution.

    Attributes:
        trade_id:       Unique identifier for this order execution.
        market_id:      Polymarket condition ID.
        side:           "YES" or "NO".
        requested_size: USD size requested.
        filled_size:    USD size actually filled.
        fill_price:     Effective fill price after slippage.
        fee:            Fee charged in USD.
        status:         FILLED, PARTIAL, or REJECTED.
        reason:         Human-readable rejection or partial-fill reason.
    """

    trade_id: str
    market_id: str
    side: str
    requested_size: float
    filled_size: float
    fill_price: float
    fee: float
    status: OrderStatus
    reason: str = field(default="")


# ── Engine ────────────────────────────────────────────────────────────────────


class PaperEngine:
    """Paper trading engine integrating wallet, positions, and ledger.

    Args:
        wallet:    :class:`~core.wallet_engine.WalletEngine` instance.
        positions: :class:`~core.positions.PaperPositionManager` instance.
        ledger:    :class:`~core.ledger.TradeLedger` instance.
        pnl_tracker: Optional PnLTracker for realized PnL persistence.
        random_seed: Optional seed for the internal ``random.Random`` instance.
                     Use a fixed seed in tests for deterministic fill/slippage.
    """

    def __init__(
        self,
        wallet: WalletEngine,
        positions: PaperPositionManager,
        ledger: TradeLedger,
        pnl_tracker: Optional[object] = None,
        random_seed: Optional[int] = None,
    ) -> None:
        self._wallet = wallet
        self._positions = positions
        self._ledger = ledger
        self._pnl_tracker = pnl_tracker
        self._processed_trade_ids: Set[str] = set()
        # Use a private seeded Random so tests can pass random_seed for reproducibility.
        # Production callers leave random_seed=None for non-deterministic simulation.
        self._rng: random.Random = random.Random(random_seed)

        log.info("paper_engine_initialized", seeded=random_seed is not None)

    # ── Public API ────────────────────────────────────────────────────────────

    async def execute_order(self, order: dict) -> PaperOrderResult:
        """Execute a paper buy/open order.

        Steps:
            1. Validate input fields.
            2. Ensure sufficient cash.
            3. Simulate partial fill (80–100 %).
            4. Apply slippage (±0.5 %).
            5. Lock funds in wallet.
            6. Open / accumulate position.
            7. Record in ledger.
            8. Return result.

        Args:
            order: Dict with keys: ``market_id``, ``side``, ``price``, ``size``.
                   Optionally includes ``trade_id``.

        Returns:
            :class:`PaperOrderResult`.
        """
        t_start = time.monotonic()

        # ── 1. Extract and validate ──────────────────────────────────────────
        trade_id: str = order.get("trade_id") or f"paper-{uuid.uuid4().hex[:16]}"
        market_id: str = str(order.get("market_id", ""))
        side: str = str(order.get("side", "")).upper()
        price: float = float(order.get("price", 0.0))
        size: float = float(order.get("size", 0.0))

        validation_error = self._validate_order(
            market_id=market_id, side=side, price=price, size=size
        )
        if validation_error:
            log.warning(
                "paper_engine_order_rejected",
                trade_id=trade_id,
                market_id=market_id,
                reason=validation_error,
            )
            return PaperOrderResult(
                trade_id=trade_id,
                market_id=market_id,
                side=side,
                requested_size=size,
                filled_size=0.0,
                fill_price=0.0,
                fee=0.0,
                status=OrderStatus.REJECTED,
                reason=validation_error,
            )

        # ── 2. Idempotency check ─────────────────────────────────────────────
        if trade_id in self._processed_trade_ids:
            log.info(
                "paper_engine_order_duplicate",
                trade_id=trade_id,
                market_id=market_id,
            )
            return PaperOrderResult(
                trade_id=trade_id,
                market_id=market_id,
                side=side,
                requested_size=size,
                filled_size=0.0,
                fill_price=price,
                fee=0.0,
                status=OrderStatus.FILLED,
                reason="duplicate_trade_id",
            )

        # ── 3. Check balance ─────────────────────────────────────────────────
        wallet_state = self._wallet.get_state()
        if wallet_state.cash < size:
            log.warning(
                "paper_engine_order_rejected_insufficient_funds",
                trade_id=trade_id,
                market_id=market_id,
                requested=size,
                available=wallet_state.cash,
            )
            return PaperOrderResult(
                trade_id=trade_id,
                market_id=market_id,
                side=side,
                requested_size=size,
                filled_size=0.0,
                fill_price=price,
                fee=0.0,
                status=OrderStatus.REJECTED,
                reason="insufficient_funds",
            )

        # ── 4. Simulate partial fill ─────────────────────────────────────────
        fill_pct = self._rng.uniform(_FILL_MIN_PCT, 1.0)
        filled_size = round(size * fill_pct, 4)
        is_partial = fill_pct < 0.9999

        # ── 5. Apply slippage ────────────────────────────────────────────────
        slippage_direction = self._rng.choice([-1, 1])
        slippage_factor = 1.0 + slippage_direction * self._rng.uniform(0.0, _SLIPPAGE_PCT)
        fill_price = round(price * slippage_factor, 6)

        # ── 6. Compute fee ───────────────────────────────────────────────────
        fee = round(filled_size * _DEFAULT_FEE_PCT, 6)

        # ── 7. Lock funds in wallet ──────────────────────────────────────────
        try:
            await self._wallet.lock_funds(filled_size, trade_id)
        except InsufficientFundsError as exc:
            log.warning(
                "paper_engine_lock_funds_failed",
                trade_id=trade_id,
                market_id=market_id,
                error=str(exc),
            )
            return PaperOrderResult(
                trade_id=trade_id,
                market_id=market_id,
                side=side,
                requested_size=size,
                filled_size=0.0,
                fill_price=fill_price,
                fee=0.0,
                status=OrderStatus.REJECTED,
                reason=f"lock_funds_failed:{exc}",
            )

        # ── 8. Open / update position ────────────────────────────────────────
        try:
            self._positions.open_position(
                market_id=market_id,
                side=side,
                size=filled_size,
                entry_price=fill_price,
                trade_id=trade_id,
            )
        except Exception as exc:
            log.error(
                "paper_engine_position_open_error",
                trade_id=trade_id,
                market_id=market_id,
                error=str(exc),
            )
            # Attempt to roll back the wallet lock
            try:
                await self._wallet.unlock_funds(filled_size, f"{trade_id}-rollback")
            except Exception as rollback_exc:
                log.error(
                    "paper_engine_rollback_error",
                    trade_id=trade_id,
                    error=str(rollback_exc),
                )
            return PaperOrderResult(
                trade_id=trade_id,
                market_id=market_id,
                side=side,
                requested_size=size,
                filled_size=0.0,
                fill_price=fill_price,
                fee=fee,
                status=OrderStatus.REJECTED,
                reason=f"position_open_error:{exc}",
            )

        # ── 9. Record in ledger ──────────────────────────────────────────────
        action = LedgerAction.PARTIAL if is_partial else LedgerAction.OPEN
        self._ledger.record(
            LedgerEntry(
                trade_id=trade_id,
                market_id=market_id,
                action=action,
                price=fill_price,
                size=filled_size,
                fee=fee,
                timestamp=_utc_now(),
            )
        )

        self._processed_trade_ids.add(trade_id)
        elapsed = time.monotonic() - t_start

        if elapsed > _EXECUTION_TIMEOUT_S:
            log.warning(
                "paper_engine_execute_slow",
                trade_id=trade_id,
                elapsed_ms=round(elapsed * 1_000, 1),
                threshold_ms=int(_EXECUTION_TIMEOUT_S * 1_000),
            )

        status = OrderStatus.PARTIAL if is_partial else OrderStatus.FILLED
        log.info(
            "paper_engine_order_executed",
            trade_id=trade_id,
            market_id=market_id,
            side=side,
            requested_size=size,
            filled_size=filled_size,
            fill_price=fill_price,
            fee=fee,
            status=status,
            elapsed_ms=round(elapsed * 1_000, 1),
        )

        return PaperOrderResult(
            trade_id=trade_id,
            market_id=market_id,
            side=side,
            requested_size=size,
            filled_size=filled_size,
            fill_price=fill_price,
            fee=fee,
            status=status,
            reason="partial_fill" if is_partial else "",
        )

    async def close_order(
        self,
        market_id: str,
        close_price: float,
        trade_id: Optional[str] = None,
    ) -> PaperOrderResult:
        """Close an open position.

        Steps:
            1. Close position → realized PnL.
            2. Unlock locked principal in wallet.
            3. Settle realized PnL in wallet.
            4. Record CLOSE in ledger.
            5. Update PnLTracker if available.
            6. Return result.

        Args:
            market_id:   Polymarket condition ID.
            close_price: Close price.
            trade_id:    Optional explicit trade ID (generated if omitted).

        Returns:
            :class:`PaperOrderResult`.
        """
        t_start = time.monotonic()
        trade_id = trade_id or f"close-{uuid.uuid4().hex[:16]}"

        if trade_id in self._processed_trade_ids:
            log.info(
                "paper_engine_close_duplicate",
                trade_id=trade_id,
                market_id=market_id,
            )
            return PaperOrderResult(
                trade_id=trade_id,
                market_id=market_id,
                side="",
                requested_size=0.0,
                filled_size=0.0,
                fill_price=close_price,
                fee=0.0,
                status=OrderStatus.FILLED,
                reason="duplicate_trade_id",
            )

        # ── 1. Close position ────────────────────────────────────────────────
        pos = self._positions.get_position(market_id)
        if pos is None:
            log.warning(
                "paper_engine_close_no_position",
                market_id=market_id,
                trade_id=trade_id,
            )
            return PaperOrderResult(
                trade_id=trade_id,
                market_id=market_id,
                side="",
                requested_size=0.0,
                filled_size=0.0,
                fill_price=close_price,
                fee=0.0,
                status=OrderStatus.REJECTED,
                reason="no_open_position",
            )

        side = pos.side
        locked_size = pos.size

        realized_pnl = self._positions.close_position(
            market_id=market_id,
            close_price=close_price,
            trade_id=trade_id,
        )

        # ── 2. Unlock principal ──────────────────────────────────────────────
        try:
            await self._wallet.unlock_funds(locked_size, f"{trade_id}-unlock")
        except Exception as exc:
            log.error(
                "paper_engine_unlock_error",
                trade_id=trade_id,
                market_id=market_id,
                error=str(exc),
            )

        # ── 3. Settle PnL ────────────────────────────────────────────────────
        try:
            await self._wallet.settle_trade(realized_pnl, f"{trade_id}-settle")
        except Exception as exc:
            log.error(
                "paper_engine_settle_error",
                trade_id=trade_id,
                market_id=market_id,
                error=str(exc),
            )

        # ── 4. Record in ledger ──────────────────────────────────────────────
        fee = round(locked_size * _DEFAULT_FEE_PCT, 6)
        self._ledger.record(
            LedgerEntry(
                trade_id=trade_id,
                market_id=market_id,
                action=LedgerAction.CLOSE,
                price=close_price,
                size=locked_size,
                fee=fee,
                timestamp=_utc_now(),
                realized_pnl=realized_pnl,
            )
        )

        # ── 5. Update PnLTracker ─────────────────────────────────────────────
        if self._pnl_tracker is not None:
            try:
                self._pnl_tracker.record_realized(
                    market_id=market_id,
                    pnl_usd=realized_pnl,
                    trade_id=trade_id,
                )
            except Exception as exc:
                log.warning(
                    "paper_engine_pnl_tracker_error",
                    trade_id=trade_id,
                    error=str(exc),
                )

        self._processed_trade_ids.add(trade_id)
        elapsed = time.monotonic() - t_start

        if elapsed > _EXECUTION_TIMEOUT_S:
            log.warning(
                "paper_engine_close_slow",
                trade_id=trade_id,
                elapsed_ms=round(elapsed * 1_000, 1),
            )

        log.info(
            "paper_engine_order_closed",
            trade_id=trade_id,
            market_id=market_id,
            side=side,
            close_price=close_price,
            locked_size=locked_size,
            realized_pnl=realized_pnl,
            fee=fee,
            elapsed_ms=round(elapsed * 1_000, 1),
        )

        return PaperOrderResult(
            trade_id=trade_id,
            market_id=market_id,
            side=side,
            requested_size=locked_size,
            filled_size=locked_size,
            fill_price=close_price,
            fee=fee,
            status=OrderStatus.FILLED,
            reason="",
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _validate_order(
        market_id: str,
        side: str,
        price: float,
        size: float,
    ) -> str:
        """Validate order fields.  Returns error string or empty string."""
        if not market_id:
            return "missing_market_id"
        if side not in ("YES", "NO"):
            return f"invalid_side:{side!r}"
        if price <= 0 or price > 1:
            return f"invalid_price:{price}"
        if size <= 0:
            return f"invalid_size:{size}"
        return ""


# ── Helpers ───────────────────────────────────────────────────────────────────


def _utc_now() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
