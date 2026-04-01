"""Phase 10.8 — Signal Activation Test Suite.

Validates SignalEngine, SignalMetrics, ActivityMonitor, and the Phase 10.8
integration in LivePaperRunner.

Scenarios covered:

  SA-01  SIGNAL_ENGINE — decision_callback_triggered logged on every invocation
  SA-02  SIGNAL_ENGINE — EXECUTE decision logged when edge ≥ threshold
  SA-03  SIGNAL_ENGINE — SKIP decision logged when edge < threshold
  SA-04  SIGNAL_ENGINE — callback returning None is logged as SKIP (low_edge)
  SA-05  SIGNAL_ENGINE — forced test signal emitted after no_signal_timeout_s
  SA-06  SIGNAL_ENGINE — forced test signal resets last_signal_ts
  SA-07  SIGNAL_ENGINE — debug_mode lowers edge threshold
  SA-08  SIGNAL_ENGINE — callback exception → SKIP recorded, no crash
  SA-09  SIGNAL_METRICS — record_generated increments total_generated
  SA-10  SIGNAL_METRICS — record_skip increments correct reason bucket
  SA-11  SIGNAL_METRICS — snapshot returns frozen view of current state
  SA-12  SIGNAL_METRICS — log_summary emits signal_metrics_summary event
  SA-13  ACTIVITY_MONITOR — no alert before alert_window_s
  SA-14  ACTIVITY_MONITOR — signal inactivity alert fired after window
  SA-15  ACTIVITY_MONITOR — order inactivity alert fired after window
  SA-16  ACTIVITY_MONITOR — alert rate-limited (no double fire)
  SA-17  ACTIVITY_MONITOR — counter advance resets idle timer
  SA-18  MESSAGE_FORMATTER — format_no_signal_alert returns expected text
  SA-19  MESSAGE_FORMATTER — format_no_trade_alert returns expected text
  SA-20  LIVE_PAPER_RUNNER — signal_metrics wired into runner
  SA-21  LIVE_PAPER_RUNNER — build_report includes signal_metrics section
  SA-22  LIVE_PAPER_RUNNER — activity monitor launched as background task
  SA-23  LIVE_PAPER_RUNNER — guard rejection records signal_metrics skip
  SA-24  LIVE_PAPER_RUNNER — execution attempt logged before simulator
  SA-25  LIVE_PAPER_RUNNER — phase "10.8" in build_report output
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from projects.polymarket.polyquantbot.monitoring.signal_metrics import (
    SignalMetrics,
    SignalMetricsSnapshot,
    SkipReason,
)
from projects.polymarket.polyquantbot.signal.signal_engine import SignalEngine
from projects.polymarket.polyquantbot.monitoring.activity_monitor import ActivityMonitor
from projects.polymarket.polyquantbot.telegram.message_formatter import (
    format_no_signal_alert,
    format_no_trade_alert,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _noop_callback(market_id: str, ctx: dict) -> Optional[dict]:
    """Callback that always returns None (no signal)."""
    return None


async def _signal_callback(market_id: str, ctx: dict) -> Optional[dict]:
    """Callback that returns a valid signal with clear edge."""
    return {
        "side": "YES",
        "price": 0.45,
        "size_usd": 10.0,
        "p_model": 0.60,
        "p_market": 0.45,
        "expected_ev": 1.5,
    }


async def _low_edge_callback(market_id: str, ctx: dict) -> Optional[dict]:
    """Callback that returns signal with edge below default threshold."""
    return {
        "side": "YES",
        "price": 0.50,
        "size_usd": 10.0,
        "p_model": 0.51,  # edge = 0.01 < default 0.05
        "p_market": 0.50,
        "expected_ev": 0.1,
    }


def _make_metrics() -> SignalMetrics:
    return SignalMetrics()


def _make_engine(
    callback=None,
    debug_mode: bool = False,
    edge_threshold: float = 0.05,
    no_signal_timeout_s: float = 9999.0,
) -> SignalEngine:
    metrics = _make_metrics()
    return SignalEngine(
        decision_callback=callback or _noop_callback,
        signal_metrics=metrics,
        debug_mode=debug_mode,
        edge_threshold=edge_threshold,
        no_signal_timeout_s=no_signal_timeout_s,
    )


# ─────────────────────────────────────────────────────────────────────────────
# SA-01 … SA-08 — SignalEngine
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sa01_decision_callback_triggered_logged():
    """SA-01: decision_callback_triggered is logged on every invocation."""
    engine = _make_engine(callback=_noop_callback)

    with patch("projects.polymarket.polyquantbot.signal.signal_engine.log") as mock_log:
        mock_log.debug = MagicMock()
        await engine("0xabc", {})
        calls = [str(c) for c in mock_log.debug.call_args_list]
        assert any("decision_callback_triggered" in c for c in calls)


@pytest.mark.asyncio
async def test_sa02_execute_decision_logged_when_edge_sufficient():
    """SA-02: EXECUTE logged when edge ≥ threshold."""
    engine = _make_engine(callback=_signal_callback, edge_threshold=0.05)
    logged_events = []

    original_info = engine._log_decision

    def capturing_log(*args, **kwargs):
        logged_events.append(kwargs)

    engine._log_decision = capturing_log  # type: ignore[method-assign]
    result = await engine("0xabc", {"mid": 0.45})

    assert result is not None
    assert result["side"] == "YES"
    assert any(e.get("decision") == "EXECUTE" for e in logged_events)


@pytest.mark.asyncio
async def test_sa03_skip_decision_logged_when_edge_insufficient():
    """SA-03: SKIP logged when edge < threshold."""
    engine = _make_engine(callback=_low_edge_callback, edge_threshold=0.05)
    logged_events = []
    engine._log_decision = lambda **kwargs: logged_events.append(kwargs)  # type: ignore[method-assign]

    result = await engine("0xabc", {"mid": 0.50})

    assert result is None
    assert any(e.get("decision") == "SKIP" for e in logged_events)


@pytest.mark.asyncio
async def test_sa04_none_callback_logged_as_skip():
    """SA-04: Callback returning None records skip with low_edge reason."""
    metrics = _make_metrics()
    engine = SignalEngine(
        decision_callback=_noop_callback,
        signal_metrics=metrics,
        debug_mode=False,
        no_signal_timeout_s=9999.0,
    )

    await engine("0xabc", {"mid": 0.50})

    snap = metrics.snapshot()
    assert snap.total_skipped >= 1
    assert snap.skipped_low_edge >= 1


@pytest.mark.asyncio
async def test_sa05_forced_test_signal_emitted_after_timeout():
    """SA-05: Forced test signal emitted when timeout has passed."""
    engine = _make_engine(callback=_noop_callback, no_signal_timeout_s=0.0)
    # Timeout is 0s, so immediately eligible for test signal

    result = await engine("0xabc", {"bid": 0.48, "ask": 0.52})

    assert result is not None
    assert result.get("is_debug_signal") is True
    assert result.get("size_usd") == 1.0


@pytest.mark.asyncio
async def test_sa06_forced_test_signal_resets_last_signal_ts():
    """SA-06: Forced test signal resets _last_signal_ts."""
    engine = _make_engine(callback=_noop_callback, no_signal_timeout_s=0.0)

    before = time.time()
    await engine("0xabc", {"bid": 0.48, "ask": 0.52})

    assert engine._last_signal_ts >= before


@pytest.mark.asyncio
async def test_sa07_debug_mode_lowers_threshold():
    """SA-07: Debug mode uses debug_edge_threshold instead of normal."""
    # low_edge_callback has edge=0.01; normal threshold=0.05 would skip,
    # but debug threshold=0.02 would also skip (0.01 < 0.02).
    # Use an edge=0.03 callback with debug_threshold=0.02 to verify EXECUTE.

    async def medium_edge_cb(market_id: str, ctx: dict) -> Optional[dict]:
        return {
            "side": "YES",
            "price": 0.50,
            "size_usd": 5.0,
            "p_model": 0.53,  # edge=0.03
            "p_market": 0.50,
            "expected_ev": 0.15,
        }

    metrics = _make_metrics()
    engine = SignalEngine(
        decision_callback=medium_edge_cb,
        signal_metrics=metrics,
        debug_mode=True,
        edge_threshold=0.05,
        debug_edge_threshold=0.02,
        no_signal_timeout_s=9999.0,
    )

    result = await engine("0xabc", {"mid": 0.50})
    assert result is not None  # 0.03 ≥ 0.02 in debug mode → EXECUTE


@pytest.mark.asyncio
async def test_sa08_callback_exception_records_skip():
    """SA-08: Exception in callback is caught and skip recorded as RISK_BLOCK; no crash."""

    async def error_callback(market_id: str, ctx: dict) -> Optional[dict]:
        raise RuntimeError("boom")

    metrics = _make_metrics()
    engine = SignalEngine(
        decision_callback=error_callback,
        signal_metrics=metrics,
        debug_mode=False,
        no_signal_timeout_s=9999.0,
    )

    result = await engine("0xabc", {})

    assert result is None
    snap = metrics.snapshot()
    assert snap.total_skipped >= 1
    # Exception is NOT a low-edge skip — it's a system block
    assert snap.skipped_risk_block >= 1


# ─────────────────────────────────────────────────────────────────────────────
# SA-09 … SA-12 — SignalMetrics
# ─────────────────────────────────────────────────────────────────────────────


def test_sa09_record_generated_increments():
    """SA-09: record_generated increments total_generated."""
    m = SignalMetrics()
    assert m.total_generated == 0
    m.record_generated()
    m.record_generated()
    assert m.total_generated == 2


def test_sa10_record_skip_increments_correct_bucket():
    """SA-10: record_skip increments correct reason bucket."""
    m = SignalMetrics()
    m.record_skip(SkipReason.LOW_EDGE)
    m.record_skip(SkipReason.LOW_EDGE)
    m.record_skip(SkipReason.LOW_LIQUIDITY)
    m.record_skip(SkipReason.RISK_BLOCK)
    m.record_skip(SkipReason.DUPLICATE)

    snap = m.snapshot()
    assert snap.skipped_low_edge == 2
    assert snap.skipped_low_liquidity == 1
    assert snap.skipped_risk_block == 1
    assert snap.skipped_duplicate == 1
    assert snap.total_skipped == 5


def test_sa11_snapshot_returns_frozen_view():
    """SA-11: Snapshot is a dataclass; mutations after snapshot don't affect it."""
    m = SignalMetrics()
    m.record_generated()
    snap1 = m.snapshot()
    m.record_generated()
    snap2 = m.snapshot()

    assert snap1.total_generated == 1
    assert snap2.total_generated == 2


