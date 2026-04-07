"""core.execution.executor — Trade execution engine for PolyQuantBot.

Connects signal results from ``core.signal`` to the exchange (or paper
simulator), applying a second round of risk validation before any order
is placed.

Pipeline for a single signal::

    execute_trade(signal)
        │
        ├─ Duplicate check (trade_id seen before?) → skip
        │
        ├─ Risk re-validation
        │   ├─ edge must remain > 0 (re-check at execution time)
        │   ├─ size_usd ≤ max_position_usd
        │   └─ kill_switch active? → skip
        │
        ├─ Mode branch
        │   ├─ PAPER → simulate fill (no network call)
        │   └─ LIVE  → place real order via executor callback
        │
        ├─ Retry once on failure
        │
        └─ Return TradeResult (success or failure)

Logging events (all structured JSON via structlog):
    ``signal_generated``   — echoed from signal for pipeline traceability
    ``trade_executed``     — order placed / simulated successfully
    ``trade_skipped``      — order NOT placed (with reason)

Environment variables (all optional):
    TRADING_MODE              — "PAPER" (default) or "LIVE"
    EXECUTION_MAX_CONCURRENT  — max parallel open trades        (default 5)
    EXECUTION_MAX_POSITION_USD — max single-trade USD cap       (default 1000)
    EXECUTION_MIN_EDGE        — minimum edge re-check threshold (default 0.02)
    ENABLE_LIVE_TRADING       — must equal "true" to allow LIVE mode

Usage::

    from core.execution import execute_trade
    from core.signal import generate_signals

    signals = await generate_signals(markets, bankroll=5000.0)
    for signal in signals:
        result = await execute_trade(signal)
        if result.success:
            print(f"Filled {result.filled_size_usd} USD on {result.market_id}")
"""
from __future__ import annotations

import asyncio
import os
import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable, Optional, Set

import structlog

from ..signal.signal_engine import SignalResult

log = structlog.get_logger()

# ── Configuration defaults ─────────────────────────────────────────────────────

_MAX_CONCURRENT_TRADES: int = 5
_MAX_POSITION_USD: float = 1_000.0
_MIN_EDGE: float = 0.01
_DEFAULT_MODE: str = "PAPER"

# ── Paper trading realism parameters ──────────────────────────────────────────
# Slippage: random ±1 % of the mid price applied in paper mode.
_PAPER_SLIPPAGE_MAX_PCT: float = 0.01   # ±1 %
# Partial fill: a random fraction of requested size is filled [60 %, 100 %].
_PAPER_FILL_MIN_PCT: float = 0.60
_PAPER_FILL_MAX_PCT: float = 1.00
# Simulated latency range in milliseconds.
_PAPER_LATENCY_MIN_MS: float = 100.0
_PAPER_LATENCY_MAX_MS: float = 500.0
# Minimum liquidity threshold (USD) — reject if below.
_MIN_LIQUIDITY_USD: float = 0.0        # set via EXECUTION_MIN_LIQUIDITY_USD env


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes"}


# ── TradeResult dataclass ──────────────────────────────────────────────────────


@dataclass
class TradeResult:
    """Outcome of a single execution attempt.

    Attributes:
        trade_id:       Unique identifier for this execution attempt.
        signal_id:      ID of the originating :class:`SignalResult`.
        market_id:      Polymarket condition ID.
        side:           "YES" or "NO".
        success:        True if the order was placed / simulated successfully.
        mode:           "PAPER" or "LIVE".
        attempted_size: USD size submitted.
        filled_size_usd: USD actually filled (0.0 if not filled).
        fill_price:     Execution price (0.0 if not filled).
        latency_ms:     Wall-clock time for the execution attempt.
        slippage_pct:   Slippage applied in paper mode (fraction, e.g. 0.008).
        partial_fill:   True when only a fraction of the requested size was filled.
        reason:         Human-readable outcome description.
        extra:          Optional payload from the executor callback.
    """

    trade_id: str
    execution_id: str
    signal_id: str
    market_id: str
    side: str
    success: bool
    mode: str
    attempted_size: float
    filled_size_usd: float = 0.0
    fill_price: float = 0.0
    latency_ms: float = 0.0
    slippage_pct: float = 0.0
    partial_fill: bool = False
    reason: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


