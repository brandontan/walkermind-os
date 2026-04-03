"""Phase 10.1 — Integration Pipeline Runner.

Wires the full live-trading pipeline with Phase 10 gating:

    PolymarketWSClient
        │  WebSocket orderbook/trade events
        ▼
    Phase10PipelineRunner.event_loop
        │  data_received_ts stamped
        ▼
    OrderBookManager → Phase7MarketCache
        │  microstructure (bid/ask/spread/depth)
        ▼
    decision_callback (user-supplied)
        │  signal_generated_ts stamped
        ▼
    GoLiveController.allow_execution()  ← PAPER mode blocks here
        │
    ExecutionGuard.validate()           ← risk/duplicate check
        │  order_sent_ts stamped
        ▼
    LiveExecutor.execute()
        │  fill_received_ts stamped
        ▼
    MetricsValidator  (latency, EV, fill_rate, drawdown)

Background tasks:
    KalshiClient polling → ArbDetector (signals logged, NOT executed)
    Metrics health log (every 60 s)
    Feedback expiry (every 60 s)

Mode:
    PAPER — GoLiveController blocks real execution;
            ExecutionGuard still validates for correctness.
            All trades are logged as paper trades.
    LIVE  — Full execution when all GO-LIVE gates pass.

GO-LIVE conditions (all must pass before LIVE execution):
    ev_capture_ratio  >= 0.75
    fill_rate         >= 0.60
    p95_latency_ms    <= 500
    drawdown          <= 0.08

Usage::

    runner = Phase10PipelineRunner.from_config(config, market_ids=["0xabc..."])
    await runner.run()

Config schema (YAML)::

    go_live:
      mode: PAPER            # PAPER | LIVE
      ev_capture_min: 0.75
      fill_rate_min:  0.60
      p95_latency_max_ms: 500
      drawdown_max: 0.08
      max_capital_usd: 10000
      max_trades_per_day: 200

    execution_guard:
      min_liquidity_usd: 10000
      max_slippage_pct: 0.03
      max_position_usd: 1000

    arb:
      poll_interval_s: 30
      kalshi_market_limit: 100

    metrics:
      health_log_interval_s: 60
      output_file: metrics.json

    websocket:
      url: wss://ws-subscriptions-clob.polymarket.com/ws/market
      heartbeat_timeout_s: 30
      reconnect_base_delay_s: 1.0
      reconnect_max_delay_s: 60.0

    execution:
      min_order_size: 1.0

Environment variables:
    CLOB_WS_URL, CLOB_API_KEY, CLOB_API_SECRET, CLOB_API_PASSPHRASE,
    CLOB_CHAIN_ID, DRY_RUN, KALSHI_API_KEY, KALSHI_API_BASE_URL
"""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional

import structlog

from ...api.kalshi_client import KalshiClient
from ...core.system_state import SystemStateManager
from ...execution.live_executor import GatedExecutionResult, LiveExecutor as GatedLiveExecutor
from ...execution.simulator import ExecutionSimulator
from .arb_detector import ArbDetector
from .execution_guard import ExecutionGuard
from .go_live_controller import GoLiveController, TradingMode
from .live_mode_controller import LiveModeController
from ...data.ingestion.execution_feedback import ExecutionFeedbackTracker
from ...data.ingestion.latency_tracker import LatencyTracker
from ...data.ingestion.trade_flow import TradeFlowAnalyzer
from ...execution.clob_executor import ExecutionRequest, ExecutionResult, LiveExecutor
from ...data.orderbook.market_cache import Phase7MarketCache
from ...data.orderbook.orderbook import OrderBookManager
from ...data.websocket.ws_client import PolymarketWSClient, WSEvent
from ...monitoring.metrics_validator import MetricsValidator
from ...telegram.telegram_live import TelegramLive
from ...telegram.message_formatter import format_error, format_execution_blocked
from ...strategy.orchestrator import MultiStrategyOrchestrator, OrchestratorResult

log = structlog.get_logger()

# ── Constants ─────────────────────────────────────────────────────────────────

_DEFAULT_ARB_POLL_S: float = 30.0          # Kalshi polling interval
_DEFAULT_KALSHI_LIMIT: int = 100           # markets per Kalshi call
_DEFAULT_HEALTH_LOG_S: float = 60.0        # health log interval
_DEFAULT_FEEDBACK_EXPIRE_S: float = 60.0   # feedback expiry interval
_STALE_DATA_THRESHOLD_S: float = 5.0       # flag stale if no WS update in 5 s
_DEPTH_LEVELS: int = 5


# ── Latency event ─────────────────────────────────────────────────────────────


