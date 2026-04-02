"""core.pipeline.trading_loop — Continuous async signal→execution pipeline.

Implements the main polling loop that:

1. Fetches active markets from the Gamma REST API every *loop_interval_s* seconds.
2. Passes markets through :func:`core.signal.generate_signals` to produce edge-filtered
   trading signals.
3. Submits each signal to :func:`core.execution.execute_trade` (paper or live).
4. Logs a heartbeat and signal count on every tick.
5. Gracefully skips iterations where the market fetch fails instead of crashing.

Pipeline per tick::

    get_active_markets()
        │  list[dict] — raw market dicts
        ▼
    generate_signals(markets, bankroll)
        │  list[SignalResult] — edge-filtered, Kelly-sized
        ▼
    for signal in signals:
        execute_trade(signal, ...)
        │  TradeResult — paper sim or real CLOB order
        ▼
    asyncio.sleep(loop_interval_s)

Environment variables (all optional):
    TRADING_MODE             — "PAPER" (default) or "LIVE"
    ENABLE_LIVE_TRADING      — must equal "true" to allow LIVE mode
    TRADING_LOOP_INTERVAL_S  — seconds between loop ticks (default 5)
    TRADING_LOOP_BANKROLL    — bankroll in USD for signal sizing (default 1000)

Usage::

    from core.pipeline.trading_loop import run_trading_loop
    import asyncio

    asyncio.run(run_trading_loop())
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Callable, Awaitable, Optional

import structlog

from ..market.market_client import get_active_markets
from ..signal.signal_engine import generate_signals
from ..execution.executor import execute_trade

log = structlog.get_logger()

# ── Defaults ──────────────────────────────────────────────────────────────────

_DEFAULT_LOOP_INTERVAL_S: float = 5.0
_DEFAULT_BANKROLL: float = 1_000.0


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


# ── Main loop ─────────────────────────────────────────────────────────────────


async def run_trading_loop(
    *,
    loop_interval_s: float | None = None,
    bankroll: float | None = None,
    mode: str | None = None,
    executor_callback: Optional[Callable[..., Awaitable[dict[str, Any]]]] = None,
    telegram_callback: Optional[Callable[[str], Awaitable[None]]] = None,
    stop_event: Optional[asyncio.Event] = None,
) -> None:
    """Run the continuous market→signal→execution trading loop.

    The loop runs indefinitely until *stop_event* is set (or the process is
    terminated).  Every unhandled exception inside a single iteration is
    caught, logged, and skipped — the loop **never crashes**.

    Args:
        loop_interval_s:    Seconds to sleep between ticks.  Reads
                            ``TRADING_LOOP_INTERVAL_S`` env var when *None*.
        bankroll:           USD bankroll for Kelly position sizing.  Reads
                            ``TRADING_LOOP_BANKROLL`` env var when *None*.
        mode:               ``"PAPER"`` or ``"LIVE"``.  Reads ``TRADING_MODE``
                            env var when *None* (default: ``"PAPER"``).
        executor_callback:  Async callable used for LIVE order placement.
                            When *None* in LIVE mode the executor falls back
                            to paper simulation.
        telegram_callback:  Optional async callable ``(message: str)`` invoked
                            after each successful trade execution.
        stop_event:         :class:`asyncio.Event` that stops the loop when set.
                            Primarily used for testing and graceful shutdown.
    """
    _interval = (
        loop_interval_s
        if loop_interval_s is not None
        else _env_float("TRADING_LOOP_INTERVAL_S", _DEFAULT_LOOP_INTERVAL_S)
    )
    _bankroll = (
        bankroll
        if bankroll is not None
        else _env_float("TRADING_LOOP_BANKROLL", _DEFAULT_BANKROLL)
    )
    _mode = (mode or os.getenv("TRADING_MODE", "PAPER")).upper()

    log.info(
        "trading_loop_started",
        mode=_mode,
        bankroll=_bankroll,
        loop_interval_s=_interval,
    )

    while True:
        # ── Check stop signal ─────────────────────────────────────────────────
        if stop_event is not None and stop_event.is_set():
            log.info("trading_loop_stopped")
            break

        log.info("trading_loop_tick", mode=_mode, bankroll=_bankroll)

        try:
            # ── 1. Fetch active markets ────────────────────────────────────────
            markets = await get_active_markets()

            if not markets:
                log.warning(
                    "trading_loop_no_markets",
                    hint="Market fetch returned empty list — skipping iteration",
                )
                await asyncio.sleep(_interval)
                continue

            # ── 2. Generate signals ───────────────────────────────────────────
            signals = await generate_signals(markets, bankroll=_bankroll)

            log.info("signals_generated", count=len(signals))

            # ── 3. Execute each signal ────────────────────────────────────────
            for signal in signals:
                result = await execute_trade(
                    signal,
                    mode=_mode,
                    executor_callback=executor_callback,
                    telegram_callback=telegram_callback,
                )
                if result.success:
                    log.info(
                        "trade_loop_executed",
                        market_id=result.market_id,
                        side=result.side,
                        mode=result.mode,
                        filled_size_usd=round(result.filled_size_usd or 0.0, 4),
                        fill_price=round(result.fill_price or 0.0, 6),
                    )

        except Exception as exc:  # noqa: BLE001
            log.error("pipeline_loop_error", error=str(exc), exc_info=True)

        # ── 4. Rate-control delay ─────────────────────────────────────────────
        await asyncio.sleep(_interval)
