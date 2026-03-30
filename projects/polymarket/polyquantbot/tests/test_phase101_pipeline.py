"""Phase 10.1 — Pipeline Integration Tests.

Validates the full Phase10PipelineRunner wiring:

  TR-01  PAPER mode — GoLiveController blocks execution
  TR-02  LIVE mode  — GoLiveController allows execution when metrics pass
  TR-03  ExecutionGuard rejects low-liquidity order in pipeline
  TR-04  ExecutionGuard rejects over-sized position in pipeline
  TR-05  Arb signals detected but not routed to execution
  TR-06  Latency event total_latency_ms is positive after execution
  TR-07  MetricsValidator records fill on each gated execution
  TR-08  MetricsValidator records latency from execution result
  TR-09  PAPER mode forces dry_run on LiveExecutor via from_config
  TR-10  GoLiveController daily trade counter increments on successful execute
  TR-11  Cache miss (stale data) skips execution silently
  TR-12  Arb poll loop handles Kalshi client timeout without crash
  TR-13  LatencyEvent fields populated correctly through pipeline
  TR-14  Pipeline stop() sets _running = False
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_passing_metrics(
    ev_capture_ratio: float = 0.80,
    fill_rate: float = 0.65,
    p95_latency: float = 300.0,
    drawdown: float = 0.04,
) -> object:
    """Duck-typed MetricsResult with all gates passing."""

    class _FakeMetrics:
        pass

    m = _FakeMetrics()
    m.ev_capture_ratio = ev_capture_ratio
    m.fill_rate = fill_rate
    m.p95_latency = p95_latency
    m.drawdown = drawdown
    return m


@dataclass
class _FakeExecutionResult:
    """Minimal ExecutionResult for test assertions."""

    order_id: str = "test-order-001"
    status: str = "submitted"
    filled_size: float = 0.0
    avg_price: float = 0.0
    latency_ms: float = 12.0
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    error: Optional[str] = None
    is_paper: bool = True


@dataclass
class _FakeExecutionRequest:
    """Minimal ExecutionRequest for test assertions."""

    market_id: str = "0xabc123"
    side: str = "YES"
    price: float = 0.62
    size: float = 100.0
    order_type: str = "LIMIT"
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    expected_ev: float = 0.05


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_runner(
    go_live_mode: str = "PAPER",
    max_position_usd: float = 500.0,
    min_liquidity_usd: float = 10_000.0,
    executor_status: str = "submitted",
    kalshi_markets: Optional[list] = None,
):
    """Build a Phase10PipelineRunner with all external deps stubbed out."""
    from projects.polymarket.polyquantbot.phase10.arb_detector import ArbDetector
    from projects.polymarket.polyquantbot.phase10.execution_guard import ExecutionGuard
    from projects.polymarket.polyquantbot.phase10.go_live_controller import (
        GoLiveController,
        TradingMode,
    )
    from projects.polymarket.polyquantbot.phase10.pipeline_runner import (
        Phase10PipelineRunner,
    )
    from projects.polymarket.polyquantbot.phase7.analytics.execution_feedback import (
        ExecutionFeedbackTracker,
    )
    from projects.polymarket.polyquantbot.phase7.analytics.latency_tracker import (
        LatencyTracker,
    )
    from projects.polymarket.polyquantbot.phase7.analytics.trade_flow import (
        TradeFlowAnalyzer,
    )
    from projects.polymarket.polyquantbot.phase7.engine.market_cache_patch import (
        Phase7MarketCache,
    )
    from projects.polymarket.polyquantbot.phase7.engine.orderbook import (
        OrderBookManager,
    )
    from projects.polymarket.polyquantbot.phase9.metrics_validator import (
        MetricsValidator,
    )

    # Stub WS client — never actually connects
    ws_client = MagicMock()
    ws_client.connect = AsyncMock()
    ws_client.disconnect = AsyncMock()
    ws_client.stats = MagicMock(
        return_value=MagicMock(
            messages_received=0,
            events_emitted=0,
            reconnects=0,
            heartbeat_timeouts=0,
        )
    )

    # Stub LiveExecutor
    fake_result = _FakeExecutionResult(status=executor_status, is_paper=True)
    executor = MagicMock()
    executor.execute = AsyncMock(return_value=fake_result)
    executor.cancel_all_open = AsyncMock(return_value=0)

    # Stub KalshiClient
    kalshi = MagicMock()
    kalshi.get_markets = AsyncMock(return_value=kalshi_markets or [])
    kalshi.close = AsyncMock()

    # Real components
    go_live_controller = GoLiveController(
        mode=TradingMode(go_live_mode),
        max_trades_per_day=1000,
        max_capital_usd=50_000.0,
    )
    execution_guard = ExecutionGuard(
        min_liquidity_usd=min_liquidity_usd,
        max_slippage_pct=0.03,
        max_position_usd=max_position_usd,
    )

    runner = Phase10PipelineRunner(
        ws_client=ws_client,
        orderbook_manager=OrderBookManager(),
        market_cache=Phase7MarketCache(),
        trade_flow_analyzer=TradeFlowAnalyzer(window_size=50),
        live_executor=executor,
        latency_tracker=LatencyTracker(),
        feedback_tracker=ExecutionFeedbackTracker(),
        go_live_controller=go_live_controller,
        execution_guard=execution_guard,
        arb_detector=ArbDetector(spread_threshold=0.04),
        kalshi_client=kalshi,
        metrics_validator=MetricsValidator(min_trades=0),
        market_ids=["0xabc123"],
        decision_callback=None,
        arb_poll_interval_s=9999.0,  # don't fire during test
        health_log_interval_s=9999.0,
    )
    return runner, executor, kalshi, go_live_controller, execution_guard


# ══════════════════════════════════════════════════════════════════════════════
# TR-01 — PAPER mode blocks execution
# ══════════════════════════════════════════════════════════════════════════════


class TestPaperModeBlocksExecution:
    """TR-01 — GoLiveController in PAPER mode returns None from _gated_execute."""

    async def test_paper_mode_blocks_gated_execute(self) -> None:
        from projects.polymarket.polyquantbot.phase10.pipeline_runner import (
            LatencyEvent,
        )

        runner, executor, *_ = _make_runner(go_live_mode="PAPER")

        request = _FakeExecutionRequest()
        lat = LatencyEvent(
            correlation_id=request.correlation_id,
            market_id=request.market_id,
            data_received_ts=time.time(),
        )
        market_ctx = {"depth": 20_000.0, "spread": 0.02, "mid": 0.62}

        result = await runner._gated_execute(request, market_ctx, lat)

        assert result is None, "PAPER mode must block execution"
        executor.execute.assert_not_called()

    async def test_paper_mode_records_fill_false(self) -> None:
        """PAPER mode should record a non-fill in MetricsValidator."""
        from projects.polymarket.polyquantbot.phase10.pipeline_runner import (
            LatencyEvent,
        )

        runner, *_ = _make_runner(go_live_mode="PAPER")

        request = _FakeExecutionRequest()
        lat = LatencyEvent(
            correlation_id=request.correlation_id,
            market_id=request.market_id,
            data_received_ts=time.time(),
        )
        await runner._gated_execute(request, {"depth": 20_000.0, "spread": 0.01, "mid": 0.62}, lat)

        # MetricsValidator recorded an unfilled order
        assert runner._metrics._orders_submitted == 1
        assert runner._metrics._orders_filled == 0


# ══════════════════════════════════════════════════════════════════════════════
# TR-02 — LIVE mode allows execution when metrics pass
# ══════════════════════════════════════════════════════════════════════════════


class TestLiveModeAllowsExecution:
    """TR-02 — GoLiveController allows execution in LIVE mode with passing metrics."""

    async def test_live_mode_executes_when_metrics_pass(self) -> None:
        from projects.polymarket.polyquantbot.phase10.pipeline_runner import (
            LatencyEvent,
        )

        runner, executor, *_ = _make_runner(
            go_live_mode="LIVE",
            executor_status="submitted",
        )
        runner._go_live.set_metrics(_make_passing_metrics())

        request = _FakeExecutionRequest(size=50.0)
        lat = LatencyEvent(
            correlation_id=request.correlation_id,
            market_id=request.market_id,
            data_received_ts=time.time(),
        )
        market_ctx = {"depth": 20_000.0, "spread": 0.02, "mid": 0.62}

        result = await runner._gated_execute(request, market_ctx, lat)

        assert result is not None, "LIVE mode with passing metrics must execute"
        executor.execute.assert_called_once()

    async def test_live_mode_blocked_without_metrics(self) -> None:
        from projects.polymarket.polyquantbot.phase10.pipeline_runner import (
            LatencyEvent,
        )

        runner, executor, *_ = _make_runner(go_live_mode="LIVE")
        # No metrics set on GoLiveController

        request = _FakeExecutionRequest(size=50.0)
        lat = LatencyEvent(
            correlation_id=request.correlation_id,
            market_id=request.market_id,
            data_received_ts=time.time(),
        )
        result = await runner._gated_execute(
            request, {"depth": 20_000.0, "spread": 0.01, "mid": 0.62}, lat
        )

        assert result is None, "LIVE mode without metrics must be blocked"
        executor.execute.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# TR-03 — ExecutionGuard rejects low-liquidity order in pipeline
# ══════════════════════════════════════════════════════════════════════════════


class TestExecutionGuardLiquidityGate:
    """TR-03 — Pipeline rejects order when depth is below min_liquidity."""

    async def test_low_liquidity_rejected(self) -> None:
        from projects.polymarket.polyquantbot.phase10.pipeline_runner import (
            LatencyEvent,
        )

        runner, executor, *_ = _make_runner(
            go_live_mode="LIVE",
            min_liquidity_usd=10_000.0,
        )
        runner._go_live.set_metrics(_make_passing_metrics())

        request = _FakeExecutionRequest(size=50.0)
        lat = LatencyEvent(
            correlation_id=request.correlation_id,
            market_id=request.market_id,
            data_received_ts=time.time(),
        )
        # depth = 500 < 10,000 threshold
        market_ctx = {"depth": 500.0, "spread": 0.02, "mid": 0.62}

        result = await runner._gated_execute(request, market_ctx, lat)

        assert result is None, "Low liquidity must block execution"
        executor.execute.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# TR-04 — ExecutionGuard rejects over-sized position in pipeline
# ══════════════════════════════════════════════════════════════════════════════


class TestExecutionGuardPositionSizeGate:
    """TR-04 — Pipeline rejects order when size exceeds max_position_usd."""

    async def test_oversized_position_rejected(self) -> None:
        from projects.polymarket.polyquantbot.phase10.pipeline_runner import (
            LatencyEvent,
        )

        runner, executor, *_ = _make_runner(
            go_live_mode="LIVE",
            max_position_usd=100.0,  # max 100 USD
        )
        runner._go_live.set_metrics(_make_passing_metrics())

        request = _FakeExecutionRequest(size=200.0)  # 200 > 100
        lat = LatencyEvent(
            correlation_id=request.correlation_id,
            market_id=request.market_id,
            data_received_ts=time.time(),
        )
        market_ctx = {"depth": 30_000.0, "spread": 0.01, "mid": 0.62}

        result = await runner._gated_execute(request, market_ctx, lat)

        assert result is None, "Over-sized position must be rejected"
        executor.execute.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# TR-05 — Arb signals detected but not executed
# ══════════════════════════════════════════════════════════════════════════════


class TestArbSignalsNotExecuted:
    """TR-05 — Arb poll populates arb_signals_total; executor stays silent."""

    async def test_arb_signal_detected_not_executed(self) -> None:
        kalshi_markets = [
            {
                "ticker": "PRES-REP-2024",
                "title": "republican president 2024",
                "yes_price": 0.72,
                "no_price": 0.28,
                "volume": 50000.0,
                "open_interest": 10000.0,
                "close_time": time.time() + 86400,
                "status": "open",
                "_source": "kalshi",
            }
        ]
        runner, executor, kalshi, *_ = _make_runner(kalshi_markets=kalshi_markets)

        # Prime cache with a Polymarket market at a different price (spread > 4%)
        runner._cache.on_tick("0xabc123", 0.60)

        await runner._run_arb_scan()

        # Executor must never be called
        executor.execute.assert_not_called()

    async def test_arb_counter_increments_on_signal(self) -> None:
        """arb_signals_total increases when spread exceeds threshold."""
        from projects.polymarket.polyquantbot.phase10.arb_detector import ArbDetector
        from projects.polymarket.polyquantbot.phase10.pipeline_runner import (
            Phase10PipelineRunner,
        )

        runner, executor, *_ = _make_runner()
        runner._arb = ArbDetector(
            spread_threshold=0.04,
            market_map={"0xabc123": "PRES-REP-2024"},
        )

        kalshi_markets = [
            {
                "ticker": "PRES-REP-2024",
                "title": "republican president 2024",
                "yes_price": 0.72,
                "_source": "kalshi",
            }
        ]
        runner._kalshi.get_markets = AsyncMock(return_value=kalshi_markets)

        # Prime cache with low poly price → spread = 0.72 - 0.60 = 0.12 > 0.04
        runner._cache.on_tick("0xabc123", 0.60)

        initial = runner._arb_signals_total
        await runner._run_arb_scan()

        assert runner._arb_signals_total > initial, "Arb signal must be detected"
        executor.execute.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# TR-06 — Latency event populated correctly
# ══════════════════════════════════════════════════════════════════════════════


class TestLatencyTracking:
    """TR-06, TR-13 — LatencyEvent fields are set through pipeline execution."""

    async def test_latency_event_total_ms_positive(self) -> None:
        from projects.polymarket.polyquantbot.phase10.pipeline_runner import (
            LatencyEvent,
        )

        runner, *_ = _make_runner(go_live_mode="LIVE")
        runner._go_live.set_metrics(_make_passing_metrics())

        request = _FakeExecutionRequest(size=50.0)
        lat = LatencyEvent(
            correlation_id=request.correlation_id,
            market_id=request.market_id,
            data_received_ts=time.time(),
        )
        market_ctx = {"depth": 20_000.0, "spread": 0.01, "mid": 0.62}

        await runner._gated_execute(request, market_ctx, lat)

        assert lat.order_sent_ts > 0, "order_sent_ts must be set"
        assert lat.fill_received_ts >= lat.order_sent_ts, "fill must come after send"
        assert lat.total_latency_ms > 0, "total_latency_ms must be positive"

    async def test_latency_event_not_set_when_blocked(self) -> None:
        """PAPER mode: order_sent_ts stays 0 (execution never reached)."""
        from projects.polymarket.polyquantbot.phase10.pipeline_runner import (
            LatencyEvent,
        )

        runner, *_ = _make_runner(go_live_mode="PAPER")

        request = _FakeExecutionRequest()
        lat = LatencyEvent(
            correlation_id=request.correlation_id,
            market_id=request.market_id,
            data_received_ts=time.time(),
        )
        await runner._gated_execute(request, {"depth": 20_000.0, "spread": 0.01, "mid": 0.62}, lat)

        assert lat.order_sent_ts == 0.0, "order_sent_ts must stay 0 when blocked"
        assert lat.fill_received_ts == 0.0, "fill_received_ts must stay 0 when blocked"


# ══════════════════════════════════════════════════════════════════════════════
# TR-07, TR-08 — MetricsValidator records fills and latency
# ══════════════════════════════════════════════════════════════════════════════


class TestMetricsRecording:
    """TR-07, TR-08 — MetricsValidator accumulates data through pipeline."""

    async def test_fill_recorded_on_successful_execution(self) -> None:
        from projects.polymarket.polyquantbot.phase10.pipeline_runner import (
            LatencyEvent,
        )

        runner, *_ = _make_runner(go_live_mode="LIVE", executor_status="submitted")
        runner._go_live.set_metrics(_make_passing_metrics())

        for _ in range(3):
            request = _FakeExecutionRequest(size=50.0)
            lat = LatencyEvent(
                correlation_id=request.correlation_id,
                market_id=request.market_id,
                data_received_ts=time.time(),
            )
            await runner._gated_execute(
                request, {"depth": 20_000.0, "spread": 0.01, "mid": 0.62}, lat
            )

        # 3 orders submitted
        assert runner._metrics._orders_submitted == 3

    async def test_latency_recorded_on_execution(self) -> None:
        from projects.polymarket.polyquantbot.phase10.pipeline_runner import (
            LatencyEvent,
        )

        runner, *_ = _make_runner(go_live_mode="LIVE", executor_status="submitted")
        runner._go_live.set_metrics(_make_passing_metrics())

        request = _FakeExecutionRequest(size=50.0)
        lat = LatencyEvent(
            correlation_id=request.correlation_id,
            market_id=request.market_id,
            data_received_ts=time.time(),
        )
        await runner._gated_execute(
            request, {"depth": 20_000.0, "spread": 0.01, "mid": 0.62}, lat
        )

        assert len(runner._metrics._latency_samples_ms) >= 1
        assert runner._metrics._latency_samples_ms[0] > 0


# ══════════════════════════════════════════════════════════════════════════════
# TR-09 — PAPER mode in from_config forces dry_run on LiveExecutor
# ══════════════════════════════════════════════════════════════════════════════


class TestFromConfigPaperMode:
    """TR-09 — from_config with PAPER mode sets dry_run=True on the executor."""

    def test_paper_config_builds_in_paper_mode(self) -> None:
        from projects.polymarket.polyquantbot.phase10.go_live_controller import (
            TradingMode,
        )
        from projects.polymarket.polyquantbot.phase10.pipeline_runner import (
            Phase10PipelineRunner,
        )

        config = {
            "go_live": {"mode": "PAPER"},
            "execution": {"min_order_size": 1.0},
        }

        with patch(
            "projects.polymarket.polyquantbot.phase10.pipeline_runner.PolymarketWSClient"
        ) as mock_ws_cls, patch(
            "projects.polymarket.polyquantbot.phase10.pipeline_runner.LiveExecutor"
        ) as mock_exec_cls:
            mock_ws_cls.return_value = MagicMock()
            mock_exec_cls.return_value = MagicMock()

            runner = Phase10PipelineRunner.from_config(config, market_ids=["0xabc"])

        assert runner.mode is TradingMode.PAPER
        # dry_run=True must have been passed to LiveExecutor
        call_kwargs = mock_exec_cls.call_args.kwargs
        assert call_kwargs.get("dry_run") is True


# ══════════════════════════════════════════════════════════════════════════════
# TR-10 — GoLiveController daily trade counter increments after execution
# ══════════════════════════════════════════════════════════════════════════════


class TestGoLiveCounterUpdates:
    """TR-10 — record_trade() called after successful execution."""

    async def test_trade_counter_increments(self) -> None:
        from projects.polymarket.polyquantbot.phase10.pipeline_runner import (
            LatencyEvent,
        )

        runner, *_ = _make_runner(go_live_mode="LIVE", executor_status="submitted")
        runner._go_live.set_metrics(_make_passing_metrics())

        before = runner._go_live._trades_today

        request = _FakeExecutionRequest(size=50.0)
        lat = LatencyEvent(
            correlation_id=request.correlation_id,
            market_id=request.market_id,
            data_received_ts=time.time(),
        )
        await runner._gated_execute(
            request, {"depth": 20_000.0, "spread": 0.01, "mid": 0.62}, lat
        )

        assert runner._go_live._trades_today == before + 1


# ══════════════════════════════════════════════════════════════════════════════
# TR-11 — Stale market data skips execution
# ══════════════════════════════════════════════════════════════════════════════


class TestStaleDataSkipsExecution:
    """TR-11 — _handle_orderbook_event skips when cache reports stale data."""

    async def test_stale_cache_skips_callback(self) -> None:
        callback = AsyncMock(return_value=None)
        runner, executor, *_ = _make_runner(go_live_mode="PAPER")
        runner._decision_callback = callback

        from projects.polymarket.polyquantbot.phase7.infra.ws_client import WSEvent

        event = WSEvent(
            type="orderbook",
            market_id="0xstale",
            timestamp=time.time(),
            data={"bids": [], "asks": [], "update_type": "snapshot"},
        )

        # No microstructure → cache.is_stale() returns True (never updated)
        # But orderbook snap will be None first (no data) so it returns early
        await runner._handle_orderbook_event(event)

        # Callback must not fire (stale / invalid book)
        callback.assert_not_called()
        executor.execute.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# TR-12 — Arb poll loop handles Kalshi timeout without crash
# ══════════════════════════════════════════════════════════════════════════════


class TestArbPollTimeout:
    """TR-12 — Kalshi timeout during poll is caught; pipeline continues."""

    async def test_kalshi_timeout_no_crash(self) -> None:
        runner, _, kalshi, *_ = _make_runner()

        # Force timeout on the first call
        async def _slow():
            await asyncio.sleep(100)

        kalshi.get_markets = AsyncMock(side_effect=asyncio.TimeoutError)

        # Should complete without raising
        await runner._run_arb_scan()

    async def test_kalshi_error_no_crash(self) -> None:
        runner, _, kalshi, *_ = _make_runner()
        kalshi.get_markets = AsyncMock(side_effect=RuntimeError("network error"))

        # Should complete without raising
        await runner._run_arb_scan()


# ══════════════════════════════════════════════════════════════════════════════
# TR-14 — Pipeline stop() sets _running = False
# ══════════════════════════════════════════════════════════════════════════════


class TestPipelineStop:
    """TR-14 — stop() flag and WS disconnect called."""

    async def test_stop_sets_running_false(self) -> None:
        runner, *_ = _make_runner()
        runner._running = True
        await runner.stop()
        assert runner._running is False

    async def test_stop_calls_ws_disconnect(self) -> None:
        runner, *_ = _make_runner()
        runner._running = True
        await runner.stop()
        runner._ws.disconnect.assert_called_once()


# ══════════════════════════════════════════════════════════════════════════════
# Pipeline GoLiveController status integration
# ══════════════════════════════════════════════════════════════════════════════


class TestGoLiveStatusIntegration:
    """set_metrics_for_go_live() propagates to GoLiveController."""

    def test_set_metrics_for_go_live_enables_live(self) -> None:
        from projects.polymarket.polyquantbot.phase10.go_live_controller import (
            TradingMode,
        )

        runner, *_ = _make_runner(go_live_mode="LIVE")
        assert runner._go_live._metrics_ready is False

        runner.set_metrics_for_go_live(_make_passing_metrics())

        assert runner._go_live._metrics_ready is True

    def test_mode_property_reflects_go_live_controller(self) -> None:
        from projects.polymarket.polyquantbot.phase10.go_live_controller import (
            TradingMode,
        )

        runner, *_ = _make_runner(go_live_mode="PAPER")
        assert runner.mode is TradingMode.PAPER
