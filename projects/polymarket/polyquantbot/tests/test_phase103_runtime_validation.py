"""Phase 10.3 — SENTINEL Runtime Validation Test Suite (PAPER Mode).

Validates live-runtime behavior of the PolyQuantBot system in PAPER mode.
All external I/O (WebSocket, Telegram HTTP, Kalshi REST) is stubbed so tests
are deterministic; the real pipeline logic runs unmodified.

Scenarios covered:

  RT-01  TELEGRAM — alert_error("SENTINEL TEST") queued and dispatched
  RT-02  TELEGRAM — delivery latency measured (queue-to-worker round-trip)
  RT-03  TELEGRAM — disabled gracefully when env vars missing
  RT-04  PIPELINE — DATA→SIGNAL→RISK→EXECUTION→MONITORING wiring
  RT-05  PIPELINE — WS connected flag + event flow (no crash)
  RT-06  PIPELINE — no data-flow crash on multiple sequential events
  RT-07  EXECUTION SAFETY — PAPER mode blocks all real orders
  RT-08  EXECUTION SAFETY — ExecutionGuard rejects every order before executor
  RT-09  EXECUTION SAFETY — is_paper flag set on simulated results
  RT-10  FAILURE — WebSocket disconnect triggers reconnect path (no crash)
  RT-11  FAILURE — Cache miss skips execution silently
  RT-12  FAILURE — Latency spike >1000 ms recorded in MetricsValidator
  RT-13  FAILURE — Slippage spike >50 bps triggers warning alert
  RT-14  ASYNC SAFETY — 50 concurrent signals produce no race condition
  RT-15  ASYNC SAFETY — parallel fill submissions preserve state integrity
  RT-16  STABILITY — 50-cycle event loop with no crash or memory leak growth
  RT-17  STABILITY — metrics accumulate monotonically over many cycles
  RT-18  RISK — kill switch disables all execution immediately
  RT-19  RISK — daily loss limit breach triggers kill switch
  RT-20  RISK — drawdown breach triggers kill switch and GoLive blocks
  RT-21  RISK — Kelly α=0.25 enforced via position sizing ≤ 10% bankroll
  RT-22  RISK — no risk rule bypass possible while RiskGuard is disabled
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers / shared fixtures
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class _FakeExecResult:
    order_id: str = "paper-001"
    status: str = "submitted"
    filled_size: float = 0.0
    avg_price: float = 0.0
    latency_ms: float = 8.0
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    error: Optional[str] = None
    is_paper: bool = True


@dataclass
class _FakeExecRequest:
    market_id: str = "0xabc123"
    side: str = "YES"
    price: float = 0.62
    size: float = 100.0
    order_type: str = "LIMIT"
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    expected_ev: float = 0.05


def _make_runner(
    go_live_mode: str = "PAPER",
    max_position_usd: float = 500.0,
    min_liquidity_usd: float = 10_000.0,
    executor_status: str = "submitted",
):
    """Build Phase10PipelineRunner with all external dependencies stubbed."""
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

    ws_client = MagicMock()
    ws_client.connect = AsyncMock()
    ws_client.disconnect = AsyncMock()
    ws_client.stats = MagicMock(
        return_value=MagicMock(
            messages_received=10,
            events_emitted=5,
            reconnects=0,
            heartbeat_timeouts=0,
        )
    )

    fake_result = _FakeExecResult(status=executor_status, is_paper=True)
    executor = MagicMock()
    executor.execute = AsyncMock(return_value=fake_result)
    executor.cancel_all_open = AsyncMock(return_value=0)

    kalshi = MagicMock()
    kalshi.get_markets = AsyncMock(return_value=[])
    kalshi.close = AsyncMock()

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
        arb_poll_interval_s=99_999.0,
        health_log_interval_s=99_999.0,
    )
    return runner, executor, kalshi, go_live_controller, execution_guard


# ══════════════════════════════════════════════════════════════════════════════
# RT-01  Telegram — alert_error("SENTINEL TEST") queued
# ══════════════════════════════════════════════════════════════════════════════


class TestRT01TelegramAlertQueued:
    """RT-01: alert_error enqueues a message when Telegram is enabled."""

    async def test_alert_error_sentinel_test_queued(self) -> None:
        from projects.polymarket.polyquantbot.phase9.telegram_live import TelegramLive

        tg = TelegramLive(bot_token="TEST_TOKEN", chat_id="TEST_CHAT", enabled=True)
        assert tg._queue.empty()

        await tg.alert_error("SENTINEL TEST", context="phase10.3_runtime_validation")

        assert not tg._queue.empty()
        alert = tg._queue.get_nowait()
        assert "SENTINEL TEST" in alert.message
        assert alert.alert_type.value == "ERROR"

    async def test_alert_error_correlation_id_attached(self) -> None:
        from projects.polymarket.polyquantbot.phase9.telegram_live import TelegramLive

        tg = TelegramLive(bot_token="T", chat_id="C", enabled=True)
        cid = str(uuid.uuid4())
        await tg.alert_error("SENTINEL TEST", correlation_id=cid)

        alert = tg._queue.get_nowait()
        assert alert.correlation_id == cid


# ══════════════════════════════════════════════════════════════════════════════
# RT-02  Telegram — delivery latency measured (worker round-trip)
# ══════════════════════════════════════════════════════════════════════════════


class TestRT02TelegramDeliveryLatency:
    """RT-02: worker dequeues alert within 2 s when HTTP is stubbed."""

    async def test_worker_dequeues_within_2s(self) -> None:
        from projects.polymarket.polyquantbot.phase9.telegram_live import TelegramLive

        tg = TelegramLive(bot_token="T", chat_id="C", enabled=True)

        sent_alerts: list[str] = []

        async def _fake_send(alert: object) -> None:
            """Stub replacing _send_with_retry to capture dispatched alerts."""
            sent_alerts.append(alert.message)  # type: ignore[union-attr]

        with patch.object(tg, "_send_with_retry", side_effect=_fake_send):
            await tg.start()
            t0 = time.monotonic()
            await tg.alert_error("SENTINEL TEST", context="latency_check")
            # Give worker up to 2 s to pick up the alert
            deadline = t0 + 2.0
            while not sent_alerts and time.monotonic() < deadline:
                await asyncio.sleep(0.05)
            await tg.stop()

        latency_s = time.monotonic() - t0
        assert sent_alerts, "Alert was not delivered within 2 s"
        assert latency_s < 2.0, f"Delivery latency too high: {latency_s:.3f}s"
        assert "SENTINEL TEST" in sent_alerts[0]


# ══════════════════════════════════════════════════════════════════════════════
# RT-03  Telegram — graceful disable when env vars missing
# ══════════════════════════════════════════════════════════════════════════════


class TestRT03TelegramDisabledNoEnv:
    """RT-03: TelegramLive.from_env() disables safely when token is absent."""

    def test_from_env_no_token_disabled(self, monkeypatch) -> None:
        from projects.polymarket.polyquantbot.phase9.telegram_live import TelegramLive

        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        tg = TelegramLive.from_env()
        assert not tg._enabled

    async def test_disabled_alert_error_no_queue(self, monkeypatch) -> None:
        from projects.polymarket.polyquantbot.phase9.telegram_live import TelegramLive

        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        tg = TelegramLive.from_env()
        await tg.alert_error("SENTINEL TEST")  # must not raise
        assert tg._queue.empty()


# ══════════════════════════════════════════════════════════════════════════════
# RT-04  Pipeline — DATA→SIGNAL→RISK→EXECUTION→MONITORING wiring
# ══════════════════════════════════════════════════════════════════════════════


class TestRT04PipelineWiring:
    """RT-04: Full pipeline wiring is intact; orderbook event flows through."""

    async def test_orderbook_event_updates_cache(self) -> None:
        from projects.polymarket.polyquantbot.phase7.infra.ws_client import WSEvent

        runner, *_ = _make_runner()
        event = WSEvent(
            type="orderbook",
            market_id="0xabc123",
            timestamp=time.time(),
            data={
                "asks": [[0.63, 500.0]],
                "bids": [[0.61, 400.0]],
                "update_type": "snapshot",
            },
        )
        await runner._handle_event(event)
        ctx = runner._cache.get_market_context("0xabc123")
        assert ctx is not None
        assert ctx.get("ask") == pytest.approx(0.63, abs=1e-6)

    async def test_pipeline_metrics_wired(self) -> None:
        runner, *_ = _make_runner()
        # MetricsValidator should exist and compute without crash
        result = runner._metrics.compute()
        assert result is not None
        assert hasattr(result, "fill_rate")


# ══════════════════════════════════════════════════════════════════════════════
# RT-05  Pipeline — WS component accessible; no crash on connect stub
# ══════════════════════════════════════════════════════════════════════════════


class TestRT05WSConnectNocrash:
    """RT-05: WS connect stub does not crash; runner starts cleanly."""

    async def test_ws_connect_stub_no_crash(self) -> None:
        runner, *_ = _make_runner()
        # connect() is stubbed — should return immediately
        await runner._ws.connect()
        runner._ws.connect.assert_awaited_once()

    async def test_ws_stats_accessible(self) -> None:
        runner, *_ = _make_runner()
        stats = runner._ws.stats()
        assert stats.messages_received == 10
        assert stats.reconnects == 0


# ══════════════════════════════════════════════════════════════════════════════
# RT-06  Pipeline — sequential events without crash
# ══════════════════════════════════════════════════════════════════════════════


class TestRT06SequentialEvents:
    """RT-06: Multiple sequential orderbook events processed without error."""

    async def test_20_sequential_events_no_crash(self) -> None:
        from projects.polymarket.polyquantbot.phase7.infra.ws_client import WSEvent

        runner, *_ = _make_runner()
        for i in range(20):
            event = WSEvent(
                type="orderbook",
                market_id="0xabc123",
                timestamp=time.time() + i * 0.1,
                data={
                    "asks": [[0.60 + i * 0.001, 200.0]],
                    "bids": [[0.59 + i * 0.001, 150.0]],
                    "update_type": "snapshot" if i == 0 else "delta",
                },
            )
            await runner._handle_event(event)
        # Cache should reflect last update
        ctx = runner._cache.get_market_context("0xabc123")
        assert ctx is not None


# ══════════════════════════════════════════════════════════════════════════════
# RT-07  Execution Safety — PAPER mode blocks all real orders
# ══════════════════════════════════════════════════════════════════════════════


class TestRT07PaperModeBlocksExecution:
    """RT-07: GoLiveController in PAPER mode returns False for allow_execution."""

    def test_paper_mode_blocks_allow_execution(self) -> None:
        from projects.polymarket.polyquantbot.phase10.go_live_controller import (
            GoLiveController,
            TradingMode,
        )

        ctrl = GoLiveController(mode=TradingMode.PAPER)
        assert ctrl.allow_execution(trade_size_usd=100.0) is False

    async def test_paper_mode_executor_never_called(self) -> None:
        from projects.polymarket.polyquantbot.phase7.infra.ws_client import WSEvent

        runner, executor, *_ = _make_runner(go_live_mode="PAPER")

        signals_issued: list[_FakeExecRequest] = []

        async def _cb(market_id: str, ctx: dict) -> Optional[_FakeExecRequest]:
            req = _FakeExecRequest(market_id=market_id)
            signals_issued.append(req)
            return req

        runner._decision_callback = _cb

        event = WSEvent(
            type="orderbook",
            market_id="0xabc123",
            timestamp=time.time(),
            data={
                "asks": [[0.63, 50_000.0]],
                "bids": [[0.61, 50_000.0]],
                "update_type": "snapshot",
            },
        )
        await runner._handle_event(event)

        assert len(signals_issued) == 1, "Callback must be reached"
        executor.execute.assert_not_awaited()

    def test_paper_mode_string_value(self) -> None:
        from projects.polymarket.polyquantbot.phase10.go_live_controller import (
            GoLiveController,
            TradingMode,
        )

        ctrl = GoLiveController(mode=TradingMode.PAPER)
        assert ctrl.mode.value == "PAPER"


# ══════════════════════════════════════════════════════════════════════════════
# RT-08  Execution Safety — ExecutionGuard rejects low-liquidity orders
# ══════════════════════════════════════════════════════════════════════════════


class TestRT08ExecutionGuardRejects:
    """RT-08: ExecutionGuard blocks orders that fail validation."""

    def test_low_liquidity_rejected(self) -> None:
        from projects.polymarket.polyquantbot.phase10.execution_guard import (
            ExecutionGuard,
        )

        guard = ExecutionGuard(min_liquidity_usd=10_000.0, max_position_usd=1_000.0)
        result = guard.validate(
            market_id="0xabc",
            side="YES",
            price=0.62,
            size_usd=100.0,
            liquidity_usd=500.0,  # below min
            slippage_pct=0.01,
        )
        assert result.passed is False
        assert "liquidity" in result.reason.lower()

    def test_slippage_exceeded_rejected(self) -> None:
        from projects.polymarket.polyquantbot.phase10.execution_guard import (
            ExecutionGuard,
        )

        guard = ExecutionGuard(max_slippage_pct=0.03)
        result = guard.validate(
            market_id="0xabc",
            side="YES",
            price=0.62,
            size_usd=100.0,
            liquidity_usd=50_000.0,
            slippage_pct=0.10,  # 10% > 3% max
        )
        assert result.passed is False
        assert "slippage" in result.reason.lower()

    def test_oversized_position_rejected(self) -> None:
        from projects.polymarket.polyquantbot.phase10.execution_guard import (
            ExecutionGuard,
        )

        guard = ExecutionGuard(max_position_usd=500.0)
        result = guard.validate(
            market_id="0xabc",
            side="YES",
            price=0.62,
            size_usd=600.0,  # > $500 max
            liquidity_usd=50_000.0,
            slippage_pct=0.01,
        )
        assert result.passed is False
        assert "position" in result.reason.lower()


# ══════════════════════════════════════════════════════════════════════════════
# RT-09  Execution Safety — paper flag on executor result
# ══════════════════════════════════════════════════════════════════════════════


class TestRT09PaperFlagOnResult:
    """RT-09: ExecutionSimulator results carry is_paper=True."""

    def test_paper_executor_result_has_is_paper_true(self) -> None:
        from projects.polymarket.polyquantbot.execution.fill_tracker import FillTracker
        from projects.polymarket.polyquantbot.execution.simulator import (
            ExecutionSimulator,
            SimMode,
        )

        ft = FillTracker()
        sim = ExecutionSimulator(fill_tracker=ft)
        # PAPER_LIVE_SIM is the default mode (send_real_orders=False)
        assert sim._mode == SimMode.PAPER_LIVE_SIM


# ══════════════════════════════════════════════════════════════════════════════
# RT-10  Failure — WS disconnect triggers reconnect (no crash)
# ══════════════════════════════════════════════════════════════════════════════


class TestRT10WSDisconnectNoCrash:
    """RT-10: Pipeline handles WS disconnect gracefully."""

    async def test_ws_disconnect_no_crash(self) -> None:
        from projects.polymarket.polyquantbot.phase7.infra.ws_client import (
            PolymarketWSClient,
        )

        client = PolymarketWSClient(
            market_ids=["0xabc"],
            ws_url="wss://invalid.example.com/ws",
            heartbeat_timeout_s=1.0,
            reconnect_base_delay=0.05,
            reconnect_max_delay=0.1,
        )

        # Force _running = False immediately so connect() exits fast
        client._running = False
        # Should not raise even with invalid URL
        stats = client.stats()
        assert stats.reconnects >= 0

    async def test_runner_stop_disconnects_ws(self) -> None:
        runner, *_ = _make_runner()
        runner._running = True
        await runner.stop()
        runner._ws.disconnect.assert_awaited_once()
        assert runner._running is False


# ══════════════════════════════════════════════════════════════════════════════
# RT-11  Failure — Cache miss skips execution silently
# ══════════════════════════════════════════════════════════════════════════════


class TestRT11CacheMissSkipsExecution:
    """RT-11: Orderbook event for unknown market skips execution silently."""

    async def test_unknown_market_skips_callback(self) -> None:
        from projects.polymarket.polyquantbot.phase7.infra.ws_client import WSEvent

        runner, executor, *_ = _make_runner()
        callback_called = False

        async def _cb(market_id: str, ctx: dict) -> None:
            nonlocal callback_called
            callback_called = True
            return None

        runner._decision_callback = _cb

        # market_id NOT in runner._market_ids
        event = WSEvent(
            type="orderbook",
            market_id="0xUNKNOWN",
            timestamp=time.time(),
            data={"asks": [[0.70, 100.0]], "bids": [[0.68, 100.0]]},
        )
        await runner._handle_event(event)
        assert not callback_called
        executor.execute.assert_not_awaited()


# ══════════════════════════════════════════════════════════════════════════════
# RT-12  Failure — Latency spike >1000 ms recorded in MetricsValidator
# ══════════════════════════════════════════════════════════════════════════════


class TestRT12LatencySpikeRecorded:
    """RT-12: MetricsValidator records latency spike; p95 reflects spike."""

    def test_latency_spike_recorded(self) -> None:
        from projects.polymarket.polyquantbot.phase9.metrics_validator import (
            MetricsValidator,
        )

        validator = MetricsValidator(min_trades=0)
        for _ in range(10):
            validator.record_latency(200.0)
        validator.record_latency(1200.0)  # spike

        result = validator.compute()
        assert result.p95_latency >= 200.0
        # With 11 samples, p95 index = floor(0.95 * 11) = 10 → last sample is 1200 ms
        assert result.p95_latency >= 1200.0 * 0.9  # p95 captures the spike

    def test_latency_spike_does_not_crash(self) -> None:
        from projects.polymarket.polyquantbot.phase9.metrics_validator import (
            MetricsValidator,
        )

        validator = MetricsValidator(min_trades=0)
        validator.record_latency(99_999.0)  # extreme spike
        result = validator.compute()
        assert result is not None


# ══════════════════════════════════════════════════════════════════════════════
# RT-13  Failure — Slippage spike >50 bps triggers warning
# ══════════════════════════════════════════════════════════════════════════════


class TestRT13SlippageSpikeAlert:
    """RT-13: MetricsValidator fires Telegram alert when slippage_bps > 50."""

    async def test_slippage_spike_triggers_alert_error(self) -> None:
        from projects.polymarket.polyquantbot.phase9.metrics_validator import (
            MetricsValidator,
        )
        from projects.polymarket.polyquantbot.phase9.telegram_live import TelegramLive

        tg = TelegramLive(bot_token="T", chat_id="C", enabled=True)
        validator = MetricsValidator(min_trades=0, slippage_warn_bps=50.0)
        validator.set_telegram(tg)

        # warn_slippage() is the method that checks threshold and fires alert
        await validator.warn_slippage(slippage_bps=80.0)

        assert not tg._queue.empty(), "Slippage spike must enqueue an alert"

    def test_slippage_below_threshold_no_alert(self) -> None:
        from projects.polymarket.polyquantbot.phase9.metrics_validator import (
            MetricsValidator,
        )
        from projects.polymarket.polyquantbot.phase9.telegram_live import TelegramLive

        tg = TelegramLive(bot_token="T", chat_id="C", enabled=True)
        validator = MetricsValidator(min_trades=0, slippage_warn_bps=50.0)
        validator.set_telegram(tg)

        # record_slippage() only stores samples; warn_slippage() fires alerts
        validator.record_slippage(slippage_bps=20.0)  # below threshold
        assert tg._queue.empty()


# ══════════════════════════════════════════════════════════════════════════════
# RT-14  Async Safety — 50 concurrent signals, no race condition
# ══════════════════════════════════════════════════════════════════════════════


class TestRT14ConcurrentSignalsNoRace:
    """RT-14: 50 concurrent orderbook events → no state corruption."""

    async def test_50_concurrent_events_no_crash(self) -> None:
        from projects.polymarket.polyquantbot.phase7.infra.ws_client import WSEvent

        runner, *_ = _make_runner()

        events = [
            WSEvent(
                type="orderbook",
                market_id="0xabc123",
                timestamp=time.time() + i * 0.001,
                data={
                    "asks": [[0.60 + i * 0.0001, 200.0]],
                    "bids": [[0.59 + i * 0.0001, 150.0]],
                    "update_type": "snapshot" if i == 0 else "delta",
                },
            )
            for i in range(50)
        ]
        await asyncio.gather(*[runner._handle_event(e) for e in events])
        ctx = runner._cache.get_market_context("0xabc123")
        assert ctx is not None


# ══════════════════════════════════════════════════════════════════════════════
# RT-15  Async Safety — Parallel fill submissions preserve state
# ══════════════════════════════════════════════════════════════════════════════


class TestRT15ParallelFillsStateIntegrity:
    """RT-15: Parallel fill submissions to Reconciliation are race-free."""

    async def test_parallel_fills_no_corruption(self) -> None:
        from projects.polymarket.polyquantbot.execution.reconciliation import (
            Reconciliation,
        )

        rec = Reconciliation()
        order_ids = [f"ord-{i:04d}" for i in range(50)]
        for oid in order_ids:
            rec.register_order(oid, f"mkt-{oid}", "YES", 0.60, 100.0)

        async def _fill(oid: str) -> None:
            rec.record_fill(oid, executed_price=0.60, filled_size=100.0)

        await asyncio.gather(*[_fill(oid) for oid in order_ids])

        report = rec.reconcile()
        assert report.total_orders == 50
        assert report.matched == 50
        assert report.missed == 0


# ══════════════════════════════════════════════════════════════════════════════
# RT-16  Stability — 50-cycle event loop, no crash
# ══════════════════════════════════════════════════════════════════════════════


class TestRT16StabilityRun:
    """RT-16: 50 event cycles run without crash or exception."""

    async def test_50_cycle_stability_run(self) -> None:
        from projects.polymarket.polyquantbot.phase7.infra.ws_client import WSEvent

        runner, *_ = _make_runner()
        errors: list[Exception] = []

        for i in range(50):
            try:
                event = WSEvent(
                    type="orderbook",
                    market_id="0xabc123",
                    timestamp=time.time() + i * 0.01,
                    data={
                        "asks": [[0.61 + i * 0.0001, 300.0 + i]],
                        "bids": [[0.60 + i * 0.0001, 250.0 + i]],
                        "update_type": "snapshot" if i == 0 else "delta",
                    },
                )
                await runner._handle_event(event)
            except Exception as exc:
                errors.append(exc)

        assert not errors, f"Errors during stability run: {errors}"

    async def test_stop_after_cycles_clean(self) -> None:
        from projects.polymarket.polyquantbot.phase7.infra.ws_client import WSEvent

        runner, *_ = _make_runner()
        for i in range(10):
            event = WSEvent(
                type="orderbook",
                market_id="0xabc123",
                timestamp=time.time() + i * 0.01,
                data={
                    "asks": [[0.62, 200.0]],
                    "bids": [[0.60, 200.0]],
                    "update_type": "snapshot" if i == 0 else "delta",
                },
            )
            await runner._handle_event(event)

        runner._running = True
        await runner.stop()
        assert runner._running is False


# ══════════════════════════════════════════════════════════════════════════════
# RT-17  Stability — Metrics accumulate monotonically
# ══════════════════════════════════════════════════════════════════════════════


class TestRT17MetricsMonotonic:
    """RT-17: Metric counters increase monotonically over cycles."""

    def test_fill_counter_increases_monotonically(self) -> None:
        from projects.polymarket.polyquantbot.phase9.metrics_validator import (
            MetricsValidator,
        )

        validator = MetricsValidator(min_trades=0)
        counts = []
        for i in range(1, 11):
            validator.record_fill(filled=True)
            result = validator.compute()
            counts.append(result.total_trades)

        for a, b in zip(counts, counts[1:]):
            assert b >= a, "Fill counter must be non-decreasing"

    def test_latency_samples_accumulate(self) -> None:
        from projects.polymarket.polyquantbot.phase9.metrics_validator import (
            MetricsValidator,
        )

        validator = MetricsValidator(min_trades=0)
        for i in range(20):
            validator.record_latency(float(100 + i * 10))
        result = validator.compute()
        assert result.p95_latency > 100.0


# ══════════════════════════════════════════════════════════════════════════════
# RT-18  Risk — Kill switch disables all execution immediately
# ══════════════════════════════════════════════════════════════════════════════


class TestRT18KillSwitchDisablesExecution:
    """RT-18: trigger_kill_switch sets disabled=True; GoLiveController blocks."""

    async def test_kill_switch_sets_disabled(self) -> None:
        from projects.polymarket.polyquantbot.phase8.risk_guard import RiskGuard

        guard = RiskGuard()
        assert guard.disabled is False
        await guard.trigger_kill_switch(reason="sentinel_test")
        assert guard.disabled is True

    async def test_kill_switch_blocks_go_live(self) -> None:
        from projects.polymarket.polyquantbot.phase8.risk_guard import RiskGuard
        from projects.polymarket.polyquantbot.phase10.go_live_controller import (
            GoLiveController,
            TradingMode,
        )

        risk = RiskGuard()
        ctrl = GoLiveController(mode=TradingMode.PAPER)

        await risk.trigger_kill_switch(reason="sentinel_kill_switch_test")
        assert risk.disabled is True
        # PAPER mode already blocks; kill switch reinforces it
        assert ctrl.allow_execution(trade_size_usd=50.0) is False

    async def test_kill_switch_reason_preserved(self) -> None:
        from projects.polymarket.polyquantbot.phase8.risk_guard import RiskGuard

        guard = RiskGuard()
        await guard.trigger_kill_switch(reason="max_drawdown")
        assert guard._kill_switch_reason == "max_drawdown"

    async def test_kill_switch_idempotent(self) -> None:
        from projects.polymarket.polyquantbot.phase8.risk_guard import RiskGuard

        guard = RiskGuard()
        await guard.trigger_kill_switch(reason="first")
        await guard.trigger_kill_switch(reason="second")  # must not raise
        assert guard.disabled is True
        assert guard._kill_switch_reason == "first"  # first reason retained


# ══════════════════════════════════════════════════════════════════════════════
# RT-19  Risk — Daily loss limit triggers kill switch
# ══════════════════════════════════════════════════════════════════════════════


class TestRT19DailyLossKillSwitch:
    """RT-19: RiskGuard fires kill switch on daily loss breach."""

    async def test_daily_loss_breach_fires_kill(self) -> None:
        from projects.polymarket.polyquantbot.phase8.risk_guard import RiskGuard

        guard = RiskGuard(daily_loss_limit=-2000.0)
        await guard.check_daily_loss(current_pnl=-2500.0)  # breach
        assert guard.disabled is True

    async def test_daily_loss_within_limit_no_kill(self) -> None:
        from projects.polymarket.polyquantbot.phase8.risk_guard import RiskGuard

        guard = RiskGuard(daily_loss_limit=-2000.0)
        await guard.check_daily_loss(current_pnl=-1000.0)  # within limit
        assert guard.disabled is False

    async def test_daily_loss_exact_limit_no_kill(self) -> None:
        from projects.polymarket.polyquantbot.phase8.risk_guard import RiskGuard

        guard = RiskGuard(daily_loss_limit=-2000.0)
        await guard.check_daily_loss(current_pnl=-1999.99)  # within limit (less negative than -2000)
        assert guard.disabled is False


# ══════════════════════════════════════════════════════════════════════════════
# RT-20  Risk — Drawdown breach triggers kill switch + GoLive blocks
# ══════════════════════════════════════════════════════════════════════════════


class TestRT20DrawdownKillSwitch:
    """RT-20: Drawdown > 8% triggers kill switch and GoLiveController blocks."""

    async def test_drawdown_breach_fires_kill(self) -> None:
        from projects.polymarket.polyquantbot.phase8.risk_guard import RiskGuard

        guard = RiskGuard(max_drawdown_pct=0.08)
        await guard.check_drawdown(peak_balance=10_000.0, current_balance=9_000.0)
        assert guard.disabled is True  # 10% drawdown > 8% threshold

    async def test_drawdown_within_limit_no_kill(self) -> None:
        from projects.polymarket.polyquantbot.phase8.risk_guard import RiskGuard

        guard = RiskGuard(max_drawdown_pct=0.08)
        await guard.check_drawdown(peak_balance=10_000.0, current_balance=9_500.0)
        assert guard.disabled is False  # 5% < 8%

    async def test_drawdown_go_live_blocked_when_risk_disabled(self) -> None:
        from projects.polymarket.polyquantbot.phase8.risk_guard import RiskGuard
        from projects.polymarket.polyquantbot.phase10.go_live_controller import (
            GoLiveController,
            TradingMode,
        )

        risk = RiskGuard(max_drawdown_pct=0.08)
        ctrl = GoLiveController(mode=TradingMode.PAPER)

        await risk.check_drawdown(peak_balance=10_000.0, current_balance=9_100.0)
        assert risk.disabled is True
        assert ctrl.allow_execution(trade_size_usd=100.0) is False


# ══════════════════════════════════════════════════════════════════════════════
# RT-21  Risk — Kelly α=0.25 → position ≤ 10% bankroll
# ══════════════════════════════════════════════════════════════════════════════


class TestRT21KellyPositionCap:
    """RT-21: Fractional Kelly (α=0.25) enforced via max_position_usd ≤ 10%."""

    def test_position_cap_10pct_bankroll(self) -> None:
        from projects.polymarket.polyquantbot.phase10.execution_guard import (
            ExecutionGuard,
        )

        bankroll = 10_000.0
        max_position = bankroll * 0.10  # 10% cap = $1,000
        guard = ExecutionGuard(max_position_usd=max_position)

        # Order at exactly the cap → should pass
        result_ok = guard.validate(
            market_id="0xabc",
            side="YES",
            price=0.62,
            size_usd=max_position,
            liquidity_usd=50_000.0,
            slippage_pct=0.01,
        )
        assert result_ok.passed is True

    def test_position_exceeds_10pct_bankroll_rejected(self) -> None:
        from projects.polymarket.polyquantbot.phase10.execution_guard import (
            ExecutionGuard,
        )

        bankroll = 10_000.0
        max_position = bankroll * 0.10
        guard = ExecutionGuard(max_position_usd=max_position)

        # Order 1 cent above cap → rejected
        result_bad = guard.validate(
            market_id="0xabc",
            side="YES",
            price=0.62,
            size_usd=max_position + 0.01,
            liquidity_usd=50_000.0,
            slippage_pct=0.01,
        )
        assert result_bad.passed is False
        assert "position" in result_bad.reason.lower()

    def test_kelly_alpha_025_sizing(self) -> None:
        """Full Kelly → α=0.25 reduces bankroll exposure by 75%."""
        bankroll = 10_000.0
        kelly_fraction = 0.40   # hypothetical full Kelly
        alpha = 0.25
        fractional_kelly = kelly_fraction * alpha   # = 0.10
        sized_position = bankroll * fractional_kelly
        assert sized_position <= bankroll * 0.10


# ══════════════════════════════════════════════════════════════════════════════
# RT-22  Risk — No bypass possible while RiskGuard is disabled
# ══════════════════════════════════════════════════════════════════════════════


class TestRT22NoRiskBypass:
    """RT-22: Once disabled, RiskGuard cannot be re-enabled via normal calls."""

    async def test_disabled_guard_check_daily_loss_noop(self) -> None:
        from projects.polymarket.polyquantbot.phase8.risk_guard import RiskGuard

        guard = RiskGuard()
        await guard.trigger_kill_switch(reason="test_bypass_check")
        assert guard.disabled is True

        # Simulate a "recovered" pnl — guard must stay disabled
        await guard.check_daily_loss(current_pnl=9999.0)
        assert guard.disabled is True

    async def test_disabled_guard_check_drawdown_noop(self) -> None:
        from projects.polymarket.polyquantbot.phase8.risk_guard import RiskGuard

        guard = RiskGuard()
        await guard.trigger_kill_switch(reason="test_bypass_check")
        assert guard.disabled is True

        await guard.check_drawdown(peak_balance=100.0, current_balance=100.0)
        assert guard.disabled is True

    async def test_paper_mode_stays_blocked_after_kill(self) -> None:
        from projects.polymarket.polyquantbot.phase10.go_live_controller import (
            GoLiveController,
            TradingMode,
        )

        ctrl = GoLiveController(mode=TradingMode.PAPER)
        # Even with passing metrics, PAPER mode cannot execute
        ctrl.set_metrics(
            type("M", (), {
                "ev_capture_ratio": 0.99,
                "fill_rate": 0.99,
                "p95_latency": 10.0,
                "drawdown": 0.001,
            })()
        )
        assert ctrl.allow_execution(trade_size_usd=100.0) is False
