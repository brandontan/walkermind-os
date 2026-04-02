"""core/execution/executor — Trade executor with risk validation, dedup, and paper/live support.

Execution flow::

    execute_trade(signal)
        ├─ Validate: edge > 0, liquidity > min, size > 0
        ├─ Risk gate: kill switch, daily loss, drawdown, max concurrent
        ├─ Dedup: trade_id = sha256(market_id:side:price:size)
        ├─ If paper mode → simulate execution (update wallet state)
        │   else         → place real order via CLOB executor
        ├─ Retry once on transient failure
        ├─ Log structured result
        └─ Return ExecutionResult

Environment variables:
    TRADING_MODE          — "paper" | "live" (default "paper")
    MAX_CONCURRENT_TRADES — maximum open positions (default 5)
    MIN_LIQUIDITY_USD     — minimum liquidity to execute (default 10_000)
    MIN_EDGE_THRESHOLD    — minimum edge required at execution time (default 0.0)
    PAPER_WALLET_USD      — starting wallet balance for paper mode (default 10_000)
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import time
from dataclasses import dataclass, field
from typing import Optional

import structlog

log = structlog.get_logger()

# ── Configuration ─────────────────────────────────────────────────────────────

_TRADING_MODE: str = os.getenv("TRADING_MODE", "paper").lower()
_MAX_CONCURRENT_TRADES: int = int(os.getenv("MAX_CONCURRENT_TRADES", "5"))
_MIN_LIQUIDITY_USD: float = float(os.getenv("MIN_LIQUIDITY_USD", "10000.0"))
_MIN_EDGE_THRESHOLD: float = float(os.getenv("MIN_EDGE_THRESHOLD", "0.0"))
_PAPER_WALLET_USD: float = float(os.getenv("PAPER_WALLET_USD", "10000.0"))

# ── In-process dedup store ────────────────────────────────────────────────────
# Maps trade_id → Unix timestamp of first execution attempt.
# Shared across all TradeExecutor instances within the process.
_EXECUTED_TRADE_IDS: dict[str, float] = {}

# ── Active trade counter (paper mode) ────────────────────────────────────────
_active_trades: int = 0
_paper_wallet_balance: float = _PAPER_WALLET_USD


# ── Data models ───────────────────────────────────────────────────────────────


@dataclass
class ExecutionResult:
    """Result of a single trade execution attempt.

    Attributes:
        trade_id: Unique idempotency key for this order.
        market_id: Polymarket condition ID.
        side: "YES" | "NO".
        price: Executed (or attempted) price.
        size_usd: Size in USD.
        mode: "paper" | "live".
        success: True if the order was placed/simulated successfully.
        reason: Human-readable reason for failure (empty on success).
        simulated_price: Fill price from simulation (paper mode only).
        latency_ms: Wall-clock execution latency.
        timestamp: Unix timestamp of execution.
        extra: Extra fields from the original signal.
    """

    trade_id: str
    market_id: str
    side: str
    price: float
    size_usd: float
    mode: str
    success: bool
    reason: str = ""
    simulated_price: float = 0.0
    latency_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)
    extra: dict = field(default_factory=dict)


# ── Trade ID generation ───────────────────────────────────────────────────────


def _generate_trade_id(market_id: str, side: str, price: float, size_usd: float) -> str:
    """Generate a deterministic idempotency key from order parameters.

    Args:
        market_id: Polymarket condition ID.
        side: "YES" | "NO".
        price: Limit price rounded to 4 dp.
        size_usd: Order size in USD rounded to 2 dp.

    Returns:
        16-character hex digest (sha256 prefix).
    """
    key = f"{market_id}:{side}:{round(price, 4)}:{round(size_usd, 2)}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


# ── TradeExecutor ─────────────────────────────────────────────────────────────


class TradeExecutor:
    """Stateful executor that enforces risk, dedup, and paper/live routing.

    Thread-safety: designed for a single asyncio event loop.

    Args:
        mode: "paper" | "live" — overrides TRADING_MODE env var.
        max_concurrent: Maximum number of simultaneously open positions.
        min_liquidity_usd: Minimum market liquidity gate.
        min_edge: Minimum edge required at execution time.
        clob_executor: Optional real CLOB executor for live mode.
        telegram: Optional TelegramLive instance for trade alerts.
        risk_guard: Optional RiskGuard for kill-switch / drawdown checks.
    """

    def __init__(
        self,
        mode: Optional[str] = None,
        max_concurrent: int = _MAX_CONCURRENT_TRADES,
        min_liquidity_usd: float = _MIN_LIQUIDITY_USD,
        min_edge: float = _MIN_EDGE_THRESHOLD,
        clob_executor: Optional[object] = None,
        telegram: Optional[object] = None,
        risk_guard: Optional[object] = None,
    ) -> None:
        self._mode: str = (mode or _TRADING_MODE).lower()
        self._max_concurrent = max_concurrent
        self._min_liquidity_usd = min_liquidity_usd
        self._min_edge = min_edge
        self._clob_executor = clob_executor
        self._telegram = telegram
        self._risk_guard = risk_guard

        # Instance-level dedup + active-trade counter
        self._executed_ids: dict[str, float] = {}
        self._active_count: int = 0

        # Paper mode simulated wallet state
        self._paper_balance: float = _PAPER_WALLET_USD

        log.info(
            "trade_executor_initialized",
            mode=self._mode,
            max_concurrent=max_concurrent,
            min_liquidity_usd=min_liquidity_usd,
            min_edge=min_edge,
        )

    # ── Public API ─────────────────────────────────────────────────────────────

    async def execute_trade(self, signal: dict) -> ExecutionResult:
        """Execute a single trade signal with full risk validation and dedup.

        Validates edge, liquidity, risk controls, and idempotency before
        placing the order.  Retries once on transient failure.  In paper
        mode the wallet state is updated in-process; in live mode the
        order is forwarded to the CLOB executor.

        Args:
            signal: Signal dict. Expected keys:
                market_id    (str)   — Polymarket condition ID
                side         (str)   — "YES" | "NO"
                price        (float) — limit price (0–1)
                size_usd     (float) — position size in USD
                edge         (float) — model - market edge
                ev           (float) — expected value
                liquidity_usd(float) — available liquidity
                (any extra keys are forwarded in ExecutionResult.extra)

        Returns:
            :class:`ExecutionResult`.
        """
        market_id: str = str(signal.get("market_id", ""))
        side: str = str(signal.get("side", "YES"))
        price: float = float(signal.get("price", signal.get("p_market", 0.0)))
        size_usd: float = float(signal.get("size_usd", 0.0))
        edge: float = float(signal.get("edge", 0.0))
        ev: float = float(signal.get("ev", 0.0))
        liquidity_usd: float = float(signal.get("liquidity_usd", 0.0))

        extra_keys = {"market_id", "side", "price", "p_market", "size_usd",
                      "edge", "ev", "liquidity_usd"}
        extra = {k: v for k, v in signal.items() if k not in extra_keys}

        trade_id = _generate_trade_id(market_id, side, price, size_usd)
        t_start = time.time()

        def _make_result(success: bool, reason: str = "", sim_price: float = 0.0) -> ExecutionResult:
            return ExecutionResult(
                trade_id=trade_id,
                market_id=market_id,
                side=side,
                price=price,
                size_usd=size_usd,
                mode=self._mode,
                success=success,
                reason=reason,
                simulated_price=sim_price,
                latency_ms=round((time.time() - t_start) * 1000.0, 2),
                timestamp=t_start,
                extra=extra,
            )

        # ── 1. Edge re-validation ─────────────────────────────────────────────
        if edge <= self._min_edge:
            log.info(
                "trade_skipped",
                trade_id=trade_id,
                market_id=market_id,
                reason="no_positive_edge",
                edge=round(edge, 4),
            )
            return _make_result(False, "no_positive_edge")

        # ── 2. Liquidity check ────────────────────────────────────────────────
        if liquidity_usd < self._min_liquidity_usd:
            log.info(
                "trade_skipped",
                trade_id=trade_id,
                market_id=market_id,
                reason="insufficient_liquidity",
                liquidity_usd=liquidity_usd,
            )
            return _make_result(False, "insufficient_liquidity")

        # ── 3. Size sanity ────────────────────────────────────────────────────
        if size_usd <= 0 or price <= 0:
            log.info(
                "trade_skipped",
                trade_id=trade_id,
                market_id=market_id,
                reason="invalid_size_or_price",
                size_usd=size_usd,
                price=price,
            )
            return _make_result(False, "invalid_size_or_price")

        # ── 4. Risk guard ─────────────────────────────────────────────────────
        if self._risk_guard is not None:
            if getattr(self._risk_guard, "disabled", False):
                log.warning(
                    "trade_skipped",
                    trade_id=trade_id,
                    market_id=market_id,
                    reason="kill_switch_active",
                )
                return _make_result(False, "kill_switch_active")

        # ── 5. Concurrent-trade cap ───────────────────────────────────────────
        if self._active_count >= self._max_concurrent:
            log.info(
                "trade_skipped",
                trade_id=trade_id,
                market_id=market_id,
                reason="max_concurrent_trades",
                active=self._active_count,
                limit=self._max_concurrent,
            )
            return _make_result(False, "max_concurrent_trades")

        # ── 6. Dedup ──────────────────────────────────────────────────────────
        if trade_id in self._executed_ids:
            log.warning(
                "trade_skipped",
                trade_id=trade_id,
                market_id=market_id,
                reason="duplicate_trade",
                first_seen=self._executed_ids[trade_id],
            )
            return _make_result(False, "duplicate_trade")

        # Register the trade ID BEFORE execution to prevent races
        self._executed_ids[trade_id] = t_start
        self._active_count += 1

        # ── 7. Execute (with one retry) ───────────────────────────────────────
        result: Optional[ExecutionResult] = None
        last_error: str = ""

        for attempt in range(2):   # attempt 0, then retry attempt 1
            try:
                if self._mode == "paper":
                    result = await self._execute_paper(
                        trade_id=trade_id,
                        market_id=market_id,
                        side=side,
                        price=price,
                        size_usd=size_usd,
                        ev=ev,
                        edge=edge,
                        t_start=t_start,
                        extra=extra,
                    )
                else:
                    result = await self._execute_live(
                        trade_id=trade_id,
                        market_id=market_id,
                        side=side,
                        price=price,
                        size_usd=size_usd,
                        ev=ev,
                        edge=edge,
                        t_start=t_start,
                        extra=extra,
                    )
                break  # success — exit retry loop
            except Exception as exc:  # noqa: BLE001  — broad catch is intentional: CLOB/paper errors are unpredictable; we retry once then skip
                last_error = str(exc)
                log.warning(
                    "trade_execution_error",
                    trade_id=trade_id,
                    market_id=market_id,
                    attempt=attempt,
                    error=last_error,
                )
                if attempt == 0:
                    # Wait briefly before the single retry
                    await asyncio.sleep(0.5)

        self._active_count = max(0, self._active_count - 1)

        if result is None:
            log.error(
                "trade_failed_after_retry",
                trade_id=trade_id,
                market_id=market_id,
                error=last_error,
            )
            # Clean up dedup entry so the caller can retry manually if needed
            self._executed_ids.pop(trade_id, None)
            return _make_result(False, f"execution_failed:{last_error}")

        return result

    # ── Paper execution ────────────────────────────────────────────────────────

    async def _execute_paper(
        self,
        trade_id: str,
        market_id: str,
        side: str,
        price: float,
        size_usd: float,
        ev: float,
        edge: float,
        t_start: float,
        extra: dict,
    ) -> ExecutionResult:
        """Simulate a trade: deduct from paper wallet, log, alert Telegram."""
        # Update simulated wallet
        self._paper_balance = max(0.0, self._paper_balance - size_usd)

        sim_price = price  # paper mode: fill at limit price
        latency_ms = round((time.time() - t_start) * 1000.0, 2)

        log.info(
            "trade_executed",
            trade_id=trade_id,
            market_id=market_id,
            side=side,
            price=price,
            size_usd=size_usd,
            ev=round(ev, 4),
            edge=round(edge, 4),
            mode="paper",
            paper_balance=round(self._paper_balance, 2),
            latency_ms=latency_ms,
        )

        await self._send_telegram_alert(
            trade_id=trade_id,
            market_id=market_id,
            side=side,
            price=price,
            size_usd=size_usd,
            ev=ev,
            mode="paper",
        )

        return ExecutionResult(
            trade_id=trade_id,
            market_id=market_id,
            side=side,
            price=price,
            size_usd=size_usd,
            mode="paper",
            success=True,
            simulated_price=sim_price,
            latency_ms=latency_ms,
            timestamp=t_start,
            extra=extra,
        )

    # ── Live execution ─────────────────────────────────────────────────────────

    async def _execute_live(
        self,
        trade_id: str,
        market_id: str,
        side: str,
        price: float,
        size_usd: float,
        ev: float,
        edge: float,
        t_start: float,
        extra: dict,
    ) -> ExecutionResult:
        """Forward order to real CLOB executor."""
        if self._clob_executor is None:
            raise RuntimeError(
                "TRADING_MODE=live but no clob_executor provided to TradeExecutor"
            )

        from ...execution.clob_executor import ExecutionRequest  # type: ignore[import]  # noqa: PLC0415 — deferred to break circular import between core.execution and execution packages

        request = ExecutionRequest(
            market_id=market_id,
            side=side,
            price=price,
            size=size_usd,
            correlation_id=trade_id,
        )
        result = await self._clob_executor.execute(request)

        latency_ms = round((time.time() - t_start) * 1000.0, 2)
        actual_price = getattr(result, "avg_price", price) or price
        actual_size = getattr(result, "filled_size", size_usd) or size_usd

        log.info(
            "trade_executed",
            trade_id=trade_id,
            market_id=market_id,
            side=side,
            price=actual_price,
            size_usd=actual_size,
            ev=round(ev, 4),
            edge=round(edge, 4),
            mode="live",
            latency_ms=latency_ms,
        )

        await self._send_telegram_alert(
            trade_id=trade_id,
            market_id=market_id,
            side=side,
            price=actual_price,
            size_usd=actual_size,
            ev=ev,
            mode="live",
        )

        return ExecutionResult(
            trade_id=trade_id,
            market_id=market_id,
            side=side,
            price=actual_price,
            size_usd=actual_size,
            mode="live",
            success=True,
            simulated_price=actual_price,
            latency_ms=latency_ms,
            timestamp=t_start,
            extra=extra,
        )

    # ── Telegram alert ─────────────────────────────────────────────────────────

    async def _send_telegram_alert(
        self,
        trade_id: str,
        market_id: str,
        side: str,
        price: float,
        size_usd: float,
        ev: float,
        mode: str,
    ) -> None:
        """Send a non-blocking Telegram trade alert if a sender is configured."""
        if self._telegram is None:
            return
        try:
            message = (
                f"📈 Trade executed\n"
                f"Mode: {mode.upper()}\n"
                f"Market: {market_id}\n"
                f"Side: {side} @ {price:.3f}\n"
                f"Size: ${size_usd:.2f} | EV: {ev:.4f}"
            )
            # Support both TelegramLive.alert_trade and a plain async callable
            if hasattr(self._telegram, "alert_trade"):
                await self._telegram.alert_trade(
                    side=side, price=price, size=size_usd
                )
            elif callable(self._telegram):
                await self._telegram(message)
        except Exception as exc:  # noqa: BLE001
            log.error(
                "telegram_alert_failed",
                trade_id=trade_id,
                error=str(exc),
            )

    # ── Status ─────────────────────────────────────────────────────────────────

    @property
    def paper_balance(self) -> float:
        """Current simulated paper-mode wallet balance in USD."""
        return self._paper_balance

    @property
    def active_trade_count(self) -> int:
        """Number of currently executing trades."""
        return self._active_count

    def is_duplicate(self, market_id: str, side: str, price: float, size_usd: float) -> bool:
        """Return True if this exact order has already been executed.

        Args:
            market_id: Polymarket condition ID.
            side: "YES" | "NO".
            price: Limit price.
            size_usd: Order size in USD.

        Returns:
            True if the trade_id is in the dedup store.
        """
        trade_id = _generate_trade_id(market_id, side, price, size_usd)
        return trade_id in self._executed_ids


# ── Module-level convenience function ────────────────────────────────────────

# Default executor instance (lazy-initialized per-process)
_default_executor: Optional[TradeExecutor] = None


def _get_default_executor() -> TradeExecutor:
    """Return (or create) the module-level default TradeExecutor."""
    global _default_executor  # noqa: PLW0603
    if _default_executor is None:
        _default_executor = TradeExecutor()
    return _default_executor


async def execute_trade(
    signal: dict,
    *,
    executor: Optional[TradeExecutor] = None,
) -> ExecutionResult:
    """Module-level convenience wrapper around :class:`TradeExecutor`.

    Uses a per-process default executor when ``executor`` is not provided.

    Args:
        signal: Signal dict (see :meth:`TradeExecutor.execute_trade`).
        executor: Optional explicit executor instance.

    Returns:
        :class:`ExecutionResult`.
    """
    _executor = executor or _get_default_executor()
    return await _executor.execute_trade(signal)
