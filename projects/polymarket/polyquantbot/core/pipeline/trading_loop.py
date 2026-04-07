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
import uuid
from typing import Any, Callable, Awaitable, Optional

import structlog

from ..market.market_client import get_active_markets, extract_market_data
from ..market_scope import apply_market_scope
from ..market.ingest import ingest_markets
from ..signal.signal_engine import generate_signals, generate_synthetic_signals
from ..signal.alpha_model import ProbabilisticAlphaModel
from ..execution.executor import (
    TradeResult,
    execute_trade,
    classify_trade_result_outcome,
    evaluate_formal_risk_gate,
)
from ...monitoring.pnl_calculator import PnLCalculator
from ...monitoring.performance_tracker import PerformanceTracker
from ...monitoring.metrics_engine import MetricsEngine
from ...monitoring.validation_engine import ValidationEngine, ValidationState
from ...monitoring.snapshot_engine import SnapshotEngine
from ...strategy.market_intelligence import MarketIntelligenceEngine
from ...telegram.utils import telegram_sender
from ...interface.ui.views import (
    render_exposure_view,
    render_home_view,
    render_market_view,
    render_performance_view,
    render_risk_view,
    render_strategy_view,
    render_wallet_view,
)
from ..validation_state import ValidationStateStore
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

# ── Stability / observability constants ───────────────────────────────────────

_HEARTBEAT_INTERVAL_S: float = 300.0     # emit system_alive log every 5 min
_WARNING_ALERT_COOLDOWN_S: float = 600.0 # WARNING alert max once per 10 min
_DEFAULT_VALIDATION_MODE: str = "LIVE_OBSERVATION"  # no kill-switch action
_SNAPSHOT_INTERVAL_S: float = 600.0      # system snapshot every 10 min

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


def build_ui_view(command: str, data: dict[str, Any]) -> str:
    """Route UI command to the correct formatter with safe fallback."""
    normalized = command.strip().lower()
    if normalized == "/home":
        return render_home_view(data)
    if normalized == "/wallet":
        return render_wallet_view(data)
    if normalized in ("/portfolio", "/exposure"):
        return render_exposure_view(data)
    if normalized == "/performance":
        return render_performance_view(data)
    if normalized == "/strategy":
        return render_strategy_view(data)
    if normalized == "/risk":
        return render_risk_view(data)
    if normalized == "/markets":
        return render_market_view(data)
    return render_home_view(data)


def map_ui_data(command: str, source: dict[str, Any]) -> dict[str, Any]:
    """Return command-scoped data to enforce no duplication between views."""
    normalized = command.strip().lower()
    if normalized == "/home":
        keys = {
            "status",
            "mode",
            "markets",
            "latency",
            "strategy",
            "scan",
            "distribution",
            "insight",
            "validation_status",
            "trades_count",
            "winrate",
            "profit_factor",
        }
    elif normalized in ("/portfolio", "/exposure"):
        keys = {
            "total_exposure",
            "ratio",
            "positions",
            "exposure",
            "unrealized",
            "position_lines",
        }
    elif normalized == "/wallet":
        keys = {"cash", "balance", "equity", "used", "free", "positions"}
    elif normalized == "/performance":
        keys = {"pnl", "total_pnl", "winrate", "wr", "trades", "total_trades", "drawdown"}
    elif normalized == "/strategy":
        keys = {"strategies"}
    elif normalized == "/risk":
        keys = {"kelly", "level", "profile"}
    elif normalized == "/markets":
        keys = {
            "total_markets",
            "active_markets",
            "top_edge_type",
            "dominant_signal",
            "top_opportunities",
        }
    else:
        keys = set(source.keys())
    payload = {key: source.get(key) for key in keys}
    if normalized == "/home":
        _trades_count, _winrate, _profit_factor, _validation_status = build_validation_snapshot(source)
        payload.update(
            {
                "trades_count": _trades_count,
                "winrate": _winrate,
                "profit_factor": _profit_factor,
                "validation_status": _validation_status,
            }
        )
    return payload


def classify_validation_status(
    *,
    trades_count: int,
    winrate: Optional[float],
    profit_factor: Optional[float],
) -> str:
    """Classify validation state from sample size + WR/PF thresholds."""
    if trades_count < 30:
        return "WARMING"
    if winrate is None or profit_factor is None:
        return "N/A"
    if winrate >= 0.70 and profit_factor >= 1.50:
        return "PASS"
    return "CRITICAL"


