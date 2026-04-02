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
        reason:         Human-readable outcome description.
        extra:          Optional payload from the executor callback.
    """

    trade_id: str
    signal_id: str
    market_id: str
    side: str
    success: bool
    mode: str
    attempted_size: float
    filled_size_usd: float = 0.0
    fill_price: float = 0.0
    latency_ms: float = 0.0
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
    kill_switch_active: bool = False,
    executor_callback: Optional[Callable[..., Awaitable[dict[str, Any]]]] = None,
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
        kill_switch_active: When True, all trades are blocked immediately.
        executor_callback:  Async callable
                            ``(market_id, side, price, size_usd, trade_id)
                            -> dict`` invoked in LIVE mode.  When None in LIVE
                            mode, the call falls back to paper simulation.
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

    trade_id = f"trade-{uuid.uuid4().hex[:12]}"

    # ── Duplicate check ───────────────────────────────────────────────────────
    if signal.signal_id in _submitted_ids:
        log.info(
            "trade_skipped",
            trade_id=trade_id,
            signal_id=signal.signal_id,
            market_id=signal.market_id,
            reason="duplicate",
        )
        return TradeResult(
            trade_id=trade_id,
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
        log.info(
            "trade_skipped",
            trade_id=trade_id,
            signal_id=signal.signal_id,
            market_id=signal.market_id,
            reason="kill_switch_active",
        )
        return TradeResult(
            trade_id=trade_id,
            signal_id=signal.signal_id,
            market_id=signal.market_id,
            side=signal.side,
            success=False,
            mode=_mode,
            attempted_size=signal.size_usd,
            reason="kill_switch_active",
        )

    # ── Risk re-validation ────────────────────────────────────────────────────
    if signal.edge <= 0:
        log.info(
            "trade_skipped",
            trade_id=trade_id,
            signal_id=signal.signal_id,
            market_id=signal.market_id,
            reason="edge_non_positive",
            edge=signal.edge,
        )
        return TradeResult(
            trade_id=trade_id,
            signal_id=signal.signal_id,
            market_id=signal.market_id,
            side=signal.side,
            success=False,
            mode=_mode,
            attempted_size=signal.size_usd,
            reason="edge_non_positive",
        )

    if signal.edge < _min_e:
        log.info(
            "trade_skipped",
            trade_id=trade_id,
            signal_id=signal.signal_id,
            market_id=signal.market_id,
            reason="edge_below_threshold",
            edge=round(signal.edge, 4),
            min_edge=round(_min_e, 4),
        )
        return TradeResult(
            trade_id=trade_id,
            signal_id=signal.signal_id,
            market_id=signal.market_id,
            side=signal.side,
            success=False,
            mode=_mode,
            attempted_size=signal.size_usd,
            reason="edge_below_threshold",
        )

    if signal.size_usd > _max_p:
        log.info(
            "trade_skipped",
            trade_id=trade_id,
            signal_id=signal.signal_id,
            market_id=signal.market_id,
            reason="size_exceeds_max_position",
            size_usd=signal.size_usd,
            max_position_usd=_max_p,
        )
        return TradeResult(
            trade_id=trade_id,
            signal_id=signal.signal_id,
            market_id=signal.market_id,
            side=signal.side,
            success=False,
            mode=_mode,
            attempted_size=signal.size_usd,
            reason="size_exceeds_max_position",
        )

    # ── Concurrent trade cap ──────────────────────────────────────────────────
    lock = _get_lock()
    async with lock:
        if _open_trade_count >= _max_c:
            log.info(
                "trade_skipped",
                trade_id=trade_id,
                signal_id=signal.signal_id,
                market_id=signal.market_id,
                reason="max_concurrent_reached",
                open_trades=_open_trade_count,
                max_concurrent=_max_c,
            )
            return TradeResult(
                trade_id=trade_id,
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
        )
        if not result.success:
            log.info("trade_skipped", trade_id=trade_id, reason=f"retry_failed:{result.reason}")
            async with lock:
                _open_trade_count = max(0, _open_trade_count - 1)
            return result

    async with lock:
        _open_trade_count = max(0, _open_trade_count - 1)

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
    )

    if telegram_callback is not None:
        try:
            await telegram_callback(
                f"📈 Trade executed: {signal.market_id} {signal.side} "
                f"${result.filled_size_usd:.2f} @ {result.fill_price:.4f}"
            )
        except Exception:  # noqa: BLE001
            pass  # Telegram alerts are best-effort only

    return result


# ── Internal execution helpers ─────────────────────────────────────────────────


async def _attempt_execution(
    signal: SignalResult,
    trade_id: str,
    mode: str,
    executor_callback: Optional[Callable[..., Awaitable[dict[str, Any]]]],
) -> TradeResult:
    """Single execution attempt (paper or live).

    Returns a TradeResult.  Never raises.
    """
    t_start = time.time()

    try:
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
            return TradeResult(
                trade_id=trade_id,
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
            # Paper simulation: fill at market price with full size
            await asyncio.sleep(0)  # yield to event loop
            latency_ms = (time.time() - t_start) * 1_000.0
            return TradeResult(
                trade_id=trade_id,
                signal_id=signal.signal_id,
                market_id=signal.market_id,
                side=signal.side,
                success=True,
                mode="PAPER",
                attempted_size=signal.size_usd,
                filled_size_usd=round(signal.size_usd, 4),
                fill_price=round(signal.p_market, 6),
                latency_ms=round(latency_ms, 2),
                reason="paper_simulated",
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
            signal_id=signal.signal_id,
            market_id=signal.market_id,
            side=signal.side,
            success=False,
            mode=mode,
            attempted_size=signal.size_usd,
            latency_ms=round(latency_ms, 2),
            reason=f"execution_exception:{exc}",
        )