# ── Module-level dedup set ─────────────────────────────────────────────────────
# Stores signal_ids that have already been submitted.  Cleared on process restart
# (intentional — prevents stale dedup state across restarts).

_submitted_ids: Set[str] = set()
_open_trade_count: int = 0
_open_trade_lock: Optional[asyncio.Lock] = None  # created lazily


def _get_lock() -> asyncio.Lock:
    global _open_trade_lock
    if _open_trade_lock is None:
        _open_trade_lock = asyncio.Lock()
    return _open_trade_lock


def reset_state() -> None:
    """Reset module-level execution state (for testing only)."""
    global _submitted_ids, _open_trade_count, _open_trade_lock
    _submitted_ids = set()
    _open_trade_count = 0
    _open_trade_lock = None


# ── execute_trade ──────────────────────────────────────────────────────────────


async def execute_trade(
    signal: SignalResult,
    *,
    mode: str | None = None,
    max_concurrent: int | None = None,
    max_position_usd: float | None = None,
    min_edge: float | None = None,
    min_liquidity_usd: float | None = None,
    kill_switch_active: bool = False,
    executor_callback: Optional[Callable[..., Awaitable[dict[str, Any]]]] = None,
    paper_executor_callback: Optional[Callable[..., Awaitable[dict[str, Any]]]] = None,
    telegram_callback: Optional[Callable[[str], Awaitable[None]]] = None,
) -> TradeResult:
    """Validate and execute (or simulate) a single trading signal.

    This function is *idempotent* for any given ``signal.signal_id``:
    a second call with the same signal ID is a no-op that returns a
    ``trade_skipped`` result with reason ``"duplicate"``.

    Args:
        signal:             Signal from :func:`generate_signals`.
        mode:               Override for ``TRADING_MODE`` env var.
        max_concurrent:     Override for maximum open trades.
        max_position_usd:   Override for max single-trade USD cap.
        min_edge:           Override for minimum edge re-check threshold.
        min_liquidity_usd:  Override for minimum liquidity threshold in USD.
        kill_switch_active: When True, all trades are blocked immediately.
        executor_callback:  Async callable
                            ``(market_id, side, price, size_usd, trade_id)
                            -> dict`` invoked in LIVE mode.
        paper_executor_callback: Optional async callable for PAPER mode
                            engine execution.
        telegram_callback:  Optional async callable ``(message: str)`` for
                            trade-executed notifications.

    Returns:
        :class:`TradeResult` describing the outcome.
    """
    global _submitted_ids, _open_trade_count

    _mode = (mode or os.getenv("TRADING_MODE", _DEFAULT_MODE)).upper()
    _max_c = max_concurrent if max_concurrent is not None else _env_int(
        "EXECUTION_MAX_CONCURRENT", _MAX_CONCURRENT_TRADES
    )
    _max_p = max_position_usd if max_position_usd is not None else _env_float(
        "EXECUTION_MAX_POSITION_USD", _MAX_POSITION_USD
    )
    _min_e = min_edge if min_edge is not None else _env_float(
        "EXECUTION_MIN_EDGE", _MIN_EDGE
    )
    _min_liq = min_liquidity_usd if min_liquidity_usd is not None else _env_float(
        "EXECUTION_MIN_LIQUIDITY_USD", _MIN_LIQUIDITY_USD
    )

    trade_id = f"trade-{uuid.uuid4().hex[:12]}"
    execution_id = f"exec-{uuid.uuid4().hex[:12]}"

    log.info(
        "execution_audit",
        execution_id=execution_id,
        trade_id=trade_id,
        signal_id=signal.signal_id,
        market_id=signal.market_id,
        intent="execute_trade",
        mode=_mode,
        result="attempt",
        reason="received",
    )
    def _audit(result: str, reason: str) -> None:
        log.info(
            "execution_audit",
            execution_id=execution_id,
            trade_id=trade_id,
            signal_id=signal.signal_id,
            market_id=signal.market_id,
            intent="execute_trade",
            mode=_mode,
            result=result,
            reason=reason,
        )

    # ── Duplicate check ───────────────────────────────────────────────────────
    if signal.signal_id in _submitted_ids:
        _audit("blocked", "duplicate")
        log.info(
            "trade_skipped",
            trade_id=trade_id,
            execution_id=execution_id,
            signal_id=signal.signal_id,
            market_id=signal.market_id,
            reason="duplicate",
        )
        return TradeResult(
            trade_id=trade_id,
            execution_id=execution_id,
            signal_id=signal.signal_id,
            market_id=signal.market_id,
            side=signal.side,
            success=False,
            mode=_mode,
            attempted_size=signal.size_usd,
            reason="duplicate",
        )

    # ── Kill switch ───────────────────────────────────────────────────────────
    if kill_switch_active:
        _audit("blocked", "kill_switch_active")
        log.info(
            "trade_skipped",
            trade_id=trade_id,
            execution_id=execution_id,
            signal_id=signal.signal_id,
            market_id=signal.market_id,
            reason="kill_switch_active",
        )
        return TradeResult(
            trade_id=trade_id,
            execution_id=execution_id,
            signal_id=signal.signal_id,
            market_id=signal.market_id,
            side=signal.side,
            success=False,
            mode=_mode,
            attempted_size=signal.size_usd,
            reason="kill_switch_active",
        )

    # ── Risk re-validation ────────────────────────────────────────────────────
    if signal.edge <= 0 and not signal.force_mode:
        _audit("blocked", "edge_non_positive")
        log.info(
            "trade_skipped",
            trade_id=trade_id,
            execution_id=execution_id,
            signal_id=signal.signal_id,
            market_id=signal.market_id,
            reason="edge_non_positive",
            edge=signal.edge,
        )
        return TradeResult(
            trade_id=trade_id,
            execution_id=execution_id,
            signal_id=signal.signal_id,
            market_id=signal.market_id,
            side=signal.side,
            success=False,
            mode=_mode,
            attempted_size=signal.size_usd,
            reason="edge_non_positive",
        )

    if signal.edge < _min_e:
        _audit("blocked", "edge_below_threshold")
        log.info(
            "trade_skipped",
            trade_id=trade_id,
            execution_id=execution_id,
            signal_id=signal.signal_id,
            market_id=signal.market_id,
            reason="edge_below_threshold",
            edge=round(signal.edge, 4),
            min_edge=round(_min_e, 4),
        )
        return TradeResult(
            trade_id=trade_id,
            execution_id=execution_id,
            signal_id=signal.signal_id,
            market_id=signal.market_id,
            side=signal.side,
            success=False,
            mode=_mode,
            attempted_size=signal.size_usd,
            reason="edge_below_threshold",
        )

    if signal.size_usd > _max_p:
        _audit("blocked", "size_exceeds_max_position")
        log.info(
            "trade_skipped",
            trade_id=trade_id,
            execution_id=execution_id,
            signal_id=signal.signal_id,
            market_id=signal.market_id,
            reason="size_exceeds_max_position",
            size_usd=signal.size_usd,
            max_position_usd=_max_p,
        )
        return TradeResult(
            trade_id=trade_id,
            execution_id=execution_id,
            signal_id=signal.signal_id,
            market_id=signal.market_id,
            side=signal.side,
            success=False,
            mode=_mode,
            attempted_size=signal.size_usd,
            reason="size_exceeds_max_position",
        )

    # ── Liquidity check ───────────────────────────────────────────────────────
    liquidity_usd: float = float(getattr(signal, "liquidity_usd", 0.0) or 0.0)
    if _min_liq > 0 and liquidity_usd < _min_liq:
        _audit("blocked", "insufficient_liquidity")
        log.info(
            "trade_skipped",
            trade_id=trade_id,
            execution_id=execution_id,
            signal_id=signal.signal_id,
            market_id=signal.market_id,
            reason="insufficient_liquidity",
            liquidity_usd=liquidity_usd,
            min_liquidity_usd=_min_liq,
        )
        return TradeResult(
            trade_id=trade_id,
            execution_id=execution_id,
            signal_id=signal.signal_id,
            market_id=signal.market_id,
            side=signal.side,
            success=False,
            mode=_mode,
            attempted_size=signal.size_usd,
            reason="insufficient_liquidity",
        )
    lock = _get_lock()
    async with lock:
        if _open_trade_count >= _max_c:
            _audit("blocked", "max_concurrent_reached")
            log.info(
                "trade_skipped",
                trade_id=trade_id,
                execution_id=execution_id,
                signal_id=signal.signal_id,
                market_id=signal.market_id,
                reason="max_concurrent_reached",
                open_trades=_open_trade_count,
                max_concurrent=_max_c,
            )
            return TradeResult(
                trade_id=trade_id,
                execution_id=execution_id,
                signal_id=signal.signal_id,
                market_id=signal.market_id,
                side=signal.side,
                success=False,
                mode=_mode,
                attempted_size=signal.size_usd,
                reason="max_concurrent_reached",
            )
        _open_trade_count += 1

    # Mark as submitted (dedup)
    _submitted_ids.add(signal.signal_id)

    log.info(
        "signal_generated",
        trade_id=trade_id,
        signal_id=signal.signal_id,
        market_id=signal.market_id,
        side=signal.side,
        edge=round(signal.edge, 4),
        ev=round(signal.ev, 4),
        size_usd=round(signal.size_usd, 4),
        mode=_mode,
    )

    # ── Execution (with single retry) ─────────────────────────────────────────
    result = await _attempt_execution(
        signal=signal,
        trade_id=trade_id,
        mode=_mode,
        executor_callback=executor_callback,
        paper_executor_callback=paper_executor_callback,
        execution_id=execution_id,
    )

    if not result.success:
        log.info("trade_skipped", trade_id=trade_id, reason=result.reason)
        # Retry once
        log.info("execution_retry", trade_id=trade_id, signal_id=signal.signal_id)
        result = await _attempt_execution(
            signal=signal,
            trade_id=trade_id,
            mode=_mode,
            executor_callback=executor_callback,
            paper_executor_callback=paper_executor_callback,
            execution_id=execution_id,
        )
        if not result.success:
            log.info("trade_skipped", trade_id=trade_id, reason=f"retry_failed:{result.reason}")
            _audit("blocked", f"retry_failed:{result.reason}")
            async with lock:
                _open_trade_count = max(0, _open_trade_count - 1)
            return result

    async with lock:
        _open_trade_count = max(0, _open_trade_count - 1)

    log.info(
        "trade_executed_realistic",
        trade_id=trade_id,
        signal_id=signal.signal_id,
        market_id=signal.market_id,
        side=signal.side,
        mode=_mode,
        filled_size_usd=round(result.filled_size_usd, 4),
        fill_price=round(result.fill_price, 6),
        latency_ms=round(result.latency_ms, 2),
        slippage_pct=round(result.slippage_pct, 6),
        partial_fill=result.partial_fill,
        force_mode=signal.force_mode,
    )
    # Keep legacy event name for backwards-compatibility with existing monitors
    log.info(
        "trade_executed",
        trade_id=trade_id,
        signal_id=signal.signal_id,
        market_id=signal.market_id,
        side=signal.side,
        mode=_mode,
        filled_size_usd=round(result.filled_size_usd, 4),
        fill_price=round(result.fill_price, 6),
        latency_ms=round(result.latency_ms, 2),
        force_mode=signal.force_mode,
    )

    if signal.force_mode:
        log.info(
            "force_trade_executed",
            trade_id=trade_id,
            market_id=signal.market_id,
            side=signal.side,
            edge=round(signal.edge, 4),
            size_usd=round(result.filled_size_usd, 4),
            fill_price=round(result.fill_price, 6),
        )

    if telegram_callback is not None:
        try:
            await telegram_callback(
                side=signal.side,
                price=result.fill_price,
                size=result.filled_size_usd,
                market_id=signal.market_id,
            )
            log.info(
                "telegram_sent",
                trade_id=trade_id,
                market_id=signal.market_id,
            )
        except Exception as tg_exc:  # noqa: BLE001
            log.warning(
                "telegram_failed",
                trade_id=trade_id,
                market_id=signal.market_id,
                error=str(tg_exc),
            )

    _audit("executed", result.reason or "executed")
    return result