@dataclass
class LatencyEvent:
    """Four-point latency record for a single signal-to-fill cycle.

    All timestamps are Unix epoch seconds (float).

    Attributes:
        correlation_id: Unique ID linking signal → order → fill.
        market_id: Target market.
        data_received_ts: When the WS event landed in the runner.
        signal_generated_ts: When the decision callback returned.
        order_sent_ts: Just before ``LiveExecutor.execute()`` was called.
        fill_received_ts: When ``ExecutionResult`` was returned.
        total_latency_ms: End-to-end latency in milliseconds.
    """

    correlation_id: str
    market_id: str
    data_received_ts: float = field(default_factory=time.time)
    signal_generated_ts: float = 0.0
    order_sent_ts: float = 0.0
    fill_received_ts: float = 0.0
    total_latency_ms: float = 0.0


# ── Phase10PipelineRunner ─────────────────────────────────────────────────────


class Phase10PipelineRunner:
    """Full Phase 10.1 pipeline runner with GO-LIVE gating.

    Composes Phase 7 live-data infrastructure with Phase 10 execution gates
    (GoLiveController, ExecutionGuard) and Phase 9 metrics collection.

    A background task polls Kalshi for arb signal detection; detected signals
    are logged and fed to MetricsValidator but are **never routed to execution**.

    Thread-safety: single asyncio event loop only.
    """

    def __init__(
        self,
        ws_client: PolymarketWSClient,
        orderbook_manager: OrderBookManager,
        market_cache: Phase7MarketCache,
        trade_flow_analyzer: TradeFlowAnalyzer,
        live_executor: LiveExecutor,
        latency_tracker: LatencyTracker,
        feedback_tracker: ExecutionFeedbackTracker,
        go_live_controller: GoLiveController,
        execution_guard: ExecutionGuard,
        arb_detector: ArbDetector,
        kalshi_client: KalshiClient,
        metrics_validator: MetricsValidator,
        market_ids: list[str],
        decision_callback: Optional[Callable] = None,
        arb_poll_interval_s: float = _DEFAULT_ARB_POLL_S,
        health_log_interval_s: float = _DEFAULT_HEALTH_LOG_S,
        depth_levels: int = _DEPTH_LEVELS,
        live_mode_controller: Optional[LiveModeController] = None,
        gated_executor: Optional[GatedLiveExecutor] = None,
        simulator: Optional[ExecutionSimulator] = None,
        telegram: Optional[TelegramLive] = None,
        system_state_manager: Optional[SystemStateManager] = None,
        multi_strategy_orchestrator: Optional[MultiStrategyOrchestrator] = None,
    ) -> None:
        """Initialise the pipeline runner.

        Args:
            ws_client: Configured PolymarketWSClient.
            orderbook_manager: Manages all OrderBook instances.
            market_cache: Phase7MarketCache for live microstructure.
            trade_flow_analyzer: Computes trade flow imbalance.
            live_executor: Places orders via CLOB (paper or live).
            latency_tracker: Records API RTT per execution.
            feedback_tracker: Tracks expected vs actual fills.
            go_live_controller: Phase 10 PAPER/LIVE mode gate.
            execution_guard: Phase 10 pre-trade validation.
            arb_detector: Detects Polymarket vs Kalshi spread opportunities.
            kalshi_client: Read-only Kalshi REST client.
            metrics_validator: Phase 9 metrics accumulator.
            market_ids: Markets to subscribe to.
            decision_callback: Optional async callable
                ``(market_id: str, market_ctx: dict) -> ExecutionRequest | None``.
                If None, runner operates in data-only mode.
            arb_poll_interval_s: Seconds between Kalshi polls.
            health_log_interval_s: Seconds between pipeline health log lines.
            depth_levels: Orderbook depth levels to aggregate.
            live_mode_controller: Phase 10.5 stateless LIVE gate (optional;
                built from go_live_controller config when not provided).
                When not provided the pipeline falls back to PAPER-only via
                the legacy GoLiveController path.
            gated_executor: Phase 10.5 gated live executor (optional).
            simulator: ExecutionSimulator for PAPER mode (optional).
            telegram: TelegramLive alert dispatcher (optional).
            system_state_manager: Phase 10.7 runtime state gate (optional).
                When provided, execution is blocked unless state is RUNNING.
            multi_strategy_orchestrator: Optional Phase 12 orchestrator.
                When provided, each orderbook tick is evaluated by all
                registered strategies before the decision_callback is invoked.
                Conflict-detected ticks are skipped automatically.
        """
        self._ws = ws_client
        self._books = orderbook_manager
        self._cache = market_cache
        self._flow = trade_flow_analyzer
        self._executor = live_executor
        self._latency_tracker = latency_tracker
        self._feedback = feedback_tracker
        self._go_live = go_live_controller
        self._guard = execution_guard
        self._arb = arb_detector
        self._kalshi = kalshi_client
        self._metrics = metrics_validator
        self._market_ids = market_ids
        self._decision_callback = decision_callback
        self._arb_poll_interval = arb_poll_interval_s
        self._health_log_interval = health_log_interval_s
        self._depth_levels = depth_levels
        self._live_ctrl = live_mode_controller
        self._gated_executor = gated_executor
        self._simulator = simulator
        self._telegram = telegram
        self._state_manager = system_state_manager
        self._multi_strategy_orchestrator = multi_strategy_orchestrator

        self._running: bool = False
        self._event_count: int = 0
        self._order_count: int = 0
        self._arb_signals_total: int = 0
        # In-memory metrics snapshot store (Phase 10.7)
        self._metrics_snapshots: list[dict] = []

        log.info(
            "phase10_pipeline_runner_initialized",
            market_count=len(market_ids),
            go_live_mode=go_live_controller.mode.value,
            arb_poll_interval_s=arb_poll_interval_s,
            live_mode_controller_attached=live_mode_controller is not None,
            telegram_attached=telegram is not None,
            system_state_manager_attached=system_state_manager is not None,
        )

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_config(
        cls,
        cfg: dict,
        market_ids: list[str],
        decision_callback: Optional[Callable] = None,
        order_guard: Optional[object] = None,
    ) -> "Phase10PipelineRunner":
        """Build runner from a top-level config dict.

        Args:
            cfg: Config dict (loaded from YAML or constructed in code).
            market_ids: Polymarket condition IDs to subscribe to.
            decision_callback: Optional async order-decision callable.
            order_guard: Optional phase8.OrderGuard for duplicate detection.

        Returns:
            Fully-configured Phase10PipelineRunner.
        """
        ws7 = cfg.get("websocket", {})
        ex7 = cfg.get("execution", {})
        arb_cfg = cfg.get("arb", {})
        metrics_cfg_section = cfg.get("metrics", {})

        # Phase 7 WS client
        ws_client = PolymarketWSClient(
            market_ids=market_ids,
            ws_url=os.getenv(
                "CLOB_WS_URL",
                ws7.get("url", "wss://ws-subscriptions-clob.polymarket.com/ws/market"),
            ),
            api_key=os.getenv("CLOB_API_KEY"),
            heartbeat_timeout_s=float(ws7.get("heartbeat_timeout_s", 30.0)),
            reconnect_base_delay=float(ws7.get("reconnect_base_delay_s", 1.0)),
            reconnect_max_delay=float(ws7.get("reconnect_max_delay_s", 60.0)),
        )

        # Phase 7 executor — DRY_RUN env or go_live.mode=PAPER both force paper
        go_live_mode = str(cfg.get("go_live", {}).get("mode", "PAPER")).upper()
        dry_run = (
            os.getenv("DRY_RUN", "false").lower() == "true"
            or go_live_mode == "PAPER"
        )
        live_executor = LiveExecutor(
            api_key=os.getenv("CLOB_API_KEY", ""),
            api_secret=os.getenv("CLOB_API_SECRET", ""),
            api_passphrase=os.getenv("CLOB_API_PASSPHRASE", ""),
            chain_id=int(os.getenv("CLOB_CHAIN_ID", "137")),
            dry_run=dry_run,
            min_order_size=float(ex7.get("min_order_size", 1.0)),
        )

        # Phase 7 market cache
        pos_cfg = cfg.get("position", {})
        market_cache = Phase7MarketCache(
            default_vol=float(pos_cfg.get("default_vol", 0.02)),
        )

        # Phase 10 components
        go_live_controller = GoLiveController.from_config(cfg)
        execution_guard = ExecutionGuard.from_config(cfg, order_guard=order_guard)
        arb_detector = ArbDetector.from_config(cfg)

        # Kalshi read-only client
        kalshi_client = KalshiClient(
            base_url=os.getenv("KALSHI_API_BASE_URL", "https://trading-api.kalshi.com/trade-api/v2"),
            api_key=os.getenv("KALSHI_API_KEY") or None,
        )

        # Phase 9 metrics validator
        metrics_validator = MetricsValidator.from_config(cfg)

        return cls(
            ws_client=ws_client,
            orderbook_manager=OrderBookManager(),
            market_cache=market_cache,
            trade_flow_analyzer=TradeFlowAnalyzer(
                window_size=int(cfg.get("trade_flow", {}).get("window", 100))
            ),
            live_executor=live_executor,
            latency_tracker=LatencyTracker(),
            feedback_tracker=ExecutionFeedbackTracker(),
            go_live_controller=go_live_controller,
            execution_guard=execution_guard,
            arb_detector=arb_detector,
            kalshi_client=kalshi_client,
            metrics_validator=metrics_validator,
            market_ids=market_ids,
            decision_callback=decision_callback,
            arb_poll_interval_s=float(arb_cfg.get("poll_interval_s", _DEFAULT_ARB_POLL_S)),
            health_log_interval_s=float(
                metrics_cfg_section.get("health_log_interval_s", _DEFAULT_HEALTH_LOG_S)
            ),
            depth_levels=int(ws7.get("depth_levels", _DEPTH_LEVELS)),
        )

    # ── Status helpers ────────────────────────────────────────────────────────

    @property
    def mode(self) -> TradingMode:
        """Current trading mode from GoLiveController."""
        return self._go_live.mode

    def set_metrics_for_go_live(self, metrics: object) -> None:
        """Inject MetricsResult into GoLiveController.

        Call this after a completed paper run to enable GO-LIVE evaluation.

        Args:
            metrics: MetricsResult from MetricsValidator.compute().
        """
        self._go_live.set_metrics(metrics)
        log.info(
            "phase10_go_live_metrics_set",
            mode=self._go_live.mode.value,
            go_live_status=self._go_live.status(),
        )

    # ── Main run loop ─────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Start the Phase 10.1 event-driven pipeline.

        Runs until interrupted or critical failure.
        On unhandled exception: cancel all open orders, then re-raise.
        """
        self._running = True
        correlation_id = str(uuid.uuid4())

        log.info(
            "phase10_pipeline_starting",
            market_count=len(self._market_ids),
            market_ids=self._market_ids,
            go_live_mode=self._go_live.mode.value,
            correlation_id=correlation_id,
        )

        await self._ws.connect()

        background_tasks = [
            asyncio.create_task(self._arb_poll_loop(), name="arb_poll"),
            asyncio.create_task(self._health_log_loop(), name="health_log"),
            asyncio.create_task(
                self._feedback_expire_loop(), name="feedback_expire"
            ),
        ]

        try:
            async for event in self._ws.events():
                if not self._running:
                    break
                await self._handle_event(event)

        except asyncio.CancelledError:
            log.info("phase10_pipeline_cancelled")

        except Exception as exc:  # noqa: BLE001
            log.error(
                "phase10_pipeline_critical_error",
                error=str(exc),
                exc_info=True,
                correlation_id=correlation_id,
            )
            cancelled = await self._executor.cancel_all_open(correlation_id)
            log.warning(
                "phase10_emergency_cancel_all",
                cancelled_count=cancelled,
                correlation_id=correlation_id,
            )
            raise

        finally:
            self._running = False
            for task in background_tasks:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            await self._ws.disconnect()
            await self._kalshi.close()
            log.info(
                "phase10_pipeline_stopped",
                total_events=self._event_count,
                total_orders=self._order_count,
                arb_signals_total=self._arb_signals_total,
            )

    async def stop(self) -> None:
        """Gracefully stop the pipeline."""
        self._running = False
        await self._ws.disconnect()

    # ── Event routing ─────────────────────────────────────────────────────────

    async def _handle_event(self, event: WSEvent) -> None:
        """Route a WS event to the appropriate handler.

        Args:
            event: Incoming WSEvent (orderbook or trade).
        """
        self._event_count += 1

        if event.type == "orderbook":
            await self._handle_orderbook_event(event)
        elif event.type == "trade":
            await self._handle_trade_event(event)
        else:
            log.debug("phase10_unknown_event_type", event_type=event.type)

    async def _handle_orderbook_event(self, event: WSEvent) -> None:
        """Process an orderbook snapshot or delta.

        Pipeline:
          1. Stamp ``data_received_ts``.
          2. Apply to OrderBookManager.
          3. Update Phase7MarketCache with new microstructure.
          4. Stale-data guard.
          5. Invoke ``decision_callback`` if present.
          6. If callback returns a request → gate → execute.
        """
        data_received_ts = time.time()
        market_id = event.market_id

        self._books.apply_ws_event(event.type, market_id, event.data, event.timestamp)

        snap = self._books.snapshot(market_id, self._depth_levels)
        if snap is None:
            log.warning(
                "phase10_orderbook_not_valid",
                market_id=market_id,
                timestamp=event.timestamp,
            )
            self._books.request_resync(market_id)
            return

        # Update market cache with live microstructure
        self._cache.on_orderbook_update(snap)

        # Stale-data guard — skip execution if feed is stale
        if self._cache.is_stale(market_id, _STALE_DATA_THRESHOLD_S):
            log.warning(
                "phase10_stale_market_data",
                market_id=market_id,
                threshold_s=_STALE_DATA_THRESHOLD_S,
            )
            return

        if self._decision_callback is None or not snap.is_valid:
            return

        # Decision callback
        market_ctx = self._cache.get_market_context(market_id)
        market_ctx["orderbook_valid"] = snap.is_valid
        market_ctx["flow_imbalance"] = self._cache.get_trade_flow_imbalance(market_id)

        # Phase 12: Multi-strategy evaluation (PAPER mode enforced in orchestrator)
        if self._multi_strategy_orchestrator is not None:
            orch_result: OrchestratorResult = await self._multi_strategy_orchestrator.run(
                market_id, market_ctx
            )
            # Log result; if conflict detected → skip execution for this tick
            if orch_result.skipped:
                log.info(
                    "phase12_conflict_skip",
                    market_id=market_id,
                    reason="conflict_detected",
                )
                return

        try:
            order_request: Optional[ExecutionRequest] = await self._decision_callback(
                market_id, market_ctx
            )
            signal_generated_ts = time.time()  # stamp after callback returns
        except Exception as exc:  # noqa: BLE001
            log.error(
                "phase10_decision_callback_error",
                market_id=market_id,
                error=str(exc),
                exc_info=True,
            )
            return

        if order_request is None:
            return

        # Capture expected EV from request metadata (recorded in _gated_execute after fill)
        expected_ev = float(getattr(order_request, "expected_ev", 0.0))

        # Build latency event for tracking
        lat_event = LatencyEvent(
            correlation_id=order_request.correlation_id,
            market_id=market_id,
            data_received_ts=data_received_ts,
            signal_generated_ts=signal_generated_ts,
        )

        await self._gated_execute(order_request, market_ctx, lat_event)

    async def _handle_trade_event(self, event: WSEvent) -> None:
        """Process a trade event — update TradeFlowAnalyzer and MarketCache.

        Args:
            event: Trade WSEvent.
        """
        market_id = event.market_id
        data = event.data
        price = float(data.get("price", 0.0))
        size = float(data.get("size", 0.0))
        side = str(data.get("side", "UNKNOWN"))

        self._flow.on_trade(
            market_id=market_id,
            price=price,
            size=size,
            side=side,
            timestamp=event.timestamp,
        )

        self._cache.on_trade(
            market_id=market_id,
            price=price,
            size=size,
            side=side,
            timestamp=event.timestamp,
        )

    # ── Gated execution ───────────────────────────────────────────────────────

    async def _gated_execute(
        self,
        request: ExecutionRequest,
        market_ctx: dict,
        lat_event: LatencyEvent,
    ) -> Optional[ExecutionResult]:
        """Apply Phase 10.5 strict gating then execute the order.

        The control layer (LiveModeController) is ALWAYS executed first.
        Based on its result the order is routed to either the gated live
        executor (LIVE path) or the simulator (PAPER fallback).

        Gates (in order):
          1. LiveModeController.is_live_enabled() — stateless, re-checked here.
          2a. LIVE path  → GatedLiveExecutor (ExecutionGuard + Redis dedup inside).
          2b. PAPER path → ExecutionSimulator or legacy LiveExecutor (dry_run).

        Args:
            request: Validated ExecutionRequest from decision callback.
            market_ctx: Current market context dict.
            lat_event: Latency tracking record (mutated in-place).

        Returns:
            ExecutionResult if executed, None if blocked by any gate.
        """
        trade_size_usd = float(request.size)
        expected_ev = float(getattr(request, "expected_ev", 0.0))

        # ── Phase 10.7: SystemStateManager gate (ALWAYS first) ───────────────
        if self._state_manager is not None and not self._state_manager.is_execution_allowed():
            state_snap = self._state_manager.snapshot()
            block_reason = f"system_state:{state_snap['state']}:{state_snap['reason']}"
            log.warning(
                "phase10_execution_blocked_system_state",
                market_id=request.market_id,
                state=state_snap["state"],
                reason=state_snap["reason"],
                correlation_id=request.correlation_id,
            )
            self._metrics.record_fill(filled=False)
            await self._notify_telegram_async(
                "system_state_blocked",
                market_id=request.market_id,
                reason=block_reason,
                state=state_snap["state"],
                correlation_id=request.correlation_id,
            )
            return None

        # ── CONTROL LAYER: LiveModeController (ALWAYS first) ──────────────────
        live_enabled = (
            self._live_ctrl.is_live_enabled()
            if self._live_ctrl is not None
            else False
        )

        if not live_enabled:
            # PAPER fallback — run through simulator or legacy dry-run executor.
            block_reason = (
                self._live_ctrl.get_block_reason()
                if self._live_ctrl is not None
                else "no_live_mode_controller"
            )
            log.debug(
                "phase10_execution_paper_fallback",
                market_id=request.market_id,
                block_reason=block_reason,
            )
            await self._notify_telegram_async(
                "paper_fallback",
                market_id=request.market_id,
                reason=block_reason,
            )
            # Legacy GoLiveController gate (maintained for backwards compatibility)
            if not self._go_live.allow_execution(trade_size_usd=trade_size_usd):
                self._metrics.record_fill(filled=False)
                return None

            # ── Paper execution (simulator preferred, legacy executor fallback) ──
            if self._simulator is not None:
                orderbook = market_ctx.get("orderbook", {})
                lat_event.order_sent_ts = time.time()
                self._order_count += 1
                try:
                    sim_result = await self._simulator.execute(
                        order_id=request.correlation_id,
                        market_id=request.market_id,
                        side=request.side,
                        expected_price=request.price,
                        size_usd=trade_size_usd,
                        orderbook=orderbook,
                    )
                except Exception as exc:  # noqa: BLE001
                    log.error(
                        "phase10_simulator_error",
                        market_id=request.market_id,
                        correlation_id=request.correlation_id,
                        error=str(exc),
                        exc_info=True,
                    )
                    self._metrics.record_fill(filled=False)
                    return None
                lat_event.fill_received_ts = time.time()
                lat_event.total_latency_ms = (
                    lat_event.fill_received_ts - lat_event.data_received_ts
                ) * 1000.0
                self._metrics.record_latency(lat_event.total_latency_ms)
                self._metrics.record_fill(filled=sim_result.success)
                self._metrics.record_ev_signal(
                    expected_ev=expected_ev, actual_ev=0.0
                )
                self._metrics.record_pnl_sample(cumulative_pnl=0.0)
                self._go_live.record_trade(size_usd=trade_size_usd)
                return ExecutionResult(
                    order_id=sim_result.order_id,
                    status="submitted" if sim_result.success else "rejected",
                    filled_size=sim_result.filled_size,
                    avg_price=sim_result.simulated_price,
                    latency_ms=lat_event.total_latency_ms,
                    correlation_id=request.correlation_id,
                    is_paper=True,
                )
            # Fallback to legacy Phase 7 executor (dry_run enforced upstream)
            return await self._legacy_execute(
                request, market_ctx, lat_event, expected_ev, trade_size_usd
            )

        # ── LIVE PATH: GatedLiveExecutor ──────────────────────────────────────
        if self._gated_executor is not None:
            lat_event.order_sent_ts = time.time()
            self._order_count += 1

            await self._notify_telegram_async(
                "live_enabled",
                market_id=request.market_id,
            )

            gated_result = await self._gated_executor.execute(request, market_ctx)

            lat_event.fill_received_ts = time.time()
            lat_event.total_latency_ms = (
                lat_event.fill_received_ts - lat_event.data_received_ts
            ) * 1000.0

            if not gated_result.allowed:
                log.warning(
                    "phase10_live_execution_blocked",
                    market_id=request.market_id,
                    reason=gated_result.block_reason,
                )
                self._metrics.record_fill(filled=False)
                await self._notify_telegram_async(
                    "live_disabled",
                    market_id=request.market_id,
                    reason=gated_result.block_reason,
                )
                return None

            result = gated_result.result
            if result is None:
                self._metrics.record_fill(filled=False)
                return None

            self._metrics.record_latency(lat_event.total_latency_ms)
            filled = result.status in ("filled", "partial", "submitted")
            self._metrics.record_fill(filled=filled)

            actual_ev = 0.0
            if result.status in ("filled", "partial") and result.avg_price > 0:
                mid = float(market_ctx.get("mid", request.price))
                actual_ev = result.filled_size * abs(mid - result.avg_price)

            self._metrics.record_ev_signal(
                expected_ev=expected_ev, actual_ev=actual_ev
            )
            self._metrics.record_pnl_sample(cumulative_pnl=actual_ev)
            self._go_live.record_trade(size_usd=trade_size_usd)
            self._cache.on_execution_latency(
                request.market_id, lat_event.total_latency_ms
            )

            exec_success = result.status in ("filled", "partial", "submitted")
            tg_event = "execution_success" if exec_success else "execution_failure"
            await self._notify_telegram_async(
                tg_event,
                market_id=request.market_id,
                status=result.status,
                latency_ms=round(lat_event.total_latency_ms, 2),
            )

            log.info(
                "phase10_live_order_executed",
                correlation_id=request.correlation_id,
                market_id=request.market_id,
                order_id=result.order_id,
                status=result.status,
                latency_ms=round(lat_event.total_latency_ms, 2),
                is_paper=result.is_paper,
            )
            return result

        # Fallback: no gated executor — use legacy Phase 7 executor
        return await self._legacy_execute(
            request, market_ctx, lat_event, expected_ev, trade_size_usd
        )

    async def _legacy_execute(
        self,
        request: ExecutionRequest,
        market_ctx: dict,
        lat_event: LatencyEvent,
        expected_ev: float,
        trade_size_usd: float,
    ) -> Optional[ExecutionResult]:
        """Legacy execution path via Phase 7 LiveExecutor.

        Retained for backwards compatibility when no gated executor or
        simulator is configured.

        Args:
            request: ExecutionRequest.
            market_ctx: Market context dict.
            lat_event: LatencyEvent (mutated in-place).
            expected_ev: Expected EV from signal.
            trade_size_usd: Trade size in USD.

        Returns:
            ExecutionResult or None if guard rejects.
        """
        # ── ExecutionGuard (Phase 10 pre-trade check) ─────────────────────────
        liquidity_usd = float(market_ctx.get("depth", 0.0))
        spread = float(market_ctx.get("spread", 0.02))
        slippage_pct = spread * 0.5

        guard_sig = (
            f"{request.market_id}:{request.side}:"
            f"{round(request.price, 4)}:{round(request.size, 2)}"
        )

        validation = self._guard.validate(
            market_id=request.market_id,
            side=request.side,
            price=request.price,
            size_usd=trade_size_usd,
            liquidity_usd=liquidity_usd,
            slippage_pct=slippage_pct,
            order_guard_signature=guard_sig,
        )

        if not validation.passed:
            log.warning(
                "phase10_execution_rejected_guard",
                market_id=request.market_id,
                reason=validation.reason,
            )
            self._metrics.record_fill(filled=False)
            return None

        # ── Execute ───────────────────────────────────────────────────────────
        lat_event.order_sent_ts = time.time()
        self._order_count += 1

        result = await self._executor.execute(request, market_ctx)

        lat_event.fill_received_ts = time.time()
        lat_event.total_latency_ms = (
            lat_event.fill_received_ts - lat_event.data_received_ts
        ) * 1000.0

        self._metrics.record_latency(lat_event.total_latency_ms)
        filled = result.status in ("filled", "partial", "submitted")
        self._metrics.record_fill(filled=filled)

        actual_ev = 0.0
        if result.status in ("filled", "partial") and result.avg_price > 0:
            mid = float(market_ctx.get("mid", request.price))
            actual_ev = result.filled_size * abs(mid - result.avg_price)

        self._metrics.record_ev_signal(expected_ev=expected_ev, actual_ev=actual_ev)
        self._metrics.record_pnl_sample(cumulative_pnl=actual_ev)
        self._go_live.record_trade(size_usd=trade_size_usd)
        self._cache.on_execution_latency(request.market_id, result.latency_ms)

        sample = self._latency_tracker.record(
            market_id=request.market_id,
            order_id=result.order_id,
            latency_ms=result.latency_ms,
            correlation_id=request.correlation_id,
        )

        if result.status in ("submitted", "partial") and result.order_id:
            self._feedback.record_expected(
                order_id=result.order_id,
                market_id=request.market_id,
                expected_fill_prob=market_ctx.get("fill_prob", 0.5),
                expected_slippage=slippage_pct,
                limit_price=request.price,
                latency_ms=result.latency_ms,
                correlation_id=request.correlation_id,
            )

        if result.status == "filled":
            self._feedback.record_actual(
                order_id=result.order_id,
                actual_fill=True,
                avg_fill_price=result.avg_price,
                actual_fill_size=result.filled_size,
                correlation_id=request.correlation_id,
            )

        log.info(
            "phase10_order_executed",
            correlation_id=request.correlation_id,
            market_id=request.market_id,
            order_id=result.order_id,
            status=result.status,
            latency_ms=round(result.latency_ms, 2),
            e2e_latency_ms=round(lat_event.total_latency_ms, 2),
            is_paper=result.is_paper,
            latency_spike=sample.is_spike,
        )

        return result

    async def _notify_telegram_async(self, event: str, **kwargs: object) -> None:
        """Send a non-blocking Telegram alert for a pipeline event.

        Never raises — all failures are caught and logged.

        Args:
            event: Event type string (e.g. ``"live_enabled"``, ``"execution_success"``).
            **kwargs: Additional context for the message.
        """
        if self._telegram is None:
            return
        try:
            market_id = str(kwargs.get("market_id", ""))
            reason = str(kwargs.get("reason", ""))
            status = str(kwargs.get("status", ""))
            latency_ms = kwargs.get("latency_ms", 0)
            state = str(kwargs.get("state", ""))
            correlation_id = str(kwargs.get("correlation_id", ""))

            if event == "system_state_blocked":
                msg = format_execution_blocked(
                    market_id=market_id,
                    reason=reason,
                    state=state,
                    correlation_id=correlation_id,
                )
                await self._telegram.alert_error(
                    error=f"execution_blocked:{state}",
                    context=msg,
                    correlation_id=correlation_id or None,
                )
            elif event == "live_enabled":
                msg = f"🟢 LIVE MODE ENABLED | market={market_id[:24]}"
                await self._telegram.alert_error(
                    error=f"pipeline_event:{event}",
                    context=msg,
                )
            elif event == "live_disabled":
                msg = f"🔴 LIVE MODE DISABLED | market={market_id[:24]} reason={reason}"
                await self._telegram.alert_error(
                    error=f"pipeline_event:{event}",
                    context=msg,
                )
            elif event == "execution_success":
                msg = (
                    f"✅ LIVE EXECUTION SUCCESS | market={market_id[:24]}"
                    f" status={status} latency={latency_ms}ms"
                )
                await self._telegram.alert_error(
                    error=f"pipeline_event:{event}",
                    context=msg,
                )
            elif event == "execution_failure":
                msg = (
                    f"❌ LIVE EXECUTION FAILURE | market={market_id[:24]}"
                    f" status={status}"
                )
                await self._telegram.alert_error(
                    error=f"pipeline_event:{event}",
                    context=msg,
                )
            elif event == "paper_fallback":
                msg = f"📄 PAPER FALLBACK | market={market_id[:24]} reason={reason}"
                await self._telegram.alert_error(
                    error=f"pipeline_event:{event}",
                    context=msg,
                )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "phase10_telegram_notify_failed",
                pipeline_event=event,
                error=str(exc),
            )

    # ── Background: Kalshi arb polling ────────────────────────────────────────

    async def _arb_poll_loop(self) -> None:
        """Periodically poll Kalshi and run arb detection.

        Detected signals are logged and counted but NEVER routed to execution.
        """
        while self._running:
            await asyncio.sleep(self._arb_poll_interval)
            if not self._running:
                break
            await self._run_arb_scan()

    async def _run_arb_scan(self) -> None:
        """Fetch Kalshi markets and run one arb detection pass."""
        try:
            kalshi_markets = await asyncio.wait_for(
                self._kalshi.get_markets(limit=_DEFAULT_KALSHI_LIMIT),
                timeout=10.0,
            )
        except asyncio.TimeoutError:
            log.warning("phase10_kalshi_poll_timeout")
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("phase10_kalshi_poll_error", error=str(exc))
            return

        # Build Polymarket snapshot from cache (current mid prices).
        # Title is set to market_id as a placeholder — ArbDetector will only
        # match via the explicit market_map config.  Fuzzy title matching will
        # not produce results here because market IDs are hex strings, not
        # human-readable titles.  Configure arb_detector.market_map in the
        # YAML config to enable exact Polymarket → Kalshi matching.
        poly_markets = [
            {
                "id": mid,
                "yes_price": self._cache.get_mid(mid),
                "title": mid,
            }
            for mid in self._cache.market_ids()
        ]

        if not poly_markets:
            return

        signals = self._arb.detect(
            polymarket_markets=poly_markets,
            kalshi_markets=kalshi_markets,
        )

        self._arb_signals_total += len(signals)

        for sig in signals:
            log.info(
                "phase10_arb_signal",
                polymarket_id=sig.get("polymarket_id"),
                kalshi_ticker=sig.get("kalshi_ticker"),
                spread=sig.get("spread"),
                direction=sig.get("direction"),
                note="monitoring_only_no_execution",
            )

    # ── Background: health log ────────────────────────────────────────────────

    async def _health_log_loop(self) -> None:
        """Periodically log pipeline health and metrics snapshot."""
        while self._running:
            await asyncio.sleep(self._health_log_interval)
            if not self._running:
                break

            ws_stats = self._ws.stats()
            global_latency = self._latency_tracker.global_stats()
            go_live_status = self._go_live.status()

            log.info(
                "phase10_pipeline_health",
                go_live_mode=go_live_status["mode"],
                trades_today=go_live_status["trades_today"],
                capital_deployed_usd=go_live_status["capital_deployed_usd"],
                ws_messages=ws_stats.messages_received,
                ws_events=ws_stats.events_emitted,
                ws_reconnects=ws_stats.reconnects,
                total_events=self._event_count,
                total_orders=self._order_count,
                arb_signals_total=self._arb_signals_total,
                latency_p95_ms=global_latency.p95_ms if global_latency else None,
                latency_mean_ms=global_latency.mean_ms if global_latency else None,
            )

            # Phase 10.7: persist metrics snapshot in memory
            snapshot: dict = {
                "timestamp": time.time(),
                "go_live_mode": go_live_status["mode"],
                "trades_today": go_live_status["trades_today"],
                "total_orders": self._order_count,
                "total_events": self._event_count,
                "latency_p95_ms": global_latency.p95_ms if global_latency else None,
            }
            self._metrics_snapshots.append(snapshot)
            # Keep only the last 1440 snapshots (~24h at 1-min intervals)
            if len(self._metrics_snapshots) > 1440:
                self._metrics_snapshots = self._metrics_snapshots[-1440:]

    # ── Background: feedback expiry ───────────────────────────────────────────

    async def _feedback_expire_loop(self) -> None:
        """Periodically expire stale pending feedback records."""
        while self._running:
            await asyncio.sleep(_DEFAULT_FEEDBACK_EXPIRE_S)
            if not self._running:
                break
            expired = self._feedback.expire_pending(max_age_s=300.0)
            if expired > 0:
                log.warning(
                    "phase10_feedback_expired",
                    expired_count=expired,
                    pending_remaining=self._feedback.pending_count(),
                )
