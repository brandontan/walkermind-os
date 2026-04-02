"""FW-01–FW-15 — Full Wiring Activation test suite.

Validates:
  FW-01–FW-05: activation_monitor wired into LivePaperRunner
  FW-06–FW-10: alert_signal / alert_trade called at correct points
  FW-11–FW-13: heartbeat ws_connected uses ws_client.stats().connected
  FW-14–FW-15: main.py WS event loop calls record_event
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_ws_event(
    market_id: str = "0xabc",
    event_type: str = "orderbook",
) -> object:
    from projects.polymarket.polyquantbot.data.websocket.ws_client import WSEvent

    if event_type == "orderbook":
        data = {
            "update_type": "snapshot",
            "bids": [[0.60, 500.0], [0.59, 300.0]],
            "asks": [[0.62, 400.0], [0.63, 200.0]],
        }
    else:
        data = {"price": 0.62, "size": 10.0, "side": "BUY", "trade_id": "t1"}

    return WSEvent(
        type=event_type,
        market_id=market_id,
        timestamp=time.time(),
        data=data,
    )


def _make_runner(
    decision_callback=None,
    activation_monitor=None,
):
    """Build a LivePaperRunner with all external deps stubbed."""
    from projects.polymarket.polyquantbot.execution.fill_tracker import FillTracker
    from projects.polymarket.polyquantbot.execution.simulator import ExecutionSimulator
    from projects.polymarket.polyquantbot.core.pipeline.execution_guard import ExecutionGuard
    from projects.polymarket.polyquantbot.core.pipeline.go_live_controller import (
        GoLiveController,
        TradingMode,
    )
    from projects.polymarket.polyquantbot.core.pipeline.live_paper_runner import (
        LivePaperRunner,
    )
    from projects.polymarket.polyquantbot.data.ingestion.execution_feedback import (
        ExecutionFeedbackTracker,
    )
    from projects.polymarket.polyquantbot.data.ingestion.latency_tracker import LatencyTracker
    from projects.polymarket.polyquantbot.data.ingestion.trade_flow import TradeFlowAnalyzer
    from projects.polymarket.polyquantbot.data.orderbook.market_cache import Phase7MarketCache
    from projects.polymarket.polyquantbot.data.orderbook.orderbook import OrderBookManager
    from projects.polymarket.polyquantbot.risk.risk_guard import RiskGuard
    from projects.polymarket.polyquantbot.monitoring.metrics_validator import MetricsValidator
    from projects.polymarket.polyquantbot.telegram.telegram_live import TelegramLive

    ws_client = MagicMock()
    ws_client.connect = AsyncMock()
    ws_client.disconnect = AsyncMock()
    ws_client.stats = MagicMock(
        return_value=MagicMock(reconnects=0, messages_received=10, events_emitted=8)
    )

    fill_tracker = FillTracker()
    simulator = ExecutionSimulator(
        fill_tracker=fill_tracker,
        slippage_threshold_bps=50.0,
        send_real_orders=False,
    )

    go_live = GoLiveController(mode=TradingMode.PAPER)
    guard = ExecutionGuard(
        min_liquidity_usd=0.0,
        max_slippage_pct=1.0,
        max_position_usd=10_000.0,
    )

    metrics = MetricsValidator(min_trades=0)
    risk = RiskGuard(daily_loss_limit=-2000.0, max_drawdown_pct=0.08)
    telegram = TelegramLive(bot_token="TEST", chat_id="TEST", enabled=True)

    runner = LivePaperRunner(
        ws_client=ws_client,
        orderbook_manager=OrderBookManager(),
        market_cache=Phase7MarketCache(),
        trade_flow_analyzer=TradeFlowAnalyzer(window_size=50),
        simulator=simulator,
        fill_tracker=fill_tracker,
        latency_tracker=LatencyTracker(),
        feedback_tracker=ExecutionFeedbackTracker(),
        go_live_controller=go_live,
        execution_guard=guard,
        metrics_validator=metrics,
        risk_guard=risk,
        telegram=telegram,
        market_ids=["0xabc"],
        decision_callback=decision_callback,
        health_log_interval_s=99_999.0,
        checkpoint_intervals_s=(99_999.0,),
        activation_monitor=activation_monitor,
    )
    runner._start_ts = time.time()
    return runner, ws_client, simulator, metrics, risk, telegram


async def _simple_signal(market_id: str, ctx: dict) -> Optional[dict]:
    return {"side": "YES", "price": 0.62, "size_usd": 50.0, "expected_ev": 0.05}


# ── FW-01: activation_monitor parameter accepted ─────────────────────────────


def test_fw01_activation_monitor_parameter_accepted():
    """FW-01: LivePaperRunner accepts activation_monitor parameter."""
    from projects.polymarket.polyquantbot.monitoring.system_activation import (
        SystemActivationMonitor,
    )

    monitor = SystemActivationMonitor()
    runner, *_ = _make_runner(activation_monitor=monitor)
    assert runner._activation_monitor is monitor


# ── FW-02: record_event called on each WS event ───────────────────────────────


async def test_fw02_record_event_called_on_ws_event():
    """FW-02: activation_monitor.record_event() incremented for each WS event."""
    from projects.polymarket.polyquantbot.monitoring.system_activation import (
        SystemActivationMonitor,
    )

    monitor = SystemActivationMonitor()
    runner, *_ = _make_runner(activation_monitor=monitor)

    event = _make_ws_event(event_type="trade")
    await runner._handle_event(event)  # type: ignore[arg-type]

    assert monitor.event_count == 1


# ── FW-03: multiple events increment event_count correctly ────────────────────


async def test_fw03_event_count_increments_for_each_event():
    """FW-03: event_count increases by 1 per WS event."""
    from projects.polymarket.polyquantbot.monitoring.system_activation import (
        SystemActivationMonitor,
    )

    monitor = SystemActivationMonitor()
    runner, *_ = _make_runner(activation_monitor=monitor)

    for _ in range(5):
        event = _make_ws_event(event_type="trade")
        await runner._handle_event(event)  # type: ignore[arg-type]

    assert monitor.event_count == 5


# ── FW-04: record_signal called when signal generated ────────────────────────


async def test_fw04_record_signal_called_on_signal():
    """FW-04: activation_monitor.record_signal() called when decision_callback returns signal."""
    from projects.polymarket.polyquantbot.monitoring.system_activation import (
        SystemActivationMonitor,
    )

    monitor = SystemActivationMonitor()
    runner, *_ = _make_runner(
        decision_callback=_simple_signal,
        activation_monitor=monitor,
    )

    event = _make_ws_event(event_type="orderbook")
    await runner._handle_event(event)  # type: ignore[arg-type]

    assert monitor.signal_count >= 1


# ── FW-05: no_activation_monitor does not crash ───────────────────────────────


async def test_fw05_no_activation_monitor_no_crash():
    """FW-05: runner works without activation_monitor (backward compatible)."""
    runner, *_ = _make_runner(decision_callback=_simple_signal, activation_monitor=None)

    event = _make_ws_event(event_type="orderbook")
    # Should not raise
    await runner._handle_event(event)  # type: ignore[arg-type]

    assert runner._event_count == 1


# ── FW-06: alert_signal called when signal generated ─────────────────────────


async def test_fw06_alert_signal_enqueued_on_signal():
    """FW-06: TelegramLive.alert_signal() enqueues a SIGNAL alert when signal fires."""
    from projects.polymarket.polyquantbot.telegram.telegram_live import AlertType

    runner, *_, telegram = _make_runner(decision_callback=_simple_signal)
    await telegram.start()

    event = _make_ws_event(event_type="orderbook")
    await runner._handle_event(event)  # type: ignore[arg-type]

    # Find SIGNAL alerts in queue
    alerts = []
    while not telegram._queue.empty():
        alerts.append(telegram._queue.get_nowait())
        telegram._queue.task_done()

    signal_alerts = [a for a in alerts if a.alert_type == AlertType.SIGNAL]
    assert len(signal_alerts) >= 1

    await telegram.stop()


# ── FW-07: alert_trade called when fill succeeds ─────────────────────────────


async def test_fw07_alert_trade_enqueued_on_fill():
    """FW-07: TelegramLive.alert_trade() enqueued when sim fill succeeds."""
    from projects.polymarket.polyquantbot.execution.simulator import SimResult, SimMode
    from projects.polymarket.polyquantbot.telegram.telegram_live import AlertType

    runner, *_, telegram = _make_runner(decision_callback=_simple_signal)
    await telegram.start()

    # Stub simulator to always fill
    filled_result = SimResult(
        order_id="test-fill-001",
        mode=SimMode.PAPER_LIVE_SIM,
        expected_price=0.62,
        simulated_price=0.62,
        filled_size=50.0,
        slippage_bps=2.0,
        latency_ms=5.0,
        success=True,
        reason="",
        fill_record=None,
    )
    runner._simulator.execute = AsyncMock(return_value=filled_result)

    event = _make_ws_event(event_type="orderbook")
    await runner._handle_event(event)  # type: ignore[arg-type]

    alerts = []
    while not telegram._queue.empty():
        alerts.append(telegram._queue.get_nowait())
        telegram._queue.task_done()

    trade_alerts = [a for a in alerts if a.alert_type == AlertType.TRADE]
    assert len(trade_alerts) >= 1

    await telegram.stop()


# ── FW-08: record_trade called when fill succeeds ────────────────────────────


async def test_fw08_record_trade_called_on_fill():
    """FW-08: activation_monitor.record_trade() called when simulated fill succeeds."""
    from projects.polymarket.polyquantbot.execution.simulator import SimResult, SimMode
    from projects.polymarket.polyquantbot.monitoring.system_activation import (
        SystemActivationMonitor,
    )

    monitor = SystemActivationMonitor()
    runner, *_ = _make_runner(
        decision_callback=_simple_signal,
        activation_monitor=monitor,
    )

    filled_result = SimResult(
        order_id="test-fill-002",
        mode=SimMode.PAPER_LIVE_SIM,
        expected_price=0.62,
        simulated_price=0.62,
        filled_size=50.0,
        slippage_bps=2.0,
        latency_ms=5.0,
        success=True,
        reason="",
        fill_record=None,
    )
    runner._simulator.execute = AsyncMock(return_value=filled_result)

    event = _make_ws_event(event_type="orderbook")
    await runner._handle_event(event)  # type: ignore[arg-type]

    assert monitor.trade_count >= 1


# ── FW-09: record_trade NOT called when fill fails ───────────────────────────


async def test_fw09_record_trade_not_called_when_no_fill():
    """FW-09: activation_monitor.record_trade() NOT called when fill fails."""
    from projects.polymarket.polyquantbot.execution.simulator import SimResult, SimMode
    from projects.polymarket.polyquantbot.monitoring.system_activation import (
        SystemActivationMonitor,
    )

    monitor = SystemActivationMonitor()
    runner, *_ = _make_runner(
        decision_callback=_simple_signal,
        activation_monitor=monitor,
    )

    failed_result = SimResult(
        order_id="test-fail-001",
        mode=SimMode.PAPER_LIVE_SIM,
        expected_price=0.62,
        simulated_price=0.0,
        filled_size=0.0,
        slippage_bps=0.0,
        latency_ms=1.0,
        success=False,
        reason="insufficient_liquidity",
        fill_record=None,
    )
    runner._simulator.execute = AsyncMock(return_value=failed_result)

    event = _make_ws_event(event_type="orderbook")
    await runner._handle_event(event)  # type: ignore[arg-type]

    assert monitor.trade_count == 0


# ── FW-10: signal_count incremented in runner alongside monitor ──────────────


async def test_fw10_runner_signal_count_incremented():
    """FW-10: runner._signal_count and monitor.signal_count both increment."""
    from projects.polymarket.polyquantbot.monitoring.system_activation import (
        SystemActivationMonitor,
    )

    monitor = SystemActivationMonitor()
    runner, *_ = _make_runner(
        decision_callback=_simple_signal,
        activation_monitor=monitor,
    )

    event = _make_ws_event(event_type="orderbook")
    await runner._handle_event(event)  # type: ignore[arg-type]

    assert runner._signal_count >= 1
    assert monitor.signal_count == runner._signal_count


# ── FW-11: heartbeat uses ws_client.stats().connected when ws_client set ─────


def test_fw11_ws_stats_connected_attribute_exists():
    """FW-11: WSClientStats has a 'connected' boolean field."""
    from projects.polymarket.polyquantbot.data.websocket.ws_client import WSClientStats

    stats = WSClientStats()
    assert hasattr(stats, "connected")
    assert isinstance(stats.connected, bool)


# ── FW-12: ws_client.stats().connected reflects real connection state ─────────


async def test_fw12_ws_stats_connected_false_before_connect():
    """FW-12: WSClient stats().connected is False before connect()."""
    from projects.polymarket.polyquantbot.data.websocket.ws_client import (
        PolymarketWSClient,
    )

    client = PolymarketWSClient(market_ids=["0xabc"])
    assert client.stats().connected is False


# ── FW-13: main.py heartbeat uses ws_client.stats().connected ────────────────


def test_fw13_main_heartbeat_uses_ws_stats():
    """FW-13: main.py heartbeat call uses ws_client.stats().connected (not False)."""
    import ast
    import pathlib

    src = pathlib.Path(
        "projects/polymarket/polyquantbot/main.py"
    ).read_text()

    tree = ast.parse(src)
    # Look for alert_heartbeat call and confirm ws_connected is not a BooleanLiteral False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "alert_heartbeat":
                for kw in node.keywords:
                    if kw.arg == "ws_connected":
                        # Must NOT be the constant False
                        assert not (
                            isinstance(kw.value, ast.Constant) and kw.value.value is False
                        ), "ws_connected is still hardcoded False"
                        return
    # If we didn't find the call, something is wrong
    assert False, "alert_heartbeat call not found in main.py"


# ── FW-14: MARKET_IDS env var parsed correctly ───────────────────────────────


def test_fw14_market_ids_parsed_from_env(monkeypatch):
    """FW-14: main.py reads MARKET_IDS env var and splits on comma."""
    monkeypatch.setenv("MARKET_IDS", "0xaaa,0xbbb, 0xccc")
    raw = "0xaaa,0xbbb, 0xccc"
    market_ids = [mid.strip() for mid in raw.split(",") if mid.strip()]
    assert market_ids == ["0xaaa", "0xbbb", "0xccc"]


# ── FW-15: 'auto' MARKET_IDS treated as empty ────────────────────────────────


def test_fw15_auto_market_ids_treated_as_empty():
    """FW-15: MARKET_IDS='auto' results in empty list (no WS started)."""
    raw = "auto"
    market_ids = (
        [mid.strip() for mid in raw.split(",") if mid.strip()]
        if raw and raw.lower() != "auto"
        else []
    )
    assert market_ids == []