def build_validation_snapshot(source: dict[str, Any]) -> tuple[str, str, str, str]:
    """Build Telegram home validation block fields with N/A-safe fallbacks."""
    _trades_raw = source.get("trades_count", source.get("trade_count"))
    _wr_raw = source.get("winrate", source.get("wr", source.get("win_rate")))
    _pf_raw = source.get("profit_factor", source.get("pf"))
    _provided_status = source.get("validation_status")

    _trades_count: Optional[int] = None
    _winrate: Optional[float] = None
    _profit_factor: Optional[float] = None

    try:
        if _trades_raw is not None:
            _trades_count = int(float(_trades_raw))
    except (TypeError, ValueError):
        _trades_count = None

    try:
        if _wr_raw is not None:
            _winrate = float(_wr_raw)
    except (TypeError, ValueError):
        _winrate = None

    try:
        if _pf_raw is not None:
            _profit_factor = float(_pf_raw)
    except (TypeError, ValueError):
        _profit_factor = None

    _status = str(_provided_status).strip().upper() if _provided_status is not None else ""
    if not _status:
        if _trades_count is None:
            _status = "N/A"
        else:
            _status = classify_validation_status(
                trades_count=_trades_count,
                winrate=_winrate,
                profit_factor=_profit_factor,
            )

    return (
        str(_trades_count) if _trades_count is not None else "N/A",
        f"{_winrate:.2f}" if _winrate is not None else "N/A",
        f"{_profit_factor:.2f}" if _profit_factor is not None else "N/A",
        _status,
    )


def classify_edge(expected_value: Optional[float]) -> str:
    """Classify EV into LOW/MEDIUM/HIGH buckets for portfolio UI."""
    if expected_value is None:
        return "N/A"
    if expected_value < 0.01:
        return "LOW"
    if expected_value <= 0.05:
        return "MEDIUM"
    return "HIGH"


def classify_strength(probability: Optional[float]) -> str:
    """Classify probability into WEAK/MODERATE/STRONG buckets for portfolio UI."""
    if probability is None:
        return "N/A"
    if probability < 0.55:
        return "WEAK"
    if probability <= 0.65:
        return "MODERATE"
    return "STRONG"


def build_portfolio_intelligence(
    *,
    probability: Any,
    expected_value: Any,
    reason: Any,
) -> dict[str, str]:
    """Build portfolio intelligence fields from signal/scoring values with safe fallbacks."""
    _prob: Optional[float] = None
    _ev: Optional[float] = None

    try:
        if probability is not None:
            _prob = float(probability)
    except (TypeError, ValueError):
        _prob = None
    try:
        if expected_value is not None:
            _ev = float(expected_value)
    except (TypeError, ValueError):
        _ev = None

    _confidence = f"{round(_prob, 2):.2f}" if _prob is not None else "N/A"
    _reason = str(reason).strip() if reason is not None and str(reason).strip() else "N/A"
    if _reason == "N/A" and _prob is not None and _ev is not None:
        _reason = f"p={_prob:.2f}, ev={_ev:.3f}"

    return {
        "confidence": _confidence,
        "edge": classify_edge(_ev),
        "signal": classify_strength(_prob),
        "reason": _reason,
    }


def short_name(name: str) -> str:
    return name[:18] + "..." if len(name) > 18 else name


def summarize_edge_type(distribution: dict[str, int]) -> str:
    if not distribution:
        return "N/A"
    total = sum(distribution.values())
    bond_count = sum(
        count for key, count in distribution.items() if "bond" in key.strip().lower()
    )
    if bond_count > total / 2:
        return "BOND ARB"
    if len(distribution) > 1:
        return "DIVERSIFIED"
    return "TREND"


def summarize_signal(signals: list[Any], distribution: dict[str, int]) -> str:
    if not signals:
        return "N/A"
    avg_prob = 0.0
    prob_count = 0
    yes_count = 0
    no_count = 0

    for signal in signals:
        try:
            avg_prob += float(getattr(signal, "p_model", 0.0))
            prob_count += 1
        except (TypeError, ValueError):
            continue
        side = str(getattr(signal, "side", "")).upper()
        if side == "YES":
            yes_count += 1
        elif side == "NO":
            no_count += 1

    dominant_class = max(distribution, key=distribution.get) if distribution else "GENERAL"
    side_label = "YES" if yes_count >= no_count else "NO"
    if prob_count <= 0:
        return f"{side_label} • {dominant_class}"
    return f"{side_label} {avg_prob / prob_count:.2f} • {dominant_class}"