def test_sa12_log_summary_emits_event(caplog):
    """SA-12: log_summary emits a structured log event."""
    import logging
    m = SignalMetrics()
    m.record_generated()
    m.record_skip(SkipReason.LOW_EDGE)

    with patch("projects.polymarket.polyquantbot.monitoring.signal_metrics.log") as mock_log:
        mock_log.info = MagicMock()
        m.log_summary()
        mock_log.info.assert_called_once()
        call_args = mock_log.info.call_args
        assert call_args[0][0] == "signal_metrics_summary"


# ─────────────────────────────────────────────────────────────────────────────
# SA-13 … SA-17 — ActivityMonitor
# ─────────────────────────────────────────────────────────────────────────────


def _make_monitor(
    signal_count: int = 0,
    order_count: int = 0,
    alert_window_s: float = 60.0,
) -> tuple[ActivityMonitor, AsyncMock]:
    telegram = MagicMock()
    telegram.alert_error = AsyncMock()

    signal_val = signal_count
    order_val = order_count

    monitor = ActivityMonitor(
        telegram=telegram,
        signal_source=lambda: signal_val,
        order_source=lambda: order_val,
        check_interval_s=0.01,
        alert_window_s=alert_window_s,
    )
    return monitor, telegram.alert_error


@pytest.mark.asyncio
async def test_sa13_no_alert_before_window():
    """SA-13: No alert sent when idle time < alert_window_s."""
    monitor, alert_mock = _make_monitor(signal_count=0, alert_window_s=3600.0)
    monitor._last_signal_activity_ts = time.time()  # just started
    monitor._last_order_activity_ts = time.time()

    await monitor._check()

    alert_mock.assert_not_called()


