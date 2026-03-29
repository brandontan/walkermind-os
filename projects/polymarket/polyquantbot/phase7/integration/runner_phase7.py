"""Phase 7 — Event-driven runner integration.

Wires the Phase 7 live data pipeline into the Phase 6.6 architecture:

    WS Feed → OrderBook → MarketCache (microstructure)
                        → TradeFlowAnalyzer
                        → Phase66Integrator (existing decision engine)
                        → LiveExecutor (real order placement)
                        → LatencyTracker
                        → ExecutionFeedbackTracker

Entry point: Phase7Runner.run() — single long-running async coroutine.
Connects WS, streams events, routes to appropriate handlers.
No polling inside the event loop — fully event-driven.

Safety:
    - WS reconnect handled by PolymarketWSClient (exponential backoff).
    - Orderbook sanity check on every update (crossed book → reset + resync).
    - Pre-trade validation in LiveExecutor (zero liquidity, invalid book).
    - Cancel all open orders on unhandled exception (emergency shutdown).
    - Safe idle fallback if data is stale.

Usage::

    # In main():
    import yaml
    from phase6_6.integration.runner_patch import Phase66Integrator
    from phase7.integration.runner_phase7 import Phase7Runner

    with open("phase7/config.yaml") as f:
        cfg = yaml.safe_load(f)

    runner = Phase7Runner.from_config(cfg, market_ids=["0xabc..."])
    await runner.run()
"""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Optional

import structlog
import yaml

from ..analytics.execution_feedback import ExecutionFeedbackTracker
from ..analytics.latency_tracker import LatencyTracker
from ..analytics.trade_flow import TradeFlowAnalyzer
from ..core.execution.live_executor import ExecutionRequest, ExecutionResult, LiveExecutor
from ..engine.market_cache_patch import Phase7MarketCache
from ..engine.orderbook import OrderBookManager
from ..infra.ws_client import PolymarketWSClient, WSEvent

log = structlog.get_logger()

# ── Constants ─────────────────────────────────────────────────────────────────

_STALE_DATA_THRESHOLD_S: float = 5.0    # flag stale if no WS update in 5s
_FEEDBACK_EXPIRE_INTERVAL_S: float = 60.0   # expire pending feedback every 60s
_HEALTH_LOG_INTERVAL_S: float = 30.0    # log pipeline health every 30s


# ── Phase7Runner ──────────────────────────────────────────────────────────────

