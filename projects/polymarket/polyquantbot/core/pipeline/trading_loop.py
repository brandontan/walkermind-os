"""core.pipeline.trading_loop — Continuous async signal→execution pipeline.

Implements the main polling loop that:

1. Fetches active markets from the Gamma REST API every *loop_interval_s* seconds.
2. Feeds market prices into a :class:`ProbabilisticAlphaModel` (``record_tick``).
3. Passes markets through :func:`core.signal.generate_signals` with the live alpha
   model to produce edge-filtered trading signals.
4. Submits each signal to :func:`core.execution.execute_trade` (paper or live).
5. After each successful fill, upserts the position and updates the trade status in
   the database.
6. Computes unrealized PnL and performance metrics at the end of every tick and logs
   them as structured JSON.
7. Logs a heartbeat and signal count on every tick.
8. Gracefully skips iterations where the market fetch fails instead of crashing.

Pipeline per tick::

    get_active_markets()
        │  list[dict] — raw market dicts
        ▼
    alpha_model.record_tick(market_id, price)   ← per market
        │
        ▼
    generate_signals(markets, bankroll, alpha_model=alpha_model)
        │  list[SignalResult] — edge-filtered, Kelly-sized, real-alpha
        ▼
    for signal in signals:
        execute_trade(signal, ...)
        │  TradeResult — paper sim or real CLOB order
        ▼
        db.upsert_position(...)  ← on success
        db.update_trade_status(...)
        ▼
    db.get_positions(user_id)
    PnLCalculator.calculate_unrealized_pnl(...)
    PnLCalculator.calculate_metrics(...)
    log.info("pnl_update", pnl=metrics)
        ▼
    asyncio.sleep(loop_interval_s)

Environment variables (all optional):
    TRADING_MODE             — "PAPER" (default) or "LIVE"
    ENABLE_LIVE_TRADING      — must equal "true" to allow LIVE mode
    TRADING_LOOP_INTERVAL_S  — seconds between loop ticks (default 5)
    TRADING_LOOP_BANKROLL    — bankroll in USD for signal sizing (default 1000)
    TRADING_LOOP_USER_ID     — user ID for position/PnL tracking (default "default")

Usage::

    from core.pipeline.trading_loop import run_trading_loop
    import asyncio

    asyncio.run(run_trading_loop())
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Callable, Awaitable, Optional

import structlog

from ..market.market_client import get_active_markets
from ..signal.signal_engine import generate_signals
from ..signal.alpha_model import ProbabilisticAlphaModel
from ..execution.executor import execute_trade
from ...monitoring.pnl_calculator import PnLCalculator

log = structlog.get_logger()

# ── Defaults ──────────────────────────────────────────────────────────────────

_DEFAULT_LOOP_INTERVAL_S: float = 5.0
_DEFAULT_BANKROLL: float = 1_000.0
_DEFAULT_USER_ID: str = "default"


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
    db: Optional[Any] = None,
    user_id: Optional[str] = None,
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
        db:                 Optional :class:`infra.db.DatabaseClient` instance.
                            When provided, positions and trade statuses are
                            persisted and PnL is computed each tick.
        user_id:            User identifier for position/PnL tracking.  Reads
                            ``TRADING_LOOP_USER_ID`` env var when *None*.
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
    _user_id = user_id or os.getenv("TRADING_LOOP_USER_ID", _DEFAULT_USER_ID)

    # ── Initialise alpha model (stateful, shared across ticks) ────────────────
    alpha_model = ProbabilisticAlphaModel()

    log.info(
        "trading_loop_started",
        mode=_mode,
        bankroll=_bankroll,
        loop_interval_s=_interval,
        user_id=_user_id,
        db_enabled=db is not None,
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

            # ── 2. Feed price data into alpha model ───────────────────────────
            market_prices: dict[str, float] = {}
            for market in markets:
                _cond_id = market.get("conditionId")
                market_id: str = str(
                    _cond_id if _cond_id is not None else market.get("condition_id") or ""
                )
                if not market_id:
                    continue
                _raw_price = market.get("lastTradePrice")
                price: float = float(
                    _raw_price if _raw_price is not None else market.get("price") or 0.0
                )
                if price > 0.0:
                    alpha_model.record_tick(market_id, price)
                    market_prices[market_id] = price

            # ── 3. Generate signals (with real alpha) ─────────────────────────
            signals = await generate_signals(
                markets,
                bankroll=_bankroll,
                alpha_model=alpha_model,
            )

            log.info("signals_generated", count=len(signals))

            # ── 4. Execute each signal and update positions ───────────────────
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

                    # ── 4a. Persist position ──────────────────────────────────
                    if db is not None and result.fill_price > 0.0:
                        await db.upsert_position({
                            "user_id": _user_id,
                            "market_id": result.market_id,
                            "avg_price": result.fill_price,
                            "size": result.filled_size_usd,
                        })

                        # ── 4b. Record trade in DB and set status ─────────────
                        await db.insert_trade({
                            "trade_id": result.trade_id,
                            "user_id": _user_id,
                            "strategy_id": signal.extra.get("strategy_id", ""),
                            "market_id": result.market_id,
                            "side": result.side,
                            "size_usd": result.filled_size_usd,
                            "price": result.fill_price,
                            "entry_price": result.fill_price,
                            "expected_ev": signal.ev,
                            "pnl": 0.0,
                            "won": False,
                            "status": "open",
                            "mode": result.mode,
                            "executed_at": time.time(),
                        })

                        await db.update_trade_status(result.trade_id, "open")

            # ── 5. Compute and log PnL metrics ────────────────────────────────
            if db is not None:
                try:
                    positions = await db.get_positions(_user_id)
                    trades = await db.get_recent_trades(limit=500)

                    unrealized = PnLCalculator.calculate_unrealized_pnl(
                        positions, market_prices
                    )
                    metrics = PnLCalculator.calculate_metrics(trades)
                    metrics["unrealized_pnl"] = unrealized

                    log.info("pnl_update", pnl=metrics)
                except Exception as pnl_exc:  # noqa: BLE001
                    log.error(
                        "pnl_update_error",
                        error=str(pnl_exc),
                        exc_info=True,
                    )

        except Exception as exc:  # noqa: BLE001
            log.error("pipeline_loop_error", error=str(exc), exc_info=True)

        # ── 6. Rate-control delay ─────────────────────────────────────────────
        await asyncio.sleep(_interval)