@pytest.mark.asyncio
async def test_sa14_signal_inactivity_alert_fired():
    """SA-14: Signal inactivity alert fires when idle >= alert_window_s."""
    monitor, alert_mock = _make_monitor(signal_count=0, alert_window_s=10.0)
    monitor._last_signal_activity_ts = time.time() - 20.0  # 20s idle, window=10s

    await monitor._check()

    alert_mock.assert_called_once()
    call_args = str(alert_mock.call_args)
    assert "NO SIGNAL" in call_args


@pytest.mark.asyncio
async def test_sa15_order_inactivity_alert_fired():
    """SA-15: Order inactivity alert fires when idle >= alert_window_s."""
    monitor, alert_mock = _make_monitor(order_count=0, alert_window_s=10.0)
    monitor._last_order_activity_ts = time.time() - 20.0

    await monitor._check()

    # May fire both; at least one should mention NO TRADE
    calls = [str(c) for c in alert_mock.call_args_list]
    assert any("NO TRADE" in c for c in calls)


@pytest.mark.asyncio
async def test_sa16_alert_rate_limited():
    """SA-16: Alert is rate-limited; second immediate call does not fire again."""
    monitor, alert_mock = _make_monitor(signal_count=0, alert_window_s=5.0)
    monitor._last_signal_activity_ts = time.time() - 10.0

    await monitor._alert_no_signals(idle_s=10.0, signal_count=0)
    await monitor._alert_no_signals(idle_s=11.0, signal_count=0)  # rate-limited

    assert alert_mock.call_count == 1


