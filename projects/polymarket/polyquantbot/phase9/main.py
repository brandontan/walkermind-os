"""Phase 9 — Production Orchestrator: Main Entrypoint.

Integrates Phase 6.6 (decision), Phase 7 (live execution), and Phase 8
(risk/control) into a single async production pipeline.

Architecture::

    PolymarketWSClient (Phase 7)
        │  WebSocket market events
        ▼
    Orchestrator.event_loop
        │  on_market_event()
        ▼
    DecisionCallback (Phase 9)
        │  strategy → sizing → fill_prob → order_guard → executor
        ▼
    LiveExecutor (Phase 7)       FillMonitor (Phase 8)
        │  CLOB order submission      │  fill lifecycle tracking
        ▼                             ▼
    PositionTracker (Phase 8)     ExitMonitor (Phase 8)
                                     │  TP/SL exit
    HealthMonitor (Phase 8)       RiskGuard (Phase 8)
        │  latency / exposure alerts  │  kill switch authority

CLI::

    python -m phase9.main --config phase9/paper_run_config.yaml

Environment variables (required for live mode):
    CLOB_API_KEY, CLOB_API_SECRET, CLOB_API_PASSPHRASE
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID  (optional but recommended)

Environment variables (optional):
    CLOB_WS_URL     — WebSocket URL override
    CLOB_CHAIN_ID   — Polygon chain ID (default: 137)
    DRY_RUN         — "true" for paper mode (overrides config.run.dry_run)
    LOG_LEVEL       — DEBUG | INFO | WARNING | ERROR

Go-live gating (paper_run_config.yaml metrics section):
    ev_capture_ratio >= 0.75
    fill_rate        >= 0.60
    p95_latency      <= 500ms
    max_drawdown     <= 10%
"""
from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
import time
import uuid
from collections import deque
from typing import Optional

import structlog
import yaml

# ── Logging setup ─────────────────────────────────────────────────────────────

def _configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    """Configure structlog for structured JSON or pretty console output.

    Args:
        level: Log level string (DEBUG/INFO/WARNING/ERROR).
        fmt: "json" for production; "pretty" for local development.
    """
    import logging
    log_level = getattr(logging, level.upper(), logging.INFO)

    shared_processors = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    if fmt == "json":
        structlog.configure(
            processors=shared_processors + [structlog.processors.JSONRenderer()],
            wrapper_class=structlog.make_filtering_bound_logger(log_level),
            logger_factory=structlog.PrintLoggerFactory(),
        )
    else:
        structlog.configure(
            processors=shared_processors + [structlog.dev.ConsoleRenderer()],
            wrapper_class=structlog.make_filtering_bound_logger(log_level),
            logger_factory=structlog.PrintLoggerFactory(),
        )

    logging.basicConfig(level=log_level, stream=sys.stderr)


log = structlog.get_logger()


# ── SystemStateManager ────────────────────────────────────────────────────────

class SystemStateManager:
    """Async-safe SYSTEM_STATE manager.

    States:
        RUNNING — normal operation, all trading enabled.
        PAUSED  — temporary pause (WS disconnect < 60s), trades blocked.
        HALTED  — permanent stop (kill switch / WS disconnect >= 60s).

    Thread-safety: asyncio.Lock ensures atomic transitions.
    """

    RUNNING = "RUNNING"
    PAUSED  = "PAUSED"
    HALTED  = "HALTED"

    def __init__(self) -> None:
        self._mode: str = self.RUNNING
        self._reason: Optional[str] = None
        self._lock: asyncio.Lock = asyncio.Lock()

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def reason(self) -> Optional[str]:
        return self._reason

    @property
    def is_running(self) -> bool:
        return self._mode == self.RUNNING

    async def transition(self, new_mode: str, reason: Optional[str] = None) -> None:
        """Atomically transition to new_mode.

        Args:
            new_mode: RUNNING | PAUSED | HALTED
            reason: Human-readable reason for this transition.
        """
        async with self._lock:
            if self._mode == new_mode:
                return
            old_mode = self._mode
            self._mode = new_mode
            self._reason = reason
            log.info(
                "system_state_transition",
                old_mode=old_mode,
                new_mode=new_mode,
                reason=reason,
            )

    def snapshot(self) -> dict:
        """Return current state as a dict."""
        return {"mode": self._mode, "reason": self._reason}


# ── CircuitBreaker ─────────────────────────────────────────────────────────────

