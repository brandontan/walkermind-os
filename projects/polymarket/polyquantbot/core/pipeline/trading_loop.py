"""core.pipeline.trading_loop — Continuous async signal→execution pipeline.

Implements the main polling loop that:

1. Fetches active markets from the Gamma REST API every *loop_interval_s* seconds.
2. Feeds market prices into a :class:`ProbabilisticAlphaModel` (``record_tick``).
3. Passes markets through :func:`core.signal.generate_signals` with the live alpha
   model to produce edge-filtered trading signals.
4. Submits each signal to :func:`core.execution.execute_trade` (paper or live),
   subject to max open positions and per-market cooldown guards.
5. After each successful fill, upserts the position in the database, updates the
   in-memory :class:`PositionManager`, and records unrealized PnL via
   :class:`PnLTracker`.
6. Computes unrealized PnL and performance metrics at the end of every tick and logs
   them as structured JSON.  Sends a Telegram PnL summary if a callback is provided.
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
        guard: open positions < MAX_OPEN_POSITIONS
        guard: market cooldown (30 s since last trade on same market)
        market_cache.get(market_id)  ← non-blocking metadata lookup
        execute_trade(signal, ...)
        │  TradeResult — paper sim or real CLOB order
        ▼
        db.upsert_position(...)  ← on success
        position_manager.open(...)  ← update in-memory position
        pnl_tracker.record_unrealized(...)
        telegram_callback(enriched_trade_message)
        ▼
    db.get_positions(user_id)
    PnLCalculator.calculate_unrealized_pnl(...)
    PnLCalculator.calculate_metrics(...)
    log.info("pnl_update", pnl=metrics)
    telegram_callback(pnl_summary)   ← if provided
        ▼
    asyncio.sleep(loop_interval_s)

Environment variables (all optional):
    TRADING_MODE             — "PAPER" (default) or "LIVE"
    ENABLE_LIVE_TRADING      — must equal "true" to allow LIVE mode
    TRADING_LOOP_INTERVAL_S  — target seconds between loop ticks (default 5; minimum 1)
    TRADING_LOOP_BANKROLL    — bankroll in USD for signal sizing (default 1000)
    TRADING_LOOP_USER_ID     — user ID for position/PnL tracking (default "default")
    TRADING_LOOP_MAX_POSITIONS — max simultaneous open positions (default 5)
    TRADING_LOOP_COOLDOWN_S  — per-market cooldown seconds (default 30)
    FORCE_SIGNAL_MODE        — when "true", bypass signal filters and force at most
                               1 trade per loop tick (for pipeline debugging);
                               **disabled by default** — must be explicitly set

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

from ..market.market_client import get_active_markets, extract_market_data
from ..market.ingest import ingest_markets
from ..signal.signal_engine import generate_signals, generate_synthetic_signals
from ..signal.alpha_model import ProbabilisticAlphaModel
from ..execution.executor import execute_trade
from ...monitoring.pnl_calculator import PnLCalculator
from ..logging.logger import (
    log_market_metadata_used,
    log_position_updated,
    log_pnl_updated,
    log_telegram_trade_detailed,
    log_loop_duration,
    log_loop_throttled,
)
from ...telegram.message_formatter import format_trade_alert

log = structlog.get_logger()

# ── Defaults ──────────────────────────────────────────────────────────────────

_DEFAULT_LOOP_INTERVAL_S: float = 5.0
_DEFAULT_BANKROLL: float = 1_000.0
_DEFAULT_USER_ID: str = "default"

# ── Exit trigger thresholds ───────────────────────────────────────────────────

_DEFAULT_TP_PCT: float = 0.15   # Take-profit: +15% unrealized gain
_DEFAULT_SL_PCT: float = 0.08   # Stop-loss: -8% unrealized loss
_DEFAULT_MAX_OPEN_POSITIONS: int = 5
_DEFAULT_COOLDOWN_S: float = 30.0
_MIN_LOOP_INTERVAL_S: float = 1.0       # absolute floor — loop must never run faster than 1 s
_FAST_LOOP_GUARD_S: float = 0.5         # if a tick finishes in < 0.5 s, force an extra sleep
_MAX_MARKETS_PER_TICK: int = 50         # expanded from 20 → 50 for broader market coverage
_NO_TRADE_FALLBACK_S: float = 1800.0    # 30 minutes — activate force mode when no trade in this window
_FORCE_TRADE_COOLDOWN_S: float = 300.0  # 5 minutes per-market guard when in force-trade fallback


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes"}


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
    market_cache: Optional[Any] = None,
    position_manager: Optional[Any] = None,
    pnl_tracker: Optional[Any] = None,
    paper_engine: Optional[Any] = None,
    tp_pct: float = _DEFAULT_TP_PCT,
    sl_pct: float = _DEFAULT_SL_PCT,
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
                            after each successful trade execution and for PnL
                            summaries.  Always called with a pre-formatted string.
        stop_event:         :class:`asyncio.Event` that stops the loop when set.
                            Primarily used for testing and graceful shutdown.
        db:                 Optional :class:`infra.db.DatabaseClient` instance.
                            When provided, positions and trade statuses are
                            persisted and PnL is computed each tick.
        user_id:            User identifier for position/PnL tracking.  Reads
                            ``TRADING_LOOP_USER_ID`` env var when *None*.
        market_cache:       Optional :class:`core.market.market_cache.MarketMetadataCache`
                            instance.  When provided, market questions and outcomes
                            are resolved from cache for enriched Telegram alerts.
        position_manager:   Optional :class:`core.portfolio.position_manager.PositionManager`
                            instance.  When provided, in-memory position tracking
                            and weighted average price are maintained.
        pnl_tracker:        Optional :class:`core.portfolio.pnl.PnLTracker` instance.
                            When provided, realized and unrealized PnL are tracked
                            and persisted across trades.
        paper_engine:       Optional :class:`execution.paper_engine.PaperEngine`
                            instance.  When provided (PAPER mode), every successful
                            fill is forwarded to ``PaperEngine.execute_order()`` so
                            the wallet, paper positions, and trade ledger are kept
                            in sync with real execution state.
    """
    # ── Enforce database — no silent fallback ─────────────────────────────────
    if db is None:
        raise RuntimeError(
            "Database required — db must not be None. "
            "Inject a connected DatabaseClient before starting the trading loop."
        )

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
    _max_open_positions = _env_int("TRADING_LOOP_MAX_POSITIONS", _DEFAULT_MAX_OPEN_POSITIONS)
    _cooldown_s = _env_float("TRADING_LOOP_COOLDOWN_S", _DEFAULT_COOLDOWN_S)
    _force_signal = _env_bool("FORCE_SIGNAL_MODE", False)

    # ── Initialise alpha model (stateful, shared across ticks) ────────────────
    alpha_model = ProbabilisticAlphaModel()

    # ── Per-market cooldown tracker: market_id → last trade timestamp ─────────
    _market_last_trade: dict[str, float] = {}

    # ── Force-trade fallback: track last successful trade timestamp ───────────
    # When no trade fires for _NO_TRADE_FALLBACK_S (30 min), we lower edge
    # threshold and activate synthetic signal mode for 1 pass.
    _last_trade_time: float = time.time()

    # ── Loop state ────────────────────────────────────────────────────────────
    _tick: int = 0

    log.info(
        "trading_loop_started",
        mode=_mode,
        bankroll=_bankroll,
        loop_interval_s=_interval,
        min_loop_interval_s=_MIN_LOOP_INTERVAL_S,
        max_markets_per_tick=_MAX_MARKETS_PER_TICK,
        user_id=_user_id,
        max_open_positions=_max_open_positions,
        cooldown_s=_cooldown_s,
        db_enabled=True,
        force_signal_mode=_force_signal,
        paper_engine_wired=paper_engine is not None,
    )
    log.info("db_enabled", status=True)

    while True:
        # ── Check stop signal ─────────────────────────────────────────────────
        if stop_event is not None and stop_event.is_set():
            log.info("trading_loop_stopped")
            break

        _tick_start: float = time.monotonic()
        log.info("trading_loop_tick", tick=_tick, mode=_mode, bankroll=_bankroll)

        _retry_count: int = 0
        _max_retries: int = 3
        normalised_markets: list[dict] = []
        signals: list = []

        while _retry_count <= _max_retries:
            try:
                # ── 1. Fetch active markets ────────────────────────────────────────
                markets = await get_active_markets()

                if not markets:
                    log.warning(
                        "trading_loop_no_markets",
                        hint="Market fetch returned empty list — skipping iteration",
                    )
                    break

                log.info("market_feed", count=len(markets))

                # ── 1a. Debug: log first 3 raw markets (temp) ─────────────────────
                # TODO: remove once production data structure is confirmed stable
                for _raw in markets[:3]:
                    log.info("market_raw_sample", data=_raw)

                # ── 1b. Parse and normalise markets ───────────────────────────────
                normalised_markets = ingest_markets(markets)
                for m in normalised_markets:
                    log.info(
                        "market_valid",
                        market_id=m["market_id"],
                        p_market=m["p_market"],
                    )

                if not normalised_markets:
                    log.warning(
                        "trading_loop_no_valid_markets",
                        hint="All markets failed extract_market_data — skipping iteration",
                    )
                    break

                # ── 1c. Limit markets per tick ────────────────────────────────────
                if len(normalised_markets) > _MAX_MARKETS_PER_TICK:
                    log.info(
                        "markets_capped",
                        original_count=len(normalised_markets),
                        capped_to=_MAX_MARKETS_PER_TICK,
                    )
                    normalised_markets = normalised_markets[:_MAX_MARKETS_PER_TICK]

                # ── 2. Feed price data into alpha model ───────────────────────────
                market_prices: dict[str, float] = {}
                for market in normalised_markets:
                    market_id: str = market["market_id"]
                    price: float = market["p_market"]
                    alpha_model.record_tick(market_id, price)
                    market_prices[market_id] = price

                # ── 3. Generate signals (with real alpha) ─────────────────────────
                # Force-trade fallback: if no trade in 30 min, activate force mode
                _now_ts = time.time()
                _time_since_trade = _now_ts - _last_trade_time
                _force_trade_fallback = _time_since_trade >= _NO_TRADE_FALLBACK_S
                _active_force = _force_signal or _force_trade_fallback

                if _force_trade_fallback and not _force_signal:
                    log.warning(
                        "force_trade_fallback_active",
                        time_since_last_trade_s=round(_time_since_trade, 1),
                        threshold_s=_NO_TRADE_FALLBACK_S,
                        hint="No trade in 30 min — activating low-confidence fallback",
                    )

                # PAPER mode: use lower edge threshold (0.5%) for more signal generation
                _paper_edge_override: float | None = None
                if _mode == "PAPER":
                    _paper_edge_override = float(
                        os.getenv("PAPER_MODE_EDGE_THRESHOLD", "0.005")
                    )

                signals = await generate_signals(
                    normalised_markets,
                    bankroll=_bankroll,
                    alpha_model=alpha_model,
                    force_signal_mode=_active_force,
                    edge_threshold=_paper_edge_override,
                )

                log.info(
                    "signals_generated",
                    count=len(signals),
                    force_mode=_active_force,
                    force_trade_fallback=_force_trade_fallback,
                    paper_edge_threshold=_paper_edge_override,
                )
                if not signals and len(normalised_markets) > 0:
                    log.warning(
                        "no_signals_generated",
                        markets_scanned=len(normalised_markets),
                        force_mode=_active_force,
                        hint="No positive-edge markets found this tick",
                    )
                    # ── 3a. Synthetic signal injection (force-trade fallback) ──────
                    # When in fallback mode and no real signal: generate synthetic
                    # signals with random bias + liquidity/spread sanity check.
                    if _force_trade_fallback:
                        try:
                            _synthetic = await generate_synthetic_signals(
                                normalised_markets,
                                bankroll=_bankroll,
                                top_n=1,
                            )
                            if _synthetic:
                                log.warning(
                                    "synthetic_signal_injected",
                                    count=len(_synthetic),
                                    hint="Using synthetic fallback signal",
                                )
                                signals = _synthetic
                        except Exception as _syn_exc:
                            log.error(
                                "synthetic_signal_error",
                                error=str(_syn_exc),
                            )

                # ── 4. Execute each signal and update positions ───────────────────
                _trades_this_tick: int = 0
                for signal in signals:
                    # ── 4a. Force signal mode: max 1 trade per loop ───────────────
                    if _active_force and _trades_this_tick >= 1:
                        log.info(
                            "signal_skipped_force_limit",
                            market_id=signal.market_id,
                            reason="force_mode_max_1_trade_per_loop",
                        )
                        continue

                    # ── 4b. Max open positions guard ──────────────────────────────
                    try:
                        open_positions = await db.get_positions(_user_id)
                        open_count = len(open_positions)
                    except Exception:  # noqa: BLE001
                        open_count = 0
                    if open_count >= _max_open_positions:
                        log.info(
                            "signal_skipped_max_positions",
                            market_id=signal.market_id,
                            open_positions=open_count,
                            limit=_max_open_positions,
                        )
                        continue

                    # ── 4c. Per-market cooldown guard ─────────────────────────────
                    # In force-trade fallback: 5-minute per-market guard to prevent spam
                    _effective_cooldown = (
                        _FORCE_TRADE_COOLDOWN_S if _force_trade_fallback else _cooldown_s
                    )
                    _now = time.time()
                    _last = _market_last_trade.get(signal.market_id, 0.0)
                    if _now - _last < _effective_cooldown:
                        log.info(
                            "signal_skipped_cooldown",
                            market_id=signal.market_id,
                            seconds_since_last=round(_now - _last, 1),
                            cooldown_s=_effective_cooldown,
                            force_fallback=_force_trade_fallback,
                        )
                        continue

                    # ── 4d. Fetch market metadata (cache lookup with API fallback) ──
                    _market_question: str = ""
                    _market_outcomes: list = []
                    if market_cache is not None:
                        try:
                            _meta = market_cache.get(signal.market_id)
                            if _meta is None:
                                # Hard fallback: single-market API fetch with retry
                                _meta = await market_cache.fetch_one(signal.market_id)
                                if _meta is not None:
                                    log.info(
                                        "market_metadata_fallback_used",
                                        market_id=signal.market_id,
                                        source="fetch_one",
                                    )
                            if _meta is not None:
                                _market_question = _meta.question
                                _market_outcomes = _meta.outcomes
                                log_market_metadata_used(
                                    signal.market_id,
                                    question=_market_question,
                                    outcomes=_market_outcomes,
                                    source="cache",
                                )
                            else:
                                log.info(
                                    "market_metadata_missing",
                                    market_id=signal.market_id,
                                    fallback="market_id",
                                )
                        except Exception as meta_exc:  # noqa: BLE001
                            log.warning(
                                "market_metadata_lookup_failed",
                                market_id=signal.market_id,
                                error=str(meta_exc),
                            )

                    # ── 4d. UNIFIED EXECUTION ────────────────────────────────
                    # PAPER mode with PaperEngine: PaperEngine is the single
                    # source of truth.  Bypass execute_trade() fill simulation.
                    # LIVE mode: use execute_trade() with executor_callback.
                    log.info(
                        "execution_start",
                        trade_id=signal.signal_id,
                        market_id=signal.market_id,
                        side=signal.side,
                        mode=_mode,
                    )

                    if _mode == "PAPER" and paper_engine is not None:
                        # ── PAPER path: PaperEngine is sole authority ─────────
                        try:
                            _paper_order = await paper_engine.execute_order({
                                "market_id": signal.market_id,
                                "side": signal.side,
                                "price": signal.p_market,
                                "size": signal.size_usd,
                                "trade_id": signal.signal_id,
                            })
                        except Exception as _pe_exc:
                            log.error(
                                "execution_failed",
                                trade_id=signal.signal_id,
                                market_id=signal.market_id,
                                error=str(_pe_exc),
                            )
                            continue

                        from ...execution.paper_engine import OrderStatus as _OS  # noqa: PLC0415
                        _pe_success = _paper_order.status in (_OS.FILLED, _OS.PARTIAL)

                        if not _pe_success:
                            log.info(
                                "execution_failed",
                                trade_id=signal.signal_id,
                                market_id=signal.market_id,
                                reason=_paper_order.reason,
                                status=_paper_order.status,
                            )
                            continue

                        # Build a synthetic TradeResult from PaperOrderResult
                        from ..execution.executor import TradeResult  # noqa: PLC0415
                        result = TradeResult(
                            trade_id=_paper_order.trade_id,
                            signal_id=signal.signal_id,
                            market_id=_paper_order.market_id,
                            side=_paper_order.side,
                            success=True,
                            mode="PAPER",
                            attempted_size=_paper_order.requested_size,
                            filled_size_usd=_paper_order.filled_size,
                            fill_price=_paper_order.fill_price,
                            latency_ms=0.0,
                            slippage_pct=0.0,
                            partial_fill=_paper_order.status == _OS.PARTIAL,
                            reason=_paper_order.reason,
                        )
                        log.info(
                            "execution_success",
                            trade_id=result.trade_id,
                            market_id=result.market_id,
                            side=result.side,
                            filled_size_usd=round(result.filled_size_usd, 4),
                            fill_price=round(result.fill_price, 6),
                            mode=result.mode,
                        )

                        # ── Persist ledger entry ──────────────────────────────
                        if db is not None and paper_engine is not None:
                            try:
                                # Persist wallet state after every execution
                                await paper_engine._wallet.persist(db)  # type: ignore[attr-defined]
                                # Persist positions
                                await paper_engine._positions.save_to_db(db)  # type: ignore[attr-defined]
                            except Exception as _persist_exc:
                                log.error(
                                    "persistence_write_failed",
                                    trade_id=result.trade_id,
                                    error=str(_persist_exc),
                                )

                    else:
                        # ── LIVE path (or PAPER fallback): use execute_trade ──
                        result = await execute_trade(
                            signal,
                            mode=_mode,
                            executor_callback=executor_callback,
                        )
                        if not result.success:
                            log.info(
                                "execution_failed",
                                trade_id=result.trade_id,
                                market_id=result.market_id,
                                reason=result.reason,
                            )
                            continue
                        log.info(
                            "execution_success",
                            trade_id=result.trade_id,
                            market_id=result.market_id,
                            side=result.side,
                            filled_size_usd=round(result.filled_size_usd or 0.0, 4),
                            fill_price=round(result.fill_price or 0.0, 6),
                            mode=result.mode,
                        )

                    if result.success:
                        _trades_this_tick += 1
                        log.info(
                            "trade_loop_executed",
                            market_id=result.market_id,
                            side=result.side,
                            mode=result.mode,
                            filled_size_usd=round(result.filled_size_usd or 0.0, 4),
                            fill_price=round(result.fill_price or 0.0, 6),
                            force_mode=_active_force,
                        )

                        # Record trade time for cooldown tracking and force-fallback reset
                        _now_trade = time.time()
                        _market_last_trade[signal.market_id] = _now_trade
                        _last_trade_time = _now_trade  # reset force-trade fallback counter

                        # ── 4e. Persist position (db is always present) ───────────
                        if result.fill_price > 0.0:
                            await db.upsert_position({
                                "user_id": _user_id,
                                "market_id": result.market_id,
                                "avg_price": result.fill_price,
                                "size": result.filled_size_usd,
                            })

                            # ── 4f. Record trade in DB and set status ─────────────
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

                        # ── 4g. Update in-memory PositionManager ──────────────────
                        _pos_realized: float = 0.0
                        _pos_unrealized: float = 0.0
                        if position_manager is not None and result.fill_price > 0.0:
                            try:
                                pos = position_manager.open(
                                    market_id=result.market_id,
                                    side=result.side,
                                    fill_price=result.fill_price,
                                    fill_size=result.filled_size_usd,
                                    trade_id=result.trade_id,
                                )
                                log_position_updated(
                                    result.market_id,
                                    side=pos.side,
                                    avg_price=pos.avg_price,
                                    size=pos.size,
                                    trade_id=result.trade_id,
                                )

                                # Compute unrealized PnL for this market
                                _mark_price = market_prices.get(result.market_id, result.fill_price)
                                _pos_unrealized = position_manager.unrealized_pnl(
                                    result.market_id, _mark_price
                                )
                            except Exception as pos_exc:  # noqa: BLE001
                                log.warning(
                                    "position_manager_update_failed",
                                    market_id=result.market_id,
                                    error=str(pos_exc),
                                )

                        # ── 4h. Update PnLTracker ─────────────────────────────────
                        if pnl_tracker is not None and result.fill_price > 0.0:
                            try:
                                pnl_rec = pnl_tracker.record_unrealized(
                                    result.market_id, _pos_unrealized
                                )
                                _pos_realized = pnl_rec.realized
                                log_pnl_updated(
                                    result.market_id,
                                    realized=pnl_rec.realized,
                                    unrealized=pnl_rec.unrealized,
                                    total=pnl_rec.realized + pnl_rec.unrealized,
                                )
                            except Exception as pnl_exc:  # noqa: BLE001
                                log.warning(
                                    "pnl_tracker_update_failed",
                                    market_id=result.market_id,
                                    error=str(pnl_exc),
                                )

                        # ── 4i. Send enriched Telegram trade alert ────────────────
                        if telegram_callback is not None and result.fill_price > 0.0:
                            try:
                                # Pick the outcome label matching the traded side, or
                                # fall back to result.side if no matching outcome found.
                                _outcome_label = result.side
                                if _market_outcomes:
                                    _upper_side = result.side.upper()
                                    for _o in _market_outcomes:
                                        if str(_o).upper() == _upper_side:
                                            _outcome_label = str(_o)
                                            break
                                    else:
                                        _outcome_label = _market_outcomes[0]
                                _trade_msg = format_trade_alert(
                                    side=result.side,
                                    price=result.fill_price,
                                    size=result.attempted_size,
                                    market_id=result.market_id,
                                    market_question=_market_question,
                                    outcome=_outcome_label,
                                    slippage_pct=result.slippage_pct,
                                    partial_fill=result.partial_fill,
                                    filled_size=result.filled_size_usd,
                                    realized_pnl=_pos_realized if pnl_tracker is not None else None,
                                    unrealized_pnl=_pos_unrealized if position_manager is not None else None,
                                )
                                await telegram_callback(_trade_msg)
                                log_telegram_trade_detailed(
                                    trade_id=result.trade_id,
                                    market_id=result.market_id,
                                    market_question=_market_question or result.market_id,
                                    side=result.side,
                                    price=result.fill_price,
                                    size=result.attempted_size,
                                    slippage_pct=result.slippage_pct,
                                    partial_fill=result.partial_fill,
                                    filled_size=result.filled_size_usd,
                                    realized_pnl=_pos_realized,
                                    unrealized_pnl=_pos_unrealized,
                                )
                            except Exception as tg_exc:  # noqa: BLE001
                                log.warning(
                                    "telegram_trade_alert_failed",
                                    trade_id=result.trade_id,
                                    market_id=result.market_id,
                                    error=str(tg_exc),
                                )

                # ── 5. Compute and log PnL metrics (db always present) ───────────
                try:
                    positions = await db.get_positions(_user_id)
                    trades = await db.get_recent_trades(limit=500)

                    realized = PnLCalculator.calculate_realized_pnl(trades)
                    unrealized = PnLCalculator.calculate_unrealized_pnl(
                        positions, market_prices
                    )
                    metrics = PnLCalculator.calculate_metrics(trades)
                    metrics["unrealized_pnl"] = unrealized
                    metrics["realized_pnl"] = realized
                    metrics["total_pnl"] = realized + unrealized

                    log.info("pnl_update", pnl=metrics)

                    # ── 5a. Update PnLTracker with unrealized PnL for all positions ─
                    if pnl_tracker is not None and position_manager is not None:
                        try:
                            for _open_pos in position_manager.all_positions():
                                _mp = market_prices.get(_open_pos.market_id, _open_pos.avg_price)
                                _upnl = position_manager.unrealized_pnl(_open_pos.market_id, _mp)
                                pnl_tracker.record_unrealized(_open_pos.market_id, _upnl)
                            log.info(
                                "pnl_updated",
                                positions=position_manager.count(),
                            )
                        except Exception as upnl_exc:  # noqa: BLE001
                            log.warning(
                                "pnl_tracker_tick_update_failed",
                                error=str(upnl_exc),
                            )

                except Exception as pnl_exc:  # noqa: BLE001
                    log.error(
                        "pnl_update_error",
                        error=str(pnl_exc),
                        exc_info=True,
                    )

                # ── 5b. Mark-to-market: update prices on PaperEngine positions ─
                if paper_engine is not None and _mode == "PAPER":
                    try:
                        for _mid, _mprice in market_prices.items():
                            paper_engine._positions.update_price(_mid, _mprice)  # type: ignore[attr-defined]
                        log.debug(
                            "mark_to_market_updated",
                            markets=len(market_prices),
                        )
                    except Exception as _mtm_exc:
                        log.warning(
                            "mark_to_market_error",
                            error=str(_mtm_exc),
                        )

                # ── 5c. Close order pipeline: TP / SL / signal reversal ───────
                if paper_engine is not None and _mode == "PAPER":
                    try:
                        _open_positions = paper_engine._positions.get_all_open()  # type: ignore[attr-defined]
                        for _pos in _open_positions:
                            _cur_price = market_prices.get(_pos.market_id)
                            if _cur_price is None:
                                continue

                            # Compute unrealized PnL ratio relative to entry cost
                            _entry_cost = _pos.size  # USD locked
                            if _entry_cost <= 0:
                                continue

                            if _pos.side == "YES":
                                _unreal_ratio = (_cur_price - _pos.entry_price) / _pos.entry_price
                            else:
                                _unreal_ratio = (_pos.entry_price - _cur_price) / _pos.entry_price

                            _trigger_reason: Optional[str] = None
                            if _unreal_ratio >= tp_pct:
                                _trigger_reason = "take_profit"
                            elif _unreal_ratio <= -sl_pct:
                                _trigger_reason = "stop_loss"

                            if _trigger_reason is not None:
                                import uuid as _uuid  # noqa: PLC0415
                                _close_trade_id = f"close-{_trigger_reason}-{_uuid.uuid4().hex[:12]}"
                                log.info(
                                    "close_order_event",
                                    market_id=_pos.market_id,
                                    reason=_trigger_reason,
                                    unrealized_ratio=round(_unreal_ratio, 4),
                                    entry_price=_pos.entry_price,
                                    close_price=_cur_price,
                                    trade_id=_close_trade_id,
                                )
                                try:
                                    _close_result = await paper_engine.close_order(
                                        market_id=_pos.market_id,
                                        close_price=_cur_price,
                                        trade_id=_close_trade_id,
                                    )
                                    log.info(
                                        "close_order_executed",
                                        trade_id=_close_trade_id,
                                        market_id=_pos.market_id,
                                        realized_pnl=round(_close_result.fill_price - _pos.entry_price, 6),
                                        close_price=_cur_price,
                                        reason=_trigger_reason,
                                    )
                                    # Persist: update DB trade status + remove position
                                    if db is not None:
                                        _rpnl = _close_result.filled_size * (
                                            _cur_price - _pos.entry_price
                                            if _pos.side == "YES"
                                            else _pos.entry_price - _cur_price
                                        )
                                        await db.update_trade_status(
                                            _pos.trade_ids[0] if _pos.trade_ids else _close_trade_id,
                                            "closed",
                                            pnl=_rpnl,
                                            won=_rpnl > 0,
                                        )
                                        await paper_engine._positions.save_closed_to_db(  # type: ignore[attr-defined]
                                            db, _pos.market_id
                                        )
                                        await paper_engine._wallet.persist(db)  # type: ignore[attr-defined]
                                    # Telegram close alert
                                    if telegram_callback is not None:
                                        try:
                                            _close_msg = (
                                                f"🔒 CLOSE [{_trigger_reason.upper()}] "
                                                f"{_pos.market_id[:12]}… "
                                                f"@ {_cur_price:.4f} | "
                                                f"Entry: {_pos.entry_price:.4f}"
                                            )
                                            await telegram_callback(_close_msg)
                                        except Exception:
                                            pass
                                except Exception as _close_exc:
                                    log.error(
                                        "close_order_failed",
                                        trade_id=_close_trade_id,
                                        market_id=_pos.market_id,
                                        error=str(_close_exc),
                                    )
                    except Exception as _exit_exc:
                        log.error(
                            "exit_pipeline_error",
                            error=str(_exit_exc),
                            exc_info=True,
                        )

                # ── Tick completed successfully — exit retry loop ─────────────────
                break

            except Exception as exc:  # noqa: BLE001
                _retry_count += 1
                if _retry_count <= _max_retries:
                    _backoff = 2 ** (_retry_count - 1)  # 1s, 2s, 4s
                    log.warning(
                        "pipeline_loop_error_retry",
                        error=str(exc),
                        attempt=_retry_count,
                        max_retries=_max_retries,
                        backoff_s=_backoff,
                        exc_info=True,
                    )
                    await asyncio.sleep(_backoff)
                else:
                    log.error(
                        "pipeline_loop_error",
                        error=str(exc),
                        attempt=_retry_count,
                        max_retries=_max_retries,
                        exc_info=True,
                    )

        # ── 6. Loop timing guard + rate-control delay ─────────────────────────
        _tick_duration: float = time.monotonic() - _tick_start
        log_loop_duration(
            tick=_tick,
            duration_s=_tick_duration,
            markets_processed=len(normalised_markets),
            signals_generated=len(signals),
        )

        # Enforce minimum 1 s per cycle; apply extra sleep when tick ran too fast
        _remaining: float = _interval - _tick_duration
        if _tick_duration < _FAST_LOOP_GUARD_S:
            # Tick finished suspiciously fast — force a guard sleep
            _guard_sleep: float = max(_MIN_LOOP_INTERVAL_S - _tick_duration, _FAST_LOOP_GUARD_S)
            log_loop_throttled(
                tick=_tick,
                duration_s=_tick_duration,
                throttle_sleep_s=_guard_sleep,
                reason="fast_loop",
            )
            await asyncio.sleep(_guard_sleep)
        elif _remaining > 0:
            await asyncio.sleep(_remaining)
        else:
            # Tick already took >= _interval; still enforce the absolute minimum
            _overrun: float = _tick_duration - _interval
            if _tick_duration < _MIN_LOOP_INTERVAL_S:
                _floor_sleep: float = _MIN_LOOP_INTERVAL_S - _tick_duration
                log_loop_throttled(
                    tick=_tick,
                    duration_s=_tick_duration,
                    throttle_sleep_s=_floor_sleep,
                    reason="below_minimum_interval",
                )
                await asyncio.sleep(_floor_sleep)
            elif _overrun > 0:
                log.info(
                    "loop_overrun",
                    tick=_tick,
                    duration_s=round(_tick_duration, 4),
                    overrun_s=round(_overrun, 4),
                )

        _tick += 1