@pytest.mark.asyncio
async def test_sa17_counter_advance_resets_idle():
    """SA-17: When signal counter advances, idle timer resets; no alert."""
    signal_count = 0
    monitor = ActivityMonitor(
        telegram=MagicMock(alert_error=AsyncMock()),
        signal_source=lambda: signal_count,
        order_source=lambda: 0,
        check_interval_s=0.01,
        alert_window_s=5.0,
    )
    monitor._last_signal_activity_ts = time.time() - 10.0  # looks idle

    # Advance counter to simulate a signal arriving
    signal_count = 1
    monitor._last_signal_count = 0  # ensure advance is detected

    await monitor._check()

    # After counter advance, idle timer resets — should not have fired alert
    assert monitor._last_signal_count == 1


# ─────────────────────────────────────────────────────────────────────────────
# SA-18 … SA-19 — Message formatter
# ─────────────────────────────────────────────────────────────────────────────


def test_sa18_format_no_signal_alert():
    """SA-18: format_no_signal_alert returns expected content."""
    msg = format_no_signal_alert(idle_s=3600.0, signal_count=0)

    assert "NO SIGNAL ACTIVITY" in msg
    assert "1.0h" in msg


def test_sa19_format_no_trade_alert():
    """SA-19: format_no_trade_alert returns expected content."""
    msg = format_no_trade_alert(idle_s=7200.0, order_count=0)

    assert "NO TRADE ACTIVITY" in msg
    assert "2.0h" in msg


# ─────────────────────────────────────────────────────────────────────────────
# SA-20 … SA-25 — LivePaperRunner integration
# ─────────────────────────────────────────────────────────────────────────────