class Phase7Runner:
    """Event-driven Phase 7 runner.

    Connects to Polymarket WS feed and routes events through:
        OrderBookManager → Phase7MarketCache → (decision engine callback)
        TradeFlowAnalyzer → Phase7MarketCache
        LiveExecutor → LatencyTracker → ExecutionFeedbackTracker

    The decision_callback is invoked on every orderbook update with the
    current market context. This is where Phase 6.6 signal evaluation,
    SENTINEL risk check, and order routing happen (supplied externally).

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
        market_ids: list[str],
        decision_callback: Optional[Callable] = None,
        depth_levels: int = 5,
    ) -> None:
        """Initialise the runner.

        Args:
            ws_client: Configured PolymarketWSClient.
            orderbook_manager: Manages all OrderBook instances.
            market_cache: Phase7MarketCache for storing microstructure.
            trade_flow_analyzer: Computes trade flow imbalance.
            live_executor: Places live orders via py-clob-client.
            latency_tracker: Records API RTT per execution.
            feedback_tracker: Tracks expected vs actual fills.
            market_ids: Markets to subscribe to.
            decision_callback: Optional async callable(market_id, market_ctx) → ExecutionRequest | None.
                If None, runner operates in data-only mode (no orders placed).
            depth_levels: Orderbook depth levels to aggregate.
        """
        self._ws = ws_client
        self._books = orderbook_manager
        self._cache = market_cache
        self._flow = trade_flow_analyzer
        self._executor = live_executor
        self._latency = latency_tracker
        self._feedback = feedback_tracker
        self._market_ids = market_ids
        self._decision_callback = decision_callback
        self._depth_levels = depth_levels

        self._running: bool = False
        self._event_count: int = 0
        self._order_count: int = 0

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_config(
        cls,
        cfg: dict,
        market_ids: list[str],
        decision_callback: Optional[Callable] = None,
    ) -> "Phase7Runner":
        """Build runner from top-level config dict.

        Args:
            cfg: Config dict (loaded from phase7/config.yaml or phase6_6/config.yaml).
            market_ids: Markets to subscribe to.
            decision_callback: Optional async callable for order decisions.
        """
        ws7 = cfg.get("websocket", {})
        ex7 = cfg.get("execution", {})

        ws_client = PolymarketWSClient(
            market_ids=market_ids,
            ws_url=os.getenv("CLOB_WS_URL", ws7.get("url", "wss://ws-subscriptions-clob.polymarket.com/ws/market")),
            api_key=os.getenv("CLOB_API_KEY"),
            heartbeat_timeout_s=float(ws7.get("heartbeat_timeout_s", 30.0)),
            reconnect_base_delay=float(ws7.get("reconnect_base_delay_s", 1.0)),
            reconnect_max_delay=float(ws7.get("reconnect_max_delay_s", 60.0)),
        )

        dry_run = os.getenv("DRY_RUN", "false").lower() == "true"
        live_executor = LiveExecutor(
            api_key=os.getenv("CLOB_API_KEY", ""),
            api_secret=os.getenv("CLOB_API_SECRET", ""),
            api_passphrase=os.getenv("CLOB_API_PASSPHRASE", ""),
            chain_id=int(os.getenv("CLOB_CHAIN_ID", "137")),
            dry_run=dry_run,
            min_order_size=float(ex7.get("min_order_size", 1.0)),
        )

        pos_cfg = cfg.get("position", {})
        market_cache = Phase7MarketCache(
            default_vol=float(pos_cfg.get("default_vol", 0.02)),
        )

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
            market_ids=market_ids,
            decision_callback=decision_callback,
            depth_levels=int(ws7.get("depth_levels", 5)),
        )

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Start the Phase 7 event-driven pipeline.

        Runs until interrupted or critical failure.
        On exception: cancel all open orders, then re-raise.
        """
        self._running = True
        correlation_id = str(uuid.uuid4())

        log.info(
            "phase7_runner_starting",
            market_count=len(self._market_ids),
            market_ids=self._market_ids,
            correlation_id=correlation_id,
        )

        await self._ws.connect()

        # Start background maintenance tasks
        maintenance_tasks = [
            asyncio.create_task(self._feedback_expire_loop(), name="feedback_expire"),
            asyncio.create_task(self._health_log_loop(), name="health_log"),
        ]

        try:
            async for event in self._ws.events():
                if not self._running:
                    break
                await self._handle_event(event)

        except asyncio.CancelledError:
            log.info("phase7_runner_cancelled")

        except Exception as exc:
            log.error(
                "phase7_runner_critical_error",
                error=str(exc),
                exc_info=True,
                correlation_id=correlation_id,
            )
            # Emergency: cancel all open orders before propagating
            cancelled = await self._executor.cancel_all_open(correlation_id)
            log.warning(
                "phase7_emergency_cancel_all",
                cancelled_count=cancelled,
                correlation_id=correlation_id,
            )
            raise

        finally:
            self._running = False
            for task in maintenance_tasks:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            await self._ws.disconnect()
            log.info(
                "phase7_runner_stopped",
                total_events=self._event_count,
                total_orders=self._order_count,
            )

    async def stop(self) -> None:
        """Gracefully stop the runner."""
        self._running = False
        await self._ws.disconnect()

    # ── Event routing ─────────────────────────────────────────────────────────

    async def _handle_event(self, event: WSEvent) -> None:
        """Route a WS event to the correct handler."""
        self._event_count += 1

        if event.type == "orderbook":
            await self._handle_orderbook_event(event)
        elif event.type == "trade":
            await self._handle_trade_event(event)
        else:
            log.debug("phase7_unknown_event_type", event_type=event.type)

    async def _handle_orderbook_event(self, event: WSEvent) -> None:
        """Process orderbook snapshot or delta.

        1. Apply to OrderBook.
        2. Sanity check (crossed → reset + log).
        3. Update Phase7MarketCache with new microstructure.
        4. Invoke decision callback if present.
        """
        market_id = event.market_id
        self._books.apply_ws_event(event.type, market_id, event.data, event.timestamp)

        snap = self._books.snapshot(market_id, self._depth_levels)
        if snap is None:
            # Book not yet valid (first delta before snapshot) — request resync
            log.warning(
                "phase7_orderbook_not_valid",
                market_id=market_id,
                timestamp=event.timestamp,
            )
            self._books.request_resync(market_id)
            return

        # Update cache with live microstructure
        self._cache.on_orderbook_update(snap)

        # Stale check
        if self._cache.is_stale(market_id, _STALE_DATA_THRESHOLD_S):
            log.warning(
                "phase7_stale_market_data",
                market_id=market_id,
                threshold_s=_STALE_DATA_THRESHOLD_S,
            )
            return

        # Decision callback
        if self._decision_callback is not None and snap.is_valid:
            market_ctx = self._cache.get_market_context(market_id)
            market_ctx["orderbook_valid"] = snap.is_valid
            market_ctx["flow_imbalance"] = self._cache.get_trade_flow_imbalance(market_id)

            try:
                order_request: Optional[ExecutionRequest] = await self._decision_callback(
                    market_id, market_ctx
                )
                if order_request is not None:
                    await self._execute_order(order_request, market_ctx)
            except Exception as exc:  # noqa: BLE001
                log.error(
                    "phase7_decision_callback_error",
                    market_id=market_id,
                    error=str(exc),
                    exc_info=True,
                )

    async def _handle_trade_event(self, event: WSEvent) -> None:
        """Process a trade event.

        1. Update TradeFlowAnalyzer.
        2. Update Phase7MarketCache.
        3. Cross-check with pending feedback records (fill confirmation).
        """
        market_id = event.market_id
        data = event.data
        price = float(data.get("price", 0.0))
        size = float(data.get("size", 0.0))
        side = str(data.get("side", "UNKNOWN"))
        trade_id = str(data.get("trade_id", ""))

        # Update trade flow analyzer
        flow_result = self._flow.on_trade(
            market_id=market_id,
            price=price,
            size=size,
            side=side,
            timestamp=event.timestamp,
        )

        # Update cache
        self._cache.on_trade(
            market_id=market_id,
            price=price,
            size=size,
            side=side,
            timestamp=event.timestamp,
        )

        log.debug(
            "phase7_trade_processed",
            market_id=market_id,
            trade_id=trade_id,
            price=price,
            size=size,
            side=side,
            flow_imbalance=flow_result.imbalance,
        )

    async def _execute_order(
        self,
        request: ExecutionRequest,
        market_ctx: dict,
    ) -> Optional[ExecutionResult]:
        """Execute an order and record latency + feedback.

        Args:
            request: Order to execute.
            market_ctx: Current market context dict.

        Returns:
            ExecutionResult or None if not submitted.
        """
        self._order_count += 1
        cid = request.correlation_id

        result = await self._executor.execute(request, market_ctx)

        # Record latency
        sample = self._latency.record(
            market_id=request.market_id,
            order_id=result.order_id,
            latency_ms=result.latency_ms,
            correlation_id=cid,
        )

        # Update cache latency
        self._cache.on_execution_latency(request.market_id, result.latency_ms)

        # Register expected feedback (only for submitted/partial orders)
        if result.status in ("submitted", "partial") and result.order_id:
            expected_slippage = market_ctx.get("spread", 0.02) * 0.5
            expected_fill_prob = market_ctx.get("fill_prob", 0.5)

            self._feedback.record_expected(
                order_id=result.order_id,
                market_id=request.market_id,
                expected_fill_prob=expected_fill_prob,
                expected_slippage=expected_slippage,
                limit_price=request.price,
                latency_ms=result.latency_ms,
                correlation_id=cid,
            )

        # If immediately filled, record actual right away
        if result.status == "filled":
            self._feedback.record_actual(
                order_id=result.order_id,
                actual_fill=True,
                avg_fill_price=result.avg_price,
                actual_fill_size=result.filled_size,
                correlation_id=cid,
            )

        log.info(
            "phase7_order_executed",
            correlation_id=cid,
            market_id=request.market_id,
            order_id=result.order_id,
            status=result.status,
            latency_ms=result.latency_ms,
            latency_spike=sample.is_spike,
            is_paper=result.is_paper,
        )

        return result

    # ── Background maintenance loops ──────────────────────────────────────────

    async def _feedback_expire_loop(self) -> None:
        """Periodically expire stale pending feedback records."""
        while self._running:
            await asyncio.sleep(_FEEDBACK_EXPIRE_INTERVAL_S)
            expired = self._feedback.expire_pending(max_age_s=300.0)
            if expired > 0:
                log.warning(
                    "phase7_feedback_expired",
                    expired_count=expired,
                    pending_remaining=self._feedback.pending_count(),
                )

    async def _health_log_loop(self) -> None:
        """Periodically log pipeline health metrics."""
        while self._running:
            await asyncio.sleep(_HEALTH_LOG_INTERVAL_S)

            ws_stats = self._ws.stats()
            feedback_summary = self._feedback.calibration_summary()
            global_latency = self._latency.global_stats()

            log.info(
                "phase7_pipeline_health",
                ws_messages=ws_stats.messages_received,
                ws_events=ws_stats.events_emitted,
                ws_reconnects=ws_stats.reconnects,
                ws_heartbeat_timeouts=ws_stats.heartbeat_timeouts,
                total_events=self._event_count,
                total_orders=self._order_count,
                feedback_fill_rate=feedback_summary.get("fill_rate", 0.0),
                feedback_mean_fill_error=feedback_summary.get("mean_fill_error", 0.0),
                feedback_pending=feedback_summary.get("pending_orders", 0),
                latency_p95_ms=global_latency.p95_ms if global_latency else None,
                latency_mean_ms=global_latency.mean_ms if global_latency else None,
            )