class CircuitBreaker:
    """Rolling-window circuit breaker for error rate and latency spikes.

    Triggers if:
        - error_rate > error_rate_threshold in the rolling call window, or
        - p95 execution latency > latency_threshold_ms in the window.

    On trigger:
        - Calls risk_guard.trigger_kill_switch() with reason.
        - Respects cooldown_sec to prevent repeated trigger spam.

    Thread-safety: single asyncio event loop only.
    """

    def __init__(
        self,
        risk_guard,
        error_rate_threshold: float = 0.30,
        error_window_size: int = 20,
        latency_threshold_ms: float = 600.0,
        cooldown_sec: float = 60.0,
        enabled: bool = True,
        consecutive_failures_threshold: int = 3,
    ) -> None:
        """Initialise the circuit breaker.

        Args:
            risk_guard: RiskGuard instance — called to trigger kill switch.
            error_rate_threshold: Trigger if error_rate exceeds this (0.0–1.0).
            error_window_size: Rolling window size in number of recent calls.
            latency_threshold_ms: Trigger if p95 latency exceeds this (ms).
            cooldown_sec: Suppress re-trigger for this many seconds after fire.
            enabled: If False, circuit breaker is a no-op.
            consecutive_failures_threshold: Trigger if N consecutive failures occur.
        """
        self._risk_guard = risk_guard
        self._error_threshold = error_rate_threshold
        self._window_size = error_window_size
        self._latency_threshold = latency_threshold_ms
        self._cooldown = cooldown_sec
        self._enabled = enabled
        self._consecutive_failures_threshold = consecutive_failures_threshold

        self._error_window: deque[bool] = deque(maxlen=error_window_size)
        self._latency_window: deque[float] = deque(maxlen=error_window_size)
        self._last_trigger_at: float = 0.0
        self._trigger_count: int = 0
        self._consecutive_failures: int = 0

        log.info(
            "circuit_breaker_initialized",
            error_rate_threshold=error_rate_threshold,
            latency_threshold_ms=latency_threshold_ms,
            cooldown_sec=cooldown_sec,
            enabled=enabled,
            consecutive_failures_threshold=consecutive_failures_threshold,
        )

    async def record(
        self,
        success: bool,
        latency_ms: float,
        correlation_id: str = "",
    ) -> None:
        """Record a call outcome and evaluate circuit breaker conditions.

        Args:
            success: True if the call succeeded, False on error/timeout.
            latency_ms: Execution latency for this call in milliseconds.
            correlation_id: Request trace ID for log correlation.
        """
        if not self._enabled or self._risk_guard.disabled:
            return

        self._error_window.append(not success)
        self._latency_window.append(latency_ms)

        # Track consecutive failures for rapid failure detection
        if not success:
            self._consecutive_failures += 1
        else:
            self._consecutive_failures = 0

        if self._consecutive_failures >= self._consecutive_failures_threshold:
            await self._trigger(
                reason=f"consecutive_failures:{self._consecutive_failures}",
                correlation_id=correlation_id,
            )
            return

        if time.time() - self._last_trigger_at < self._cooldown:
            return

        if len(self._error_window) >= self._window_size:
            error_rate = sum(self._error_window) / len(self._error_window)
            if error_rate > self._error_threshold:
                await self._trigger(
                    reason=f"error_rate:{error_rate:.3f}_exceeds:{self._error_threshold}",
                    correlation_id=correlation_id,
                )
                return

        if len(self._latency_window) >= self._window_size:
            sorted_lat = sorted(self._latency_window)
            p95_idx = max(0, int(len(sorted_lat) * 0.95) - 1)
            p95 = sorted_lat[p95_idx]
            if p95 > self._latency_threshold:
                await self._trigger(
                    reason=f"p95_latency:{p95:.0f}ms_exceeds:{self._latency_threshold:.0f}ms",
                    correlation_id=correlation_id,
                )

    async def _trigger(self, reason: str, correlation_id: str) -> None:
        """Fire the circuit breaker — activates the kill switch.

        Args:
            reason: Human-readable trigger description.
            correlation_id: Request trace ID.
        """
        self._trigger_count += 1
        self._last_trigger_at = time.time()

        log.error(
            "circuit_breaker_triggered",
            reason=reason,
            trigger_count=self._trigger_count,
            correlation_id=correlation_id,
        )

        await self._risk_guard.trigger_kill_switch(f"circuit_breaker:{reason}")


# ── Phase9Orchestrator ─────────────────────────────────────────────────────────