def build_market_intel_payload(
    *,
    markets: list[dict[str, Any]],
    distribution: dict[str, int],
    signals: list[Any],
) -> dict[str, Any]:
    opportunities: list[dict[str, Any]] = []
    for signal in sorted(
        signals,
        key=lambda item: float(getattr(item, "ev", 0.0) or 0.0),
        reverse=True,
    )[:5]:
        opportunities.append(
            {
                "name": short_name(str(getattr(signal, "market_id", "N/A"))),
                "ev": round(float(getattr(signal, "ev", 0.0) or 0.0), 3),
                "signal": classify_strength(float(getattr(signal, "p_model", 0.0) or 0.0)),
            }
        )
    return {
        "total_markets": len(markets),
        "active_markets": len(signals),
        "top_edge_type": summarize_edge_type(distribution),
        "dominant_signal": summarize_signal(signals, distribution),
        "top_opportunities": opportunities[:5],
    }


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

    # ── Validation Engine singletons (initialized once, shared across ticks) ──
    _performance_tracker = PerformanceTracker()
    _metrics_engine = MetricsEngine()
    _validation_engine = ValidationEngine()
    _snapshot_engine = SnapshotEngine()
    _market_intel_engine = MarketIntelligenceEngine()
    _validation_state = ValidationStateStore()
    # Mutable container for previous validation state — enables change detection
    _prev_vs: list[ValidationState] = [ValidationState.HEALTHY]

    # ── Stability / observability state ───────────────────────────────────────
    _validation_mode: str = os.getenv("VALIDATION_MODE", _DEFAULT_VALIDATION_MODE).upper()
    _snapshot_telegram_enabled: bool = _env_bool("VALIDATION_SNAPSHOT_TELEGRAM_ENABLED", False)
    _last_snapshot_time: list[float] = [0.0]
    _last_heartbeat: list[float] = [0.0]        # mutable so closure can mutate
    _validation_hook_errors: list[int] = [0]    # cumulative error counter
    _last_market_distribution: dict[str, int] = {}
    _last_market_intel_payload: dict[str, Any] = {}
    _trade_type_distribution: dict[str, int] = {}
    _market_type_by_id: dict[str, str] = {}

    def _to_float(value: Any) -> float:
        """Return float-safe value for Telegram formatting."""
        if value is None:
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _format_validation_alert(
        state: ValidationState,
        metrics: dict[str, Any],
    ) -> Optional[str]:
        """Build concise validation alerts for Telegram."""
        trade_count = int(_to_float(metrics.get("trade_count", 0)))
        win_rate = _to_float(metrics.get("win_rate", 0.0))
        profit_factor = _to_float(metrics.get("profit_factor", 0.0))
        drawdown = _to_float(metrics.get("max_drawdown", 0.0))

        if state == ValidationState.INSUFFICIENT_DATA:
            return (
                "⚠️ VALIDATION: INSUFFICIENT DATA\n"
                f"Trades: {trade_count}/30\n"
                "Status: Warming up..."
            )
        if state == ValidationState.HEALTHY:
            return (
                "✅ VALIDATION: HEALTHY\n"
                f"Trades: {trade_count}\n"
                f"WR: {win_rate:.2f}\n"
                f"PF: {profit_factor:.2f}\n"
                f"MDD: {drawdown:.2%}"
            )
        if state == ValidationState.WARNING:
            return (
                "⚠️ VALIDATION: WARNING\n"
                f"Trades: {trade_count}\n"
                f"WR: {win_rate:.2f} (target 0.70)\n"
                f"PF: {profit_factor:.2f} (target 1.50)\n"
                f"MDD: {drawdown:.2%}"
            )
        if state == ValidationState.CRITICAL:
            return (
                "🚨 VALIDATION: CRITICAL\n"
                f"Trades: {trade_count}\n"
                f"WR: {win_rate:.2f} < 0.70\n"
                f"PF: {profit_factor:.2f} < 1.50\n"
                f"MDD: {drawdown:.2%}"
            )
        return None

    def _format_snapshot_alert(snapshot: dict[str, Any]) -> str:
        """Build LOW PRIORITY Telegram snapshot message."""
        return (
            "📊 SNAPSHOT\n"
            f"Trades: {int(_to_float(snapshot.get('trade_count', 0)))}\n"
            f"WR: {_to_float(snapshot.get('win_rate', 0.0)):.2f}\n"
            f"PF: {_to_float(snapshot.get('profit_factor', 0.0)):.2f}\n"
            f"MDD: {_to_float(snapshot.get('drawdown', 0.0)):.2%}\n"
            f"State: {snapshot.get('state', 'UNKNOWN')}"
        )

    async def _emit_validation_result(
        _val_result: Any,
        _computed: dict[str, Any],
        tg_cb: Optional[Callable[[str], Awaitable[None]]],
    ) -> None:
        """Shared helper: update state store, log, and send Telegram alerts."""
        _validation_state.update(_val_result.state, _computed)

        _tc = int(_to_float(_computed.get("trade_count", _performance_tracker.get_trade_count())))
        _last_pnl = _to_float(_computed.get("last_pnl", 0.0))

        _log_fn = (
            log.critical
            if _val_result.state == ValidationState.CRITICAL
            else log.info
        )
        _log_fn(
            "validation_update",
            state=_val_result.state.value,
            metrics=_computed,
            reason=_val_result.reasons,
            trade_count=_tc,
            rolling_window_size=_performance_tracker.max_window,
            last_pnl=round(_last_pnl, 6),
            validation_mode=_validation_mode,
        )

        _now = time.time()
        if _now - _last_snapshot_time[0] >= _SNAPSHOT_INTERVAL_S:
            _snapshot = _snapshot_engine.build_snapshot(
                _computed,
                _val_result.state.value,
                market_distribution=_last_market_distribution,
                trade_distribution=_trade_type_distribution,
                trades=_performance_tracker.get_recent_trades(),
            )
            log.info(
                "system_snapshot",
                snapshot=_snapshot,
            )

            if _snapshot_telegram_enabled:
                try:
                    await telegram_sender.send(_format_snapshot_alert(_snapshot))
                except Exception as _snap_tg_exc:  # noqa: BLE001
                    log.warning(
                        "snapshot_telegram_failed",
                        error=str(_snap_tg_exc),
                    )
            _last_snapshot_time[0] = _now

        state_changed = _val_result.state != _prev_vs[0]
        if state_changed:
            _prev_vs[0] = _val_result.state

            if _val_result.state == ValidationState.CRITICAL:
                # Engage kill switch on CRITICAL when not in observation-only mode
                if _validation_mode != "LIVE_OBSERVATION" and stop_event is not None:
                    log.critical(
                        "validation_critical_halt",
                        reason="CRITICAL validation state — stop_event set",
                        validation_mode=_validation_mode,
                    )
                    stop_event.set()

            _alert = _format_validation_alert(_val_result.state, _computed)
            if _alert:
                try:
                    await telegram_sender.send(_alert)
                except Exception as _tg_val_exc:  # noqa: BLE001
                    log.warning(
                        "validation_telegram_failed",
                        error=str(_tg_val_exc),
                    )

    async def _run_validation_hook(
        trade: dict[str, Any],
        tg_cb: Optional[Callable[[str], Awaitable[None]]],
    ) -> None:
        """Run the validation pipeline for a newly opened trade.

        Designed to run as a background ``asyncio.create_task()`` so that
        execution latency is unaffected.  All failures are caught and logged;
        the coroutine never propagates exceptions to the caller.
        """
        try:
            _performance_tracker.add_trade(trade)
        except (ValueError, TypeError) as _ve:
            _validation_hook_errors[0] += 1
            log.error(
                "validation_trade_invalid",
                error=str(_ve),
                cumulative_errors=_validation_hook_errors[0],
            )
            return

        try:
            _recent = _performance_tracker.get_recent_trades()
            _computed = _metrics_engine.compute(_recent)
            _val_result = _validation_engine.evaluate(_computed)
            await _emit_validation_result(_val_result, _computed, tg_cb)
        except Exception as _val_exc:  # noqa: BLE001
            _validation_hook_errors[0] += 1
            log.critical(
                "validation_hook_error",
                error=str(_val_exc),
                cumulative_errors=_validation_hook_errors[0],
                exc_info=True,
            )

    async def _run_closed_validation_hook(
        trade_id: str,
        pnl: float,
        tg_cb: Optional[Callable[[str], Awaitable[None]]],
    ) -> None:
        """Update a closed trade's PnL in the tracker and re-run validation.

        Designed to run as a background ``asyncio.create_task()`` after a
        position is closed and its realized PnL is known.  All failures are
        caught and logged; the coroutine never propagates exceptions.
        """
        if not trade_id:
            log.debug(
                "closed_validation_skipped",
                trade_id=trade_id,
                pnl=pnl,
                reason="no trade_id",
            )
            return

        _updated = _performance_tracker.update_trade(trade_id, pnl)
        if not _updated:
            log.warning(
                "closed_validation_trade_not_found",
                trade_id=trade_id,
                pnl=pnl,
            )
            return

        try:
            _recent = _performance_tracker.get_recent_trades()
            _computed = _metrics_engine.compute(_recent)
            _val_result = _validation_engine.evaluate(_computed)
            await _emit_validation_result(_val_result, _computed, tg_cb)
        except Exception as _cval_exc:  # noqa: BLE001
            _validation_hook_errors[0] += 1
            log.critical(
                "closed_validation_hook_error",
                trade_id=trade_id,
                pnl=pnl,
                error=str(_cval_exc),
                cumulative_errors=_validation_hook_errors[0],
                exc_info=True,
            )

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
        validation_mode=_validation_mode,
        heartbeat_interval_s=_HEARTBEAT_INTERVAL_S,
        warning_alert_cooldown_s=_WARNING_ALERT_COOLDOWN_S,
    )
    log.info("db_enabled", status=True)

    while True:
        # ── Check stop signal ─────────────────────────────────────────────────
        if stop_event is not None and stop_event.is_set():
            log.info("trading_loop_stopped")
            break

        _tick_start: float = time.monotonic()
        log.info("trading_loop_tick", tick=_tick, mode=_mode, bankroll=_bankroll)

        # ── Heartbeat (every HEARTBEAT_INTERVAL_S) ────────────────────────────
        _now_hb = time.time()
        if _now_hb - _last_heartbeat[0] >= _HEARTBEAT_INTERVAL_S:
            _last_heartbeat[0] = _now_hb
            log.info(
                "system_heartbeat",
                system_alive=True,
                tick=_tick,
                validation_hook_errors=_validation_hook_errors[0],
                validation_state=_prev_vs[0].value,
                trade_count=_performance_tracker.get_trade_count(),
                validation_mode=_validation_mode,
            )

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

                scoped_markets, scope_snapshot = await apply_market_scope(markets)
                log.info(
                    "market_feed",
                    count=len(markets),
                    scoped_count=len(scoped_markets),
                    selection_type=scope_snapshot.get("selection_type", "All Markets"),
                    active_categories=scope_snapshot.get("enabled_categories", []),
                    fallback_applied_count=scope_snapshot.get("fallback_applied_count", 0),
                )

                if not scoped_markets:
                    log.warning(
                        "trading_loop_scope_blocked",
                        all_markets=scope_snapshot.get("all_markets_enabled", True),
                        active_categories=scope_snapshot.get("enabled_categories", []),
                        guidance="Enable All Markets or at least one category in Telegram > Markets > Categories",
                    )
                    break

                # ── 1a. Debug: log first 3 raw markets (temp) ─────────────────────
                # TODO: remove once production data structure is confirmed stable
                for _raw in scoped_markets[:3]:
                    log.info("market_raw_sample", data=_raw)

                # ── 1b. Parse and normalise markets ───────────────────────────────
                normalised_markets = ingest_markets(scoped_markets)
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

                # ── 1d. Shadow-only market intelligence (no decision impact) ─────
                market_distribution: dict[str, int] = {}
                _market_type_by_id = {}
                for market in normalised_markets:
                    market_id = str(market.get("market_id", "unknown"))
                    try:
                        intel = _market_intel_engine.analyze(market)
                    except Exception as _intel_exc:  # noqa: BLE001
                        log.warning(
                            "market_intelligence_warning",
                            market_id=market_id,
                            error=str(_intel_exc),
                        )
                        intel = {"market_type": "GENERAL", "tags": []}

                    market_type = str(intel.get("market_type", "GENERAL"))
                    tags = intel.get("tags", [])
                    if not isinstance(tags, list):
                        tags = []

                    _market_type_by_id[market_id] = market_type
                    market_distribution[market_type] = market_distribution.get(market_type, 0) + 1

                    log.info(
                        "market_intelligence",
                        market_id=market_id,
                        type=market_type,
                        tags=tags,
                    )
                _last_market_distribution = market_distribution

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
                _last_market_intel_payload = build_market_intel_payload(
                    markets=normalised_markets,
                    distribution=_last_market_distribution,
                    signals=signals,
                )
                log.info("market_intel_payload", payload=_last_market_intel_payload)
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

                    _reserved = await db.reserve_execution_intent(
                        signal_id=signal.signal_id,
                        market_id=signal.market_id,
                    )
                    if not _reserved:
                        log.info(
                            "execution_duplicate_blocked",
                            signal_id=signal.signal_id,
                            market_id=signal.market_id,
                            reason="duplicate_blocked",
                        )
                        await db.mark_execution_intent(
                            signal_id=signal.signal_id,
                            status="duplicate_blocked",
                            reason="duplicate_blocked",
                        )
                        log.info(
                            "execution_audit",
                            trade_id="",
                            signal_id=signal.signal_id,
                            market_id=signal.market_id,
                            side=signal.side,
                            mode=_mode,
                            outcome="duplicate_blocked",
                            reason="duplicate_blocked",
                            attempted_size=round(signal.size_usd or 0.0, 4),
                            filled_size=0.0,
                            fill_price=0.0,
                            partial_fill=False,
                        )
                        continue

                    _risk_decision = evaluate_formal_risk_gate(
                        signal,
                        mode=_mode,
                        max_position_usd=_bankroll * 0.10,
                        min_edge=float(os.getenv("EXECUTION_MIN_EDGE", "0.01")),
                        min_liquidity_usd=float(os.getenv("EXECUTION_MIN_LIQUIDITY_USD", "10000")),
                        kill_switch_active=False,
                    )
                    if not _risk_decision.allowed:
                        await db.mark_execution_intent(
                            signal_id=signal.signal_id,
                            status="risk_blocked",
                            reason=_risk_decision.reason,
                        )
                        _risk_outcome = (
                            "kill_switch_blocked"
                            if _risk_decision.reason == "kill_switch_active"
                            else "risk_blocked"
                        )
                        log.info(
                            "execution_audit",
                            trade_id="",
                            signal_id=signal.signal_id,
                            market_id=signal.market_id,
                            side=signal.side,
                            mode=_mode,
                            outcome=_risk_outcome,
                            reason=_risk_decision.reason,
                            attempted_size=round(signal.size_usd or 0.0, 4),
                            filled_size=0.0,
                            fill_price=0.0,
                            partial_fill=False,
                        )
                        continue

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
                            await db.mark_execution_intent(
                                signal_id=signal.signal_id,
                                status="failed",
                                reason=f"paper_engine_failure:{_pe_exc}",
                            )
                            continue

                        from ...execution.paper_engine import OrderStatus as _OS  # noqa: PLC0415
                        _is_partial = _paper_order.status == _OS.PARTIAL
                        _is_filled = _paper_order.status == _OS.FILLED
                        _is_rejected = _paper_order.status == _OS.REJECTED

                        result = TradeResult(
                            trade_id=_paper_order.trade_id,
                            signal_id=signal.signal_id,
                            market_id=_paper_order.market_id,
                            side=_paper_order.side,
                            success=_is_filled or _is_partial,
                            mode="PAPER",
                            attempted_size=_paper_order.requested_size,
                            filled_size_usd=_paper_order.filled_size,
                            fill_price=_paper_order.fill_price,
                            latency_ms=0.0,
                            slippage_pct=0.0,
                            partial_fill=_is_partial,
                            reason=(
                                f"paper_engine_rejected:{_paper_order.reason}"
                                if _is_rejected
                                else (_paper_order.reason or ("partial_fill" if _is_partial else "paper_filled"))
                            ),
                            extra={"paper_status": str(_paper_order.status)},
                        )

                        if not result.success:
                            log.info(
                                "execution_failed",
                                trade_id=result.trade_id,
                                market_id=result.market_id,
                                reason=result.reason,
                                status=str(_paper_order.status),
                            )
                        else:
                            log.info(
                                "execution_success",
                                trade_id=result.trade_id,
                                market_id=result.market_id,
                                side=result.side,
                                filled_size_usd=round(result.filled_size_usd, 4),
                                fill_price=round(result.fill_price, 6),
                                mode=result.mode,
                                partial_fill=result.partial_fill,
                            )

                        # ── Persist ledger entry ──────────────────────────────
                        if result.success and db is not None and paper_engine is not None:
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
                                result.success = False
                                result.reason = f"downstream_persist_failed:{_persist_exc}"

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
                        else:
                            log.info(
                                "execution_success",
                                trade_id=result.trade_id,
                                market_id=result.market_id,
                                side=result.side,
                                filled_size_usd=round(result.filled_size_usd or 0.0, 4),
                                fill_price=round(result.fill_price or 0.0, 6),
                                mode=result.mode,
                                partial_fill=result.partial_fill,
                            )

                    _execution_outcome = classify_trade_result_outcome(result)
                    if _execution_outcome == "blocked" and result.reason == "kill_switch_active":
                        _execution_outcome = "kill_switch_blocked"
                    log.info(
                        "execution_audit",
                        trade_id=result.trade_id,
                        signal_id=signal.signal_id,
                        market_id=result.market_id,
                        side=result.side,
                        mode=result.mode,
                        outcome=_execution_outcome,
                        reason=result.reason,
                        attempted_size=round(result.attempted_size or 0.0, 4),
                        filled_size=round(result.filled_size_usd or 0.0, 4),
                        fill_price=round(result.fill_price or 0.0, 6),
                        partial_fill=result.partial_fill,
                    )
                    await db.mark_execution_intent(
                        signal_id=signal.signal_id,
                        status=_execution_outcome,
                        reason=result.reason,
                        trade_id=result.trade_id,
                    )

                    if not result.success:
                        continue

                    if result.success:
                        _trades_this_tick += 1
                        _portfolio_intelligence = build_portfolio_intelligence(
                            probability=signal.p_model,
                            expected_value=signal.ev,
                            reason=signal.extra.get("decision_reason"),
                        )

                        _signal_market_type = _market_type_by_id.get(signal.market_id, "GENERAL")
                        _trade_type_distribution[_signal_market_type] = (
                            _trade_type_distribution.get(_signal_market_type, 0) + 1
                        )
                        log.info(
                            "market_type_trade_recorded",
                            market_id=result.market_id,
                            market_type=_signal_market_type,
                            trade_count=_trade_type_distribution[_signal_market_type],
                        )

                        log.info(
                            "trade_loop_executed",
                            market_id=result.market_id,
                            side=result.side,
                            mode=result.mode,
                            filled_size_usd=round(result.filled_size_usd or 0.0, 4),
                            fill_price=round(result.fill_price or 0.0, 6),
                            force_mode=_active_force,
                            confidence=_portfolio_intelligence["confidence"],
                            edge_class=_portfolio_intelligence["edge"],
                            signal_class=_portfolio_intelligence["signal"],
                            decision_reason=_portfolio_intelligence["reason"],
                        )

                        # Record trade time for cooldown tracking and force-fallback reset
                        _now_trade = time.time()
                        _market_last_trade[signal.market_id] = _now_trade
                        _last_trade_time = _now_trade  # reset force-trade fallback counter

                        # ── 4e. Persist position (db is always present) ───────────
                        if result.fill_price > 0.0:
                            try:
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
                            except Exception as _recon_exc:
                                log.error(
                                    "execution_reconciliation_failed",
                                    trade_id=result.trade_id,
                                    market_id=result.market_id,
                                    error=str(_recon_exc),
                                )
                                await db.mark_execution_intent(
                                    signal_id=signal.signal_id,
                                    status="restore_recovery_failure",
                                    reason=f"reconciliation_failed:{_recon_exc}",
                                    trade_id=result.trade_id,
                                )
                                continue

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
                        if result.fill_price > 0.0:
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
                                await telegram_sender.send(_trade_msg)
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

                        # ── 4j. Validation engine hook (non-blocking) ─────────────
                        if result.fill_price > 0.0:
                            _result_label = "WIN" if _to_float(signal.ev) > 0.0 else "LOSS"
                            _val_trade: dict[str, Any] = {
                                "trade_id": result.trade_id,
                                "pnl": 0.0,
                                "result": _result_label,
                                "market_type": _signal_market_type,
                                "signal": _portfolio_intelligence["signal"],
                                "edge": _portfolio_intelligence["edge"],
                                "entry_price": result.fill_price,
                                "exit_price": result.fill_price,
                                "size": result.filled_size_usd or 0.0,
                                "timestamp": time.time(),
                                "signal_type": signal.extra.get("signal_type", "REAL"),
                            }
                            asyncio.create_task(
                                _run_validation_hook(_val_trade, telegram_callback)
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
                    metrics.update(_last_market_intel_payload)

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
                                _close_trade_id = f"close-{_trigger_reason}-{uuid.uuid4().hex[:12]}"
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
                                        _orig_trade_id = (
                                            _pos.trade_ids[0] if _pos.trade_ids else _close_trade_id
                                        )
                                        await db.update_trade_status(
                                            _orig_trade_id,
                                            "closed",
                                            pnl=_rpnl,
                                            won=_rpnl > 0,
                                        )
                                        # ── 5c-i. Closed-trade PnL → PerformanceTracker ──
                                        asyncio.create_task(
                                            _run_closed_validation_hook(
                                                _orig_trade_id,
                                                _rpnl,
                                                telegram_callback,
                                            )
                                        )
                                        await paper_engine._positions.save_closed_to_db(  # type: ignore[attr-defined]
                                            db, _pos.market_id
                                        )
                                        await paper_engine._wallet.persist(db)  # type: ignore[attr-defined]
                                    # Telegram close alert
                                        try:
                                            _close_msg = (
                                                f"🔒 CLOSE [{_trigger_reason.upper()}] "
                                                f"{_pos.market_id[:12]}… "
                                                f"@ {_cur_price:.4f} | "
                                                f"Entry: {_pos.entry_price:.4f}"
                                            )
                                            await telegram_sender.send(_close_msg)
                                        except Exception as _close_tg_exc:
                                            log.warning(
                                                "close_order_telegram_failed",
                                                trade_id=_close_trade_id,
                                                market_id=_pos.market_id,
                                                error=str(_close_tg_exc),
                                            )
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

                # ── 5d. LIVE close order pipeline: TP / SL ───────────────────
                elif _mode == "LIVE" and position_manager is not None:
                    try:
                        for _lpos in position_manager.all_positions():
                            _cur_price = market_prices.get(_lpos.market_id)
                            if _cur_price is None:
                                continue
                            _entry_cost = _lpos.size
                            if _entry_cost <= 0:
                                continue
                            if _lpos.side == "YES":
                                _live_unreal_ratio = (_cur_price - _lpos.avg_price) / _lpos.avg_price
                            else:
                                _live_unreal_ratio = (_lpos.avg_price - _cur_price) / _lpos.avg_price
                            _live_trigger: Optional[str] = None
                            if _live_unreal_ratio >= tp_pct:
                                _live_trigger = "take_profit"
                            elif _live_unreal_ratio <= -sl_pct:
                                _live_trigger = "stop_loss"
                            if _live_trigger is not None:
                                _live_close_id = f"live-close-{_live_trigger}-{uuid.uuid4().hex[:12]}"
                                log.info(
                                    "live_close_order_event",
                                    market_id=_lpos.market_id,
                                    reason=_live_trigger,
                                    unrealized_ratio=round(_live_unreal_ratio, 4),
                                    entry_price=_lpos.avg_price,
                                    close_price=_cur_price,
                                    trade_id=_live_close_id,
                                )
                                try:
                                    _closed_lpos, _live_rpnl = position_manager.close(
                                        _lpos.market_id, _cur_price
                                    )
                                    if _closed_lpos is not None:
                                        log.info(
                                            "live_close_order_executed",
                                            trade_id=_live_close_id,
                                            market_id=_lpos.market_id,
                                            realized_pnl=round(_live_rpnl, 6),
                                            close_price=_cur_price,
                                            reason=_live_trigger,
                                        )
                                        if db is not None:
                                            _live_orig_id = (
                                                _lpos.trade_ids[0]
                                                if hasattr(_lpos, "trade_ids") and _lpos.trade_ids
                                                else _live_close_id
                                            )
                                            await db.update_trade_status(
                                                _live_orig_id,
                                                "closed",
                                                pnl=_live_rpnl,
                                                won=_live_rpnl > 0,
                                            )
                                            # ── 5d-i. Closed-trade PnL → PerformanceTracker ──
                                            asyncio.create_task(
                                                _run_closed_validation_hook(
                                                    _live_orig_id,
                                                    _live_rpnl,
                                                    telegram_callback,
                                                )
                                            )
                                        try:
                                            _live_close_msg = (
                                                f"🔒 LIVE CLOSE [{_live_trigger.upper()}] "
                                                f"{_lpos.market_id[:12]}… "
                                                f"@ {_cur_price:.4f} | "
                                                f"Entry: {_lpos.avg_price:.4f}"
                                            )
                                            await telegram_sender.send(_live_close_msg)
                                        except Exception as _live_close_tg_exc:
                                            log.warning(
                                                "live_close_order_telegram_failed",
                                                trade_id=_live_close_id,
                                                market_id=_lpos.market_id,
                                                error=str(_live_close_tg_exc),
                                            )
                                except Exception as _live_close_exc:
                                    log.error(
                                        "live_close_order_failed",
                                        trade_id=_live_close_id,
                                        market_id=_lpos.market_id,
                                        error=str(_live_close_exc),
                                    )
                    except Exception as _live_exit_exc:
                        log.error(
                            "live_exit_pipeline_error",
                            error=str(_live_exit_exc),
                            exc_info=True,
                        )
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