def _make_runner_for_signal_test(callback=None):
    """Build a minimal LivePaperRunner with stubbed dependencies."""
    from unittest.mock import MagicMock, AsyncMock
    from projects.polymarket.polyquantbot.phase10.live_paper_runner import LivePaperRunner
    from projects.polymarket.polyquantbot.phase10.go_live_controller import (
        GoLiveController, TradingMode,
    )
    from projects.polymarket.polyquantbot.monitoring.signal_metrics import SignalMetrics

    ws = MagicMock()
    ws.stats = MagicMock(return_value=MagicMock(reconnects=0))

    books = MagicMock()
    cache = MagicMock()
    cache.is_stale = MagicMock(return_value=False)

    simulator = MagicMock()
    simulator._send_real_orders = False

    fill_tracker = MagicMock()
    latency_tracker = MagicMock()
    feedback = MagicMock()

    go_live = GoLiveController(mode=TradingMode.PAPER, max_capital_usd=1000.0)

    guard = MagicMock()
    metrics = MagicMock()
    metrics.compute = MagicMock(
        return_value=MagicMock(
            ev_capture_ratio=0.8,
            fill_rate=0.7,
            p95_latency=300.0,
            drawdown=0.01,
            avg_slippage_bps=5.0,
            p95_slippage_bps=10.0,
            worst_slippage_bps=15.0,
            total_trades=5,
            go_live_ready=True,
            gate_details={},
        )
    )

    risk = MagicMock()
    risk.disabled = False

    telegram = MagicMock()
    telegram.enabled = True
    telegram.alert_error = AsyncMock()
    telegram.alert_kill = AsyncMock()
    telegram.start = AsyncMock()
    telegram.stop = AsyncMock()

    sig_metrics = SignalMetrics()

    runner = LivePaperRunner(
        ws_client=ws,
        orderbook_manager=books,
        market_cache=cache,
        trade_flow_analyzer=MagicMock(),
        simulator=simulator,
        fill_tracker=fill_tracker,
        latency_tracker=latency_tracker,
        feedback_tracker=feedback,
        go_live_controller=go_live,
        execution_guard=guard,
        metrics_validator=metrics,
        risk_guard=risk,
        telegram=telegram,
        market_ids=["0xabc"],
        decision_callback=callback,
        signal_metrics=sig_metrics,
    )
    return runner, sig_metrics


def test_sa20_signal_metrics_wired():
    """SA-20: signal_metrics is accessible on runner and has correct type."""
    from projects.polymarket.polyquantbot.monitoring.signal_metrics import SignalMetrics

    runner, sig_metrics = _make_runner_for_signal_test(callback=_signal_callback)

    assert isinstance(runner._signal_metrics, SignalMetrics)
    assert runner._signal_metrics is sig_metrics


def test_sa21_build_report_includes_signal_metrics():
    """SA-21: build_report includes signal_metrics section and phase 10.8."""
    runner, sig_metrics = _make_runner_for_signal_test(callback=_signal_callback)
    runner._start_ts = time.time()

    report = runner.build_report()

    assert report["phase"] == "10.8"
    assert "signal_metrics" in report
    assert "total_generated" in report["signal_metrics"]
    assert "total_skipped" in report["signal_metrics"]


def test_sa22_activity_monitor_is_activity_monitor():
    """SA-22: _activity_monitor is an ActivityMonitor instance."""
    runner, _ = _make_runner_for_signal_test()

    assert isinstance(runner._activity_monitor, ActivityMonitor)


@pytest.mark.asyncio
async def test_sa23_guard_rejection_records_signal_metrics_skip():
    """SA-23: ExecutionGuard rejection records a signal_metrics skip."""
    from projects.polymarket.polyquantbot.phase10.live_paper_runner import LivePaperRunner

    runner, sig_metrics = _make_runner_for_signal_test(callback=_signal_callback)
    runner._start_ts = time.time()

    # Guard always rejects
    guard_result = MagicMock()
    guard_result.passed = False
    guard_result.reason = "low_liquidity"
    runner._guard.validate = MagicMock(return_value=guard_result)
    # risk.check_daily_loss must be awaitable
    runner._risk.check_daily_loss = AsyncMock()

    signal = {
        "side": "YES",
        "price": 0.45,
        "size_usd": 10.0,
        "p_model": 0.60,
        "p_market": 0.45,
        "expected_ev": 1.5,
    }
    ctx = {"depth": 5.0, "spread": 0.02, "mid": 0.45, "orderbook": None}

    result = await runner._simulate_order(
        market_id="0xabc",
        signal=signal,
        market_ctx=ctx,
        data_received_ts=time.time(),
        signal_generated_ts=time.time(),
    )

    assert result is None
    snap = sig_metrics.snapshot()
    assert snap.total_skipped >= 1