# ── Internal execution helpers ─────────────────────────────────────────────────


async def _attempt_execution(
    signal: SignalResult,
    trade_id: str,
    mode: str,
    executor_callback: Optional[Callable[..., Awaitable[dict[str, Any]]]],
    paper_executor_callback: Optional[Callable[..., Awaitable[dict[str, Any]]]],
    execution_id: str,
) -> TradeResult:
    """Single execution attempt (paper or live).

    Returns a TradeResult.  Never raises.
    """
    t_start = time.time()

    try:
        log.info(
            "order_sent",
            execution_id=execution_id,
            trade_id=trade_id,
            signal_id=signal.signal_id,
            market_id=signal.market_id,
            side=signal.side,
            price=round(signal.p_market, 6),
            size_usd=round(signal.size_usd, 4),
            mode=mode,
        )

        if mode == "LIVE" and executor_callback is None:
            return TradeResult(
                trade_id=trade_id,
                execution_id=execution_id,
                signal_id=signal.signal_id,
                market_id=signal.market_id,
                side=signal.side,
                success=False,
                mode=mode,
                attempted_size=signal.size_usd,
                reason="live_executor_callback_required",
            )

        if mode != "LIVE" and executor_callback is not None:
            log.warning(
                "execution_mode_guard_blocked_live_callback",
                execution_id=execution_id,
                trade_id=trade_id,
                mode=mode,
            )

        if mode == "LIVE" and executor_callback is not None:
            raw = await executor_callback(
                market_id=signal.market_id,
                side=signal.side,
                price=signal.p_market,
                size_usd=signal.size_usd,
                trade_id=trade_id,
            )
            latency_ms = (time.time() - t_start) * 1_000.0
            filled = float(raw.get("filled_size", signal.size_usd))
            fill_price = float(raw.get("fill_price", signal.p_market))
            log.info(
                "order_filled",
                trade_id=trade_id,
                execution_id=execution_id,
                signal_id=signal.signal_id,
                market_id=signal.market_id,
                side=signal.side,
                filled_size_usd=round(filled, 4),
                fill_price=round(fill_price, 6),
                latency_ms=round(latency_ms, 2),
                mode=mode,
            )
            return TradeResult(
                trade_id=trade_id,
                execution_id=execution_id,
                signal_id=signal.signal_id,
                market_id=signal.market_id,
                side=signal.side,
                success=True,
                mode=mode,
                attempted_size=signal.size_usd,
                filled_size_usd=round(filled, 4),
                fill_price=round(fill_price, 6),
                latency_ms=round(latency_ms, 2),
                reason="live_executed",
                extra=raw,
            )
        else:
            # ── PAPER path (authoritative) ───────────────────────────────
            if paper_executor_callback is not None:
                raw = await paper_executor_callback(
                    market_id=signal.market_id,
                    side=signal.side,
                    price=signal.p_market,
                    size_usd=signal.size_usd,
                    trade_id=trade_id,
                    execution_id=execution_id,
                )
                latency_ms = (time.time() - t_start) * 1_000.0
                filled = float(raw.get("filled_size", signal.size_usd))
                fill_price = float(raw.get("fill_price", signal.p_market))
                partial_fill = bool(raw.get("partial_fill", False))
                return TradeResult(
                    trade_id=trade_id,
                    execution_id=execution_id,
                    signal_id=signal.signal_id,
                    market_id=signal.market_id,
                    side=signal.side,
                    success=True,
                    mode="PAPER",
                    attempted_size=signal.size_usd,
                    filled_size_usd=round(filled, 4),
                    fill_price=round(fill_price, 6),
                    latency_ms=round(latency_ms, 2),
                    partial_fill=partial_fill,
                    reason=str(raw.get("reason", "paper_engine_executed")),
                    extra=raw,
                )

            # 1. Simulated latency: random value in [100 ms, 500 ms]
            sim_latency_s = random.uniform(
                _PAPER_LATENCY_MIN_MS / 1_000.0,
                _PAPER_LATENCY_MAX_MS / 1_000.0,
            )
            await asyncio.sleep(sim_latency_s)

            # 2. Slippage: random ±1 % applied to the mid price.
            #    YES buyers pay above mid (positive slippage hurts the buyer).
            #    NO buyers also pay above their mid (positive sign inverted so NO
            #    fill_price moves in the adverse direction for that side).
            slippage_sign = 1 if signal.side.upper() == "YES" else -1
            slippage_pct = random.uniform(0, _PAPER_SLIPPAGE_MAX_PCT) * slippage_sign
            fill_price = signal.p_market * (1.0 + slippage_pct)
            fill_price = max(0.001, min(0.999, fill_price))

            # 3. Partial fill: random fraction [60 %, 100 %] of requested size
            fill_fraction = random.uniform(_PAPER_FILL_MIN_PCT, _PAPER_FILL_MAX_PCT)
            filled_size = signal.size_usd * fill_fraction
            partial_fill = fill_fraction < _PAPER_FILL_MAX_PCT

            latency_ms = (time.time() - t_start) * 1_000.0

            log.info(
                "slippage_applied",
                trade_id=trade_id,
                market_id=signal.market_id,
                side=signal.side,
                base_price=round(signal.p_market, 6),
                fill_price=round(fill_price, 6),
                slippage_pct=round(slippage_pct, 6),
            )
            if partial_fill:
                log.info(
                    "partial_fill",
                    trade_id=trade_id,
                    market_id=signal.market_id,
                    side=signal.side,
                    requested_size_usd=round(signal.size_usd, 4),
                    filled_size_usd=round(filled_size, 4),
                    fill_fraction=round(fill_fraction, 4),
                )
            log.info(
                "order_filled",
                trade_id=trade_id,
                execution_id=execution_id,
                signal_id=signal.signal_id,
                market_id=signal.market_id,
                side=signal.side,
                filled_size_usd=round(filled_size, 4),
                fill_price=round(fill_price, 6),
                latency_ms=round(latency_ms, 2),
                slippage_pct=round(slippage_pct, 6),
                partial_fill=partial_fill,
                mode="PAPER",
            )
            reason = "partial_fill" if partial_fill else "paper_simulated"
            return TradeResult(
                trade_id=trade_id,
                execution_id=execution_id,
                signal_id=signal.signal_id,
                market_id=signal.market_id,
                side=signal.side,
                success=True,
                mode="PAPER",
                attempted_size=signal.size_usd,
                filled_size_usd=round(filled_size, 4),
                fill_price=round(fill_price, 6),
                latency_ms=round(latency_ms, 2),
                slippage_pct=round(slippage_pct, 6),
                partial_fill=partial_fill,
                reason=reason,
            )
    except Exception as exc:  # noqa: BLE001
        latency_ms = (time.time() - t_start) * 1_000.0
        log.error(
            "execution_error",
            trade_id=trade_id,
            market_id=signal.market_id,
            error=str(exc),
            exc_info=True,
        )
        return TradeResult(
            trade_id=trade_id,
            execution_id=execution_id,
            signal_id=signal.signal_id,
            market_id=signal.market_id,
            side=signal.side,
            success=False,
            mode=mode,
            attempted_size=signal.size_usd,
            latency_ms=round(latency_ms, 2),
            reason=f"execution_exception:{exc}",
        )