class Phase9Orchestrator:
    """Phase 9 production orchestrator — async lifecycle manager.

    Bootstraps all subsystems, runs the WebSocket event loop, and
    manages graceful shutdown.

    Lifecycle::

        orchestrator = Phase9Orchestrator(config)
        await orchestrator.bootstrap()
        await orchestrator.run()             # blocks until shutdown
        await orchestrator.shutdown()        # called automatically on SIGTERM/SIGINT

    Thread-safety: single asyncio event loop only.
    """

    def __init__(self, config: dict) -> None:
        """Initialise orchestrator from parsed config dict.

        Args:
            config: Parsed paper_run_config.yaml dict.
        """
        self._cfg = config
        self._tasks: list[asyncio.Task] = []
        self._running: bool = False
        self._cumulative_pnl: float = 0.0
        self._ws_heartbeat_paused: bool = False  # True when trading paused for WS reconnect
        self._system_state: Optional[SystemStateManager] = None
        self._ws_disconnect_at: float = 0.0  # Unix timestamp when WS first disconnected
        self._shutdown_lock: asyncio.Lock = asyncio.Lock()  # prevents concurrent double-shutdown

        # Apply DRY_RUN from config if not overridden by env
        if config.get("run", {}).get("dry_run", True):
            os.environ.setdefault("DRY_RUN", "true")

        # All injected components — populated in bootstrap()
        self._risk_guard = None
        self._position_tracker = None
        self._fill_monitor = None
        self._exit_monitor = None
        self._health_monitor = None
        self._order_guard = None
        self._live_executor = None
        self._ws_client = None
        self._phase66_integrator = None
        self._strategy_engine = None
        self._telegram = None
        self._decision_callback = None
        self._circuit_breaker = None
        self._metrics_validator = None

    # ── Bootstrap ─────────────────────────────────────────────────────────────

    async def bootstrap(self) -> None:
        """Initialise all components in strict dependency order.

        Raises:
            RuntimeError: If required environment variables are missing in live mode.
        """
        log.info("phase9_bootstrap_start", dry_run=os.getenv("DRY_RUN", "false"))

        cfg = self._cfg
        risk_cfg = cfg.get("risk", {})
        og_cfg = cfg.get("order_guard", {})
        fill_cfg = cfg.get("fill_monitor", {})
        exit_cfg = cfg.get("exit", {})
        health_cfg = cfg.get("health", {})
        cb_cfg = cfg.get("circuit_breaker", {})
        tg_cfg = cfg.get("telegram", {})
        mkt_cfg = cfg.get("markets", {})

        # 1. RiskGuard — master kill switch, no upstream dependencies
        from ..phase8.risk_guard import RiskGuard
        self._risk_guard = RiskGuard(
            daily_loss_limit=float(risk_cfg.get("daily_loss_limit", -2000.0)),
            max_drawdown_pct=float(risk_cfg.get("max_drawdown_pct", 0.08)),
        )

        # 1b. SystemStateManager — RUNNING|PAUSED|HALTED state machine
        self._system_state = SystemStateManager()

        # 2. PositionTracker — tracks all open/closed positions
        from ..phase8.position_tracker import PositionTracker
        self._position_tracker = PositionTracker(risk_guard=self._risk_guard)

        # 3. OrderGuard — prevents duplicate order submissions
        from ..phase8.order_guard import OrderGuard
        self._order_guard = OrderGuard(
            risk_guard=self._risk_guard,
            order_timeout_sec=float(og_cfg.get("order_timeout_sec", 30.0)),
        )

        # 4. LiveExecutor — CLOB order submission (dry_run or live)
        from ..phase7.core.execution.live_executor import LiveExecutor
        self._live_executor = LiveExecutor.from_env()

        # Inject executor + tracker into RiskGuard for cancel/close on kill switch
        self._risk_guard._executor = self._live_executor
        self._risk_guard._position_tracker = self._position_tracker

        # 5. FillMonitor — tracks fill lifecycle with dedup and retry
        from ..phase8.fill_monitor import FillMonitor
        self._fill_monitor = FillMonitor(
            executor=self._live_executor,
            position_tracker=self._position_tracker,
            risk_guard=self._risk_guard,
            order_timeout_sec=float(fill_cfg.get("order_timeout_sec", 30.0)),
            max_retry=int(fill_cfg.get("max_retry", 5)),
            poll_interval_sec=float(fill_cfg.get("poll_interval_sec", 2.0)),
        )

        # 6. ExitMonitor — enforces TP/SL on all open positions
        from ..phase8.exit_monitor import ExitMonitor
        self._exit_monitor = ExitMonitor(
            executor=self._live_executor,
            position_tracker=self._position_tracker,
            risk_guard=self._risk_guard,
            take_profit_pct=float(exit_cfg.get("take_profit_pct", 0.15)),
            stop_loss_pct=float(exit_cfg.get("stop_loss_pct", -0.08)),
            check_interval_sec=float(exit_cfg.get("check_interval_sec", 5.0)),
        )

        # 7. Phase 6.6 Integrator — sizing, fill_prob, correlation
        from ..phase6_6.integration.runner_patch import Phase66Integrator
        phase66_cfg_path = os.path.join(
            os.path.dirname(__file__), "..", "phase6_6", "config.yaml"
        )
        try:
            with open(phase66_cfg_path, "r", encoding="utf-8") as fh:
                phase66_cfg = yaml.safe_load(fh)
        except (FileNotFoundError, OSError):
            log.warning(
                "phase66_config_not_found_using_defaults",
                path=phase66_cfg_path,
            )
            phase66_cfg = {}

        self._phase66_integrator = Phase66Integrator.from_config(
            cfg=phase66_cfg,
            mm_cancel_callback=None,  # MM cancel not wired in Phase 9 paper run
        )

        # 8. Strategy engine — signal generation (Phase 6 StrategyManager)
        self._strategy_engine = _SimpleStrategyAdapter(cfg)

        # 9. TelegramLive — real-time alert system
        from .telegram_live import TelegramLive
        tg_enabled = tg_cfg.get("enabled", True)
        self._telegram = TelegramLive.from_env(enabled=tg_enabled)
        await self._telegram.start()

        # 10. HealthMonitor — latency/exposure monitoring
        from ..phase8.health_monitor import HealthMonitor
        self._health_monitor = HealthMonitor(
            position_tracker=self._position_tracker,
            fill_monitor=self._fill_monitor,
            risk_guard=self._risk_guard,
            check_interval_sec=float(health_cfg.get("check_interval_sec", 30.0)),
            latency_warn_ms=float(health_cfg.get("latency_warn_ms", 500.0)),
            fill_rate_warn=float(health_cfg.get("fill_rate_warn", 0.50)),
            exposure_limit_pct=float(health_cfg.get("exposure_limit_pct", 0.45)),
            balance_provider=lambda: 10000.0,  # paper run default balance
        )

        # 11. CircuitBreaker — error rate + latency spike guard
        self._circuit_breaker = CircuitBreaker(
            risk_guard=self._risk_guard,
            error_rate_threshold=float(cb_cfg.get("error_rate_threshold", 0.30)),
            error_window_size=int(cb_cfg.get("error_window_size", 20)),
            latency_threshold_ms=float(cb_cfg.get("latency_threshold_ms", 600.0)),
            cooldown_sec=float(cb_cfg.get("cooldown_sec", 60.0)),
            enabled=bool(cb_cfg.get("enabled", True)),
            consecutive_failures_threshold=int(cb_cfg.get("consecutive_failures_threshold", 3)),
        )

        # 12. DecisionCallback — strategy → execution bridge
        from .decision_callback import DecisionCallback
        self._decision_callback = DecisionCallback(
            risk_guard=self._risk_guard,
            order_guard=self._order_guard,
            fill_monitor=self._fill_monitor,
            live_executor=self._live_executor,
            phase66_integrator=self._phase66_integrator,
            strategy_engine=self._strategy_engine,
            telegram=self._telegram,
            config=cfg,
            system_state=self._system_state,
            position_tracker=self._position_tracker,
        )

        # 13. MetricsValidator — post-run metric computation
        from .metrics_validator import MetricsValidator
        self._metrics_validator = MetricsValidator.from_config(cfg)

        # 14. WebSocket client — Polymarket CLOB real-time feed
        market_ids = list(mkt_cfg.get("market_ids", []))
        if not market_ids:
            log.warning(
                "no_market_ids_in_config",
                hint="Set markets.market_ids in paper_run_config.yaml or override at runtime",
            )
            market_ids = ["__placeholder__"]  # prevents WSClient ValueError; won't subscribe

        from ..phase7.infra.ws_client import PolymarketWSClient
        self._ws_client = PolymarketWSClient.from_env(market_ids=market_ids)

        log.info("phase9_bootstrap_complete")

    # ── Main run loop ─────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Start all background tasks and the main WebSocket event loop.

        Blocks until self._running is False (set by shutdown() or kill switch).
        """
        if not self._decision_callback:
            raise RuntimeError("bootstrap() must be called before run()")

        self._running = True

        run_cfg = self._cfg.get("run", {})
        duration_h = float(run_cfg.get("run_duration_hours", 0))

        log.info(
            "phase9_run_started",
            dry_run=os.getenv("DRY_RUN", "false"),
            run_duration_hours=duration_h,
        )

        # ── Launch background tasks ───────────────────────────────────────────
        self._tasks = [
            asyncio.create_task(self._fill_monitor.run(), name="fill_monitor"),
            asyncio.create_task(self._exit_monitor.run(), name="exit_monitor"),
            asyncio.create_task(self._health_monitor.run(), name="health_monitor"),
            asyncio.create_task(self._ws_event_loop(), name="ws_event_loop"),
        ]

        if duration_h > 0:
            self._tasks.append(
                asyncio.create_task(
                    self._duration_timer(duration_h * 3600.0),
                    name="duration_timer",
                )
            )

        # ── Wait until shutdown ───────────────────────────────────────────────
        try:
            done, pending = await asyncio.wait(
                self._tasks,
                return_when=asyncio.FIRST_EXCEPTION,
            )
            for task in done:
                # task.exception() raises CancelledError if the task was
                # cancelled — always check cancelled() first.
                if task.cancelled():
                    continue
                exc = task.exception()
                if exc:
                    log.error(
                        "background_task_raised",
                        task_name=task.get_name(),
                        error=str(exc),
                        exc_info=True,
                    )
            # Cancel any remaining pending tasks so they don't leak.
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        except asyncio.CancelledError:
            log.info("phase9_run_cancelled")

    # ── Event loop ────────────────────────────────────────────────────────────

    async def _ws_event_loop(self) -> None:
        """Connect WebSocket client and dispatch market events to the pipeline.

        Runs until self._running is False or risk_guard.disabled is True.
        Includes a reconnect loop: on any disconnect or error, trading is
        paused (risk_guard.disabled=True) and a reconnect is attempted with
        exponential backoff.  Trading resumes automatically after a successful
        reconnect unless the kill switch was independently triggered.
        """
        ws_cfg = self._cfg.get("websocket", {})
        reconnect_base = float(ws_cfg.get("reconnect_base_delay_sec", 1.0))
        reconnect_max = float(ws_cfg.get("reconnect_max_delay_sec", 60.0))
        reconnect_delay = reconnect_base
        heartbeat_pause_sec = float(ws_cfg.get("heartbeat_pause_sec", 30.0))
        heartbeat_kill_sec = float(ws_cfg.get("heartbeat_kill_sec", 60.0))

        while self._running:
            try:
                await self._ws_client.connect()

                # Restore trading after a heartbeat-only pause.
                # Only reset disabled if no permanent kill switch has fired
                # (trigger_kill_switch sets _kill_switch_reason; our heartbeat
                # pause sets disabled=True directly, leaving _kill_switch_reason None).
                if self._ws_heartbeat_paused:
                    self._ws_heartbeat_paused = False
                    kill_switch_reason = getattr(
                        self._risk_guard, "_kill_switch_reason", None
                    )
                    if not kill_switch_reason:
                        self._risk_guard.disabled = False
                        log.info("phase9_ws_reconnected_trading_resumed")
                        if self._system_state and self._system_state.mode == SystemStateManager.PAUSED:
                            await self._system_state.transition(SystemStateManager.RUNNING, "ws_reconnected")
                    else:
                        log.warning(
                            "phase9_ws_reconnected_but_kill_switch_active",
                            reason=kill_switch_reason,
                        )

                reconnect_delay = reconnect_base  # reset backoff on clean connect
                log.info("phase9_ws_event_loop_started")

                async for event in self._ws_client.events():
                    if not self._running or self._risk_guard.disabled:
                        log.info(
                            "phase9_ws_event_loop_stopping",
                            running=self._running,
                            risk_guard_disabled=self._risk_guard.disabled,
                        )
                        break

                    if event.type != "orderbook":
                        continue

                    await self._on_market_event(event)

            except asyncio.CancelledError:
                log.info("ws_event_loop_cancelled")
                break
            except Exception as exc:
                if not self._running:
                    break
                log.error(
                    "ws_heartbeat_failure",
                    error=str(exc),
                    reconnect_in_sec=reconnect_delay,
                    exc_info=True,
                )
                # Track disconnect start time
                if not self._ws_heartbeat_paused:
                    self._ws_disconnect_at = time.time()
                    self._ws_heartbeat_paused = True

                disconnect_duration = time.time() - self._ws_disconnect_at

                if disconnect_duration >= heartbeat_kill_sec:
                    # WS down >= 60s → kill switch
                    log.error(
                        "ws_heartbeat_kill_switch",
                        disconnect_duration_sec=round(disconnect_duration, 1),
                        heartbeat_kill_sec=heartbeat_kill_sec,
                    )
                    await self._risk_guard.trigger_kill_switch(
                        f"ws_disconnect_duration:{disconnect_duration:.0f}s"
                    )
                    if self._system_state:
                        await self._system_state.transition(
                            SystemStateManager.HALTED,
                            f"ws_disconnect_duration:{disconnect_duration:.0f}s",
                        )
                    self._running = False
                    break
                elif disconnect_duration >= heartbeat_pause_sec:
                    # WS down >= 30s but < 60s → PAUSED
                    if self._system_state and self._system_state.is_running:
                        await self._system_state.transition(
                            SystemStateManager.PAUSED,
                            f"ws_disconnect:{disconnect_duration:.0f}s",
                        )

                if not self._risk_guard.disabled:
                    self._risk_guard.disabled = True
                    log.warning(
                        "ws_heartbeat_trading_paused",
                        disconnect_duration_sec=round(disconnect_duration, 1),
                        reconnect_in_sec=reconnect_delay,
                    )
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2.0, reconnect_max)
                continue  # attempt reconnect on next iteration

            finally:
                try:
                    await self._ws_client.disconnect()
                except Exception:  # noqa: BLE001
                    pass

            # Clean exit (inner for-loop finished without exception).
            # Either self._running is False or risk_guard is disabled by kill switch.
            break

        log.info("ws_event_loop_exited")

    async def _on_market_event(self, event) -> None:
        """Process a single WebSocket market event through the decision pipeline.

        Args:
            event: WSEvent from PolymarketWSClient with type="orderbook".
        """
        if self._risk_guard.disabled:
            return

        if self._system_state and not self._system_state.is_running:
            return

        t0 = time.perf_counter()
        cid = str(uuid.uuid4())

        # Build market context from orderbook event
        bids = event.data.get("bids", [])
        asks = event.data.get("asks", [])

        best_bid = float(bids[0][0]) if bids else 0.0
        best_ask = float(asks[0][0]) if asks else 1.0
        mid_price = (best_bid + best_ask) / 2.0
        spread = best_ask - best_bid
        bid_depth = sum(float(b[1]) for b in bids[:5]) if bids else 0.0

        market_ctx = {
            "market_id": event.market_id,
            "p_market": round(mid_price, 6),
            "p_market_prev": self._get_prev_price(event.market_id, mid_price),
            "spread": round(spread, 6),
            "depth": round(bid_depth, 2),
            "orderbook_valid": bool(bids and asks),
            "balance": 10000.0,  # paper run default
            "timestamp": event.timestamp,
        }

        # Stale data guard: reject if market data is more than 2s old.
        # Threshold matches decision_callback._STALE_DATA_THRESHOLD_S.
        event_age_s = time.time() - float(market_ctx.get("timestamp", 0))
        if event_age_s > 2.0:  # noqa: PLR2004 — matches _STALE_DATA_THRESHOLD_S
            log.warning(
                "stale_market_data_rejected",
                market_id=event.market_id,
                age_sec=round(event_age_s, 3),
                correlation_id=cid,
            )
            return

        # Update Phase 6.6 integrator with tick data
        latency_ms = (time.perf_counter() - t0) * 1000
        await self._phase66_integrator.on_market_tick(
            market_id=event.market_id,
            price=mid_price,
            latency_ms=latency_ms,
            correlation_id=cid,
        )

        # Run decision pipeline
        from .decision_callback import DecisionInput
        inp = DecisionInput(
            market_id=event.market_id,
            market_ctx=market_ctx,
            correlation_id=cid,
        )

        try:
            result = await asyncio.wait_for(
                self._decision_callback(inp),
                timeout=1.0,  # 1s end-to-end latency budget
            )

            success = result.status in ("submitted", "filled", "partial", "skipped")
            await self._circuit_breaker.record(
                success=success,
                latency_ms=result.latency_ms,
                correlation_id=cid,
            )

            # Record metrics
            if result.status in ("submitted", "filled", "partial"):
                self._metrics_validator.record_fill(filled=True)
                self._metrics_validator.record_latency(result.latency_ms)

            elif result.status == "rejected":
                self._metrics_validator.record_fill(filled=False)
                self._metrics_validator.record_latency(result.latency_ms)

        except asyncio.TimeoutError:
            await self._circuit_breaker.record(
                success=False, latency_ms=1000.0, correlation_id=cid
            )
            log.warning(
                "event_pipeline_timeout",
                market_id=event.market_id,
                correlation_id=cid,
            )
        except Exception as exc:  # noqa: BLE001
            await self._circuit_breaker.record(
                success=False, latency_ms=0.0, correlation_id=cid
            )
            log.error(
                "event_pipeline_error",
                market_id=event.market_id,
                error=str(exc),
                correlation_id=cid,
                exc_info=True,
            )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_prev_price(self, market_id: str, current_price: float) -> float:
        """Return previous price from Phase 6.6 market cache.

        Falls back to current_price if no history.

        Args:
            market_id: Market to look up.
            current_price: Current mid-price (fallback value).

        Returns:
            Previous price or current_price if not available.
        """
        if self._phase66_integrator:
            prev = self._phase66_integrator.market_cache.get_prev_price(market_id)
            if prev is not None:
                return prev
        return current_price

    async def _duration_timer(self, duration_sec: float) -> None:
        """Background task that stops the run after duration_sec seconds.

        Args:
            duration_sec: Run duration in seconds.
        """
        log.info("duration_timer_started", duration_sec=duration_sec)
        await asyncio.sleep(duration_sec)
        log.info("duration_timer_elapsed", duration_sec=duration_sec)
        await self.shutdown()

    # ── Shutdown ──────────────────────────────────────────────────────────────

    async def shutdown(self) -> None:
        """Gracefully shut down all subsystems.

        Order:
            1. Set _running = False (stops event loop acceptance).
            2. Cancel all background tasks.
            3. Disconnect WebSocket client.
            4. Shutdown TelegramLive (drain alert queue).
            5. Shutdown Phase 6.6 integrator (drain MM cancel tasks).
            6. Compute and write metrics.
            7. Send daily summary Telegram alert.
        """
        # Use a lock to prevent concurrent double-shutdown (e.g. signal + duration_timer).
        async with self._shutdown_lock:
            if not self._running:
                return
            self._running = False

        log.info("phase9_shutdown_start")

        # 1. Cancel background tasks
        for task in self._tasks:
            if task and not task.done():
                task.cancel()

        await asyncio.gather(*self._tasks, return_exceptions=True)

        # 2. Disconnect WebSocket
        if self._ws_client:
            await self._ws_client.disconnect()

        # 3. Shutdown Phase 6.6 integrator
        if self._phase66_integrator:
            await self._phase66_integrator.shutdown()

        # 4. Compute and write metrics
        metrics = None
        if self._metrics_validator and self._decision_callback:
            self._metrics_validator.ingest_callback_metrics(
                self._decision_callback.metrics_snapshot()
            )
            metrics = self._metrics_validator.compute()
            output_path = self._cfg.get("metrics", {}).get("output_file", "metrics.json")
            self._metrics_validator.write(metrics, output_path=output_path)
            passed = self._metrics_validator.gate_check(metrics)
            log.info(
                "phase9_metrics_final",
                ev_capture=metrics.ev_capture_ratio,
                fill_rate=metrics.fill_rate,
                p95_latency=metrics.p95_latency,
                drawdown=metrics.drawdown,
                gate_passed=passed,
            )

        # 5. Send Telegram daily summary
        if self._telegram and metrics:
            summary = metrics.session_summary
            await self._telegram.alert_daily(
                pnl=summary.get("final_cumulative_pnl", 0.0),
                trades=summary.get("orders_filled", 0),
                win_rate=metrics.ev_capture_ratio,  # proxy
                fill_rate=metrics.fill_rate,
                p95_latency_ms=metrics.p95_latency,
            )
            await self._telegram.stop()

        log.info("phase9_shutdown_complete")


# ── SimpleStrategyAdapter ─────────────────────────────────────────────────────

class _SimpleStrategyAdapter:
    """Minimal strategy adapter that wraps Phase 6 StrategyManager.

    Falls back to a lightweight Bayesian strategy if Phase 6
    StrategyManager cannot be instantiated from config.

    Phase 9 paper run uses this adapter to generate signals.
    In production, replace with the full Phase 6 StrategyManager.
    """

    def __init__(self, config: dict) -> None:
        """Initialise the strategy adapter.

        Args:
            config: Top-level paper_run_config dict.
        """
        self._min_ev = float(config.get("risk", {}).get("min_ev_threshold", 0.0))
        self._manager = None

        # Try to load full Phase 6 StrategyManager
        try:
            from ..phase6.engine.strategy_engine import BayesianStrategy
            self._bayesian = BayesianStrategy(min_ev=max(self._min_ev, 0.01))
            log.info("strategy_adapter_using_bayesian")
        except ImportError as exc:
            log.warning("strategy_adapter_phase6_import_failed", error=str(exc))
            self._bayesian = None

    async def generate_signal(self, market_data: dict) -> list:
        """Generate trading signals from market data.

        Args:
            market_data: Market context dict with p_market, p_market_prev, etc.

        Returns:
            List of SignalResult objects (0–N signals).
        """
        if self._bayesian:
            try:
                return await self._bayesian.generate_signal(market_data)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "strategy_adapter_signal_error",
                    error=str(exc),
                )
        return []


# ── Signal handler ─────────────────────────────────────────────────────────────

_orchestrator_ref: Optional[Phase9Orchestrator] = None


def _install_signal_handlers(orchestrator: Phase9Orchestrator, loop: asyncio.AbstractEventLoop) -> None:
    """Install SIGTERM/SIGINT handlers for graceful shutdown.

    Args:
        orchestrator: Running orchestrator to shut down on signal.
        loop: Event loop to schedule the shutdown coroutine.
    """
    def _handle_signal(sig_name: str) -> None:
        log.info("signal_received_initiating_shutdown", signal=sig_name)
        loop.create_task(orchestrator.shutdown())

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(
                sig,
                lambda s=sig.name: _handle_signal(s),
            )
        except NotImplementedError:
            # Windows: signal handlers not supported in asyncio
            pass


# ── CLI entrypoint ────────────────────────────────────────────────────────────

def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments.

    Args:
        argv: Argument list override (defaults to sys.argv).

    Returns:
        Namespace with config, log_level, log_format.
    """
    parser = argparse.ArgumentParser(
        prog="phase9.main",
        description="Phase 9 — Production Orchestrator (Walker AI Trading Team)",
    )
    parser.add_argument(
        "--config",
        default="phase9/paper_run_config.yaml",
        help="Path to YAML config (default: phase9/paper_run_config.yaml)",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Override log level from config",
    )
    parser.add_argument(
        "--log-format",
        default=None,
        choices=["json", "pretty"],
        help="Override log format (json | pretty)",
    )
    return parser.parse_args(argv)