@pytest.mark.asyncio
async def test_sa24_execution_attempt_logged(caplog):
    """SA-24: live_paper_runner_execution_attempt is logged before simulator."""
    from projects.polymarket.polyquantbot.execution.simulator import SimResult, SimMode

    runner, _ = _make_runner_for_signal_test(callback=_signal_callback)
    runner._start_ts = time.time()

    guard_result = MagicMock()
    guard_result.passed = True
    guard_result.reason = None
    runner._guard.validate = MagicMock(return_value=guard_result)
    runner._risk.check_daily_loss = AsyncMock()

    sim_result = SimResult(
        order_id="test-001",
        mode=SimMode.PAPER_LIVE_SIM,
        expected_price=0.45,
        simulated_price=0.45,
        filled_size=10.0,
        slippage_bps=2.0,
        latency_ms=10.0,
        success=True,
        reason="",
        fill_record=None,
    )
    runner._simulator.execute = AsyncMock(return_value=sim_result)
    runner._metrics.record_latency = MagicMock()
    runner._metrics.record_fill = MagicMock()
    runner._metrics.record_ev_signal = MagicMock()
    runner._metrics.record_pnl_sample = MagicMock()
    runner._metrics.record_slippage = MagicMock()
    runner._telegram.alert_error = AsyncMock()

    logged_events = []
    original_info = None

    with patch(
        "projects.polymarket.polyquantbot.phase10.live_paper_runner.log"
    ) as mock_log:
        mock_log.info = MagicMock(side_effect=lambda event, **kw: logged_events.append(event))
        mock_log.warning = MagicMock()
        mock_log.debug = MagicMock()
        mock_log.error = MagicMock()

        signal = {
            "side": "YES",
            "price": 0.45,
            "size_usd": 10.0,
            "expected_ev": 1.5,
        }
        ctx = {"depth": 100.0, "spread": 0.02, "mid": 0.45, "orderbook": None}

        await runner._simulate_order(
            market_id="0xabc",
            signal=signal,
            market_ctx=ctx,
            data_received_ts=time.time(),
            signal_generated_ts=time.time(),
        )

    assert "live_paper_runner_execution_attempt" in logged_events


def test_sa25_build_report_phase_is_10_8():
    """SA-25: build_report returns phase '10.8'."""
    runner, _ = _make_runner_for_signal_test()
    runner._start_ts = time.time()

    report = runner.build_report()

    assert report["phase"] == "10.8"


# ─────────────────────────────────────────────────────────────────────────────
# RC-01 … RC-05 — RunController Phase 10.8 validation
# ─────────────────────────────────────────────────────────────────────────────


def test_rc01_minimum_6h_duration_enforced():
    """RC-01: RunController raises ValueError when duration < 6 hours."""
    from projects.polymarket.polyquantbot.phase10.run_controller import RunController, _MIN_DURATION_S

    runner, _ = _make_runner_for_signal_test()

    with pytest.raises(ValueError, match="minimum allowed run duration"):
        RunController(runner=runner, duration_s=_MIN_DURATION_S - 1.0)


def test_rc01b_exactly_6h_is_accepted():
    """RC-01b: RunController accepts exactly 6 hours (boundary condition)."""
    from projects.polymarket.polyquantbot.phase10.run_controller import RunController, _MIN_DURATION_S

    runner, _ = _make_runner_for_signal_test()
    ctrl = RunController(runner=runner, duration_s=_MIN_DURATION_S)
    assert ctrl._duration_s == _MIN_DURATION_S


@pytest.mark.asyncio
async def test_rc02_two_hour_validation_critical_failure_no_signals():
    """RC-02: 2H validation sets critical_failure when signals_generated == 0."""
    from unittest.mock import patch
    from projects.polymarket.polyquantbot.phase10.run_controller import RunController

    runner, _ = _make_runner_for_signal_test()
    runner._signal_count = 0
    runner._sim_order_count = 0
    runner._start_ts = time.time()

    ctrl = RunController(runner=runner, duration_s=6 * 3600.0)
    ctrl._start_ts = time.time()

    with patch(
        "projects.polymarket.polyquantbot.phase10.run_controller._SIGNAL_VALIDATION_WINDOW_S",
        0.0,
    ):
        await ctrl._signal_validation()

    assert ctrl.critical_failure is True
    assert any("signals_generated=0" in r for r in ctrl.critical_failure_reasons)


@pytest.mark.asyncio
async def test_rc03_two_hour_validation_critical_failure_no_orders():
    """RC-03: 2H validation sets critical_failure when orders_attempted == 0."""
    from unittest.mock import patch
    from projects.polymarket.polyquantbot.phase10.run_controller import RunController

    runner, _ = _make_runner_for_signal_test()
    runner._signal_count = 5
    runner._sim_order_count = 0
    runner._start_ts = time.time()

    ctrl = RunController(runner=runner, duration_s=6 * 3600.0)
    ctrl._start_ts = time.time()

    with patch(
        "projects.polymarket.polyquantbot.phase10.run_controller._SIGNAL_VALIDATION_WINDOW_S",
        0.0,
    ):
        await ctrl._signal_validation()

    assert ctrl.critical_failure is True
    assert any("orders_attempted=0" in r for r in ctrl.critical_failure_reasons)


@pytest.mark.asyncio
async def test_rc04_two_hour_validation_passes_when_both_nonzero():
    """RC-04: 2H validation does NOT set critical_failure when signals > 0 and orders > 0."""
    from unittest.mock import patch
    from projects.polymarket.polyquantbot.phase10.run_controller import RunController

    runner, _ = _make_runner_for_signal_test()
    runner._signal_count = 3
    runner._sim_order_count = 2
    runner._start_ts = time.time()

    ctrl = RunController(runner=runner, duration_s=6 * 3600.0)
    ctrl._start_ts = time.time()

    with patch(
        "projects.polymarket.polyquantbot.phase10.run_controller._SIGNAL_VALIDATION_WINDOW_S",
        0.0,
    ):
        await ctrl._signal_validation()

    assert ctrl.critical_failure is False
    assert ctrl.critical_failure_reasons == []


@pytest.mark.asyncio
async def test_rc05_final_report_includes_critical_failure_flag():
    """RC-05: final_report dict includes critical_failure and signal_metrics after finalize."""
    from unittest.mock import patch
    from projects.polymarket.polyquantbot.phase10.run_controller import RunController

    runner, sig_metrics = _make_runner_for_signal_test()
    runner._signal_count = 0
    runner._sim_order_count = 0
    runner._start_ts = time.time()

    ctrl = RunController(runner=runner, duration_s=6 * 3600.0)
    ctrl._start_ts = time.time()

    with patch(
        "projects.polymarket.polyquantbot.phase10.run_controller._SIGNAL_VALIDATION_WINDOW_S",
        0.0,
    ):
        await ctrl._signal_validation()

    with patch.object(ctrl, "_report_path", "/tmp/test_phase108_rc05_report.json"):
        await ctrl._finalize()

    report = ctrl.final_report
    assert report is not None
    assert "critical_failure" in report
    assert report["critical_failure"] is True
    assert "critical_failure_reasons" in report
    assert isinstance(report["critical_failure_reasons"], list)
    assert "signal_metrics" in report