async def _async_main(config_path: str, log_level: str, log_format: str) -> None:
    """Main async entrypoint.

    Args:
        config_path: Path to paper_run_config.yaml.
        log_level: Structlog log level string.
        log_format: "json" or "pretty".
    """
    # Load config
    try:
        with open(config_path, "r", encoding="utf-8") as fh:
            config = yaml.safe_load(fh)
    except (FileNotFoundError, OSError) as exc:
        print(f"FATAL: Cannot open config file '{config_path}': {exc}", file=sys.stderr)
        sys.exit(1)

    # Configure logging (config values override defaults; CLI args override config)
    run_cfg = config.get("run", {})
    effective_level = log_level or run_cfg.get("log_level", "INFO")
    effective_format = log_format or run_cfg.get("log_format", "json")
    _configure_logging(effective_level, effective_format)

    log.info(
        "phase9_starting",
        config_path=config_path,
        log_level=effective_level,
        log_format=effective_format,
        dry_run=os.getenv("DRY_RUN", str(run_cfg.get("dry_run", True))),
    )

    # Build and start orchestrator
    orchestrator = Phase9Orchestrator(config)
    # asyncio.get_running_loop() is the correct call inside an async context
    # (get_event_loop() is deprecated in Python 3.10+ inside a running loop).
    loop = asyncio.get_running_loop()
    _install_signal_handlers(orchestrator, loop)

    try:
        await orchestrator.bootstrap()
        await orchestrator.run()
    except KeyboardInterrupt:
        log.info("keyboard_interrupt_received")
    except Exception as exc:  # noqa: BLE001
        log.error(
            "phase9_unhandled_exception",
            error=str(exc),
            exc_info=True,
        )
    finally:
        await orchestrator.shutdown()


def main(argv: Optional[list[str]] = None) -> None:
    """Synchronous entry point — called by `python -m phase9.main`.

    Args:
        argv: CLI arguments override (defaults to sys.argv).
    """
    args = _parse_args(argv)
    asyncio.run(
        _async_main(
            config_path=args.config,
            log_level=args.log_level or "",
            log_format=args.log_format or "",
        )
    )


if __name__ == "__main__":
    main()
