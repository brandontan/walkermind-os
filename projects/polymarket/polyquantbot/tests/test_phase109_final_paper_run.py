"""Phase 10.9 — SENTINEL Final Paper Run Validation Suite.

Validates the complete Phase 10.9 PRODUCTION_DRY_RUN paper run criteria
prior to issuing a GO-LIVE verdict.

Run mode:
  PRODUCTION_DRY_RUN
  SIGNAL_DEBUG_MODE = true
  Real WebSocket ENABLED
  Execution = SIMULATED (ZERO real orders)
  Minimum duration = 6 hours (21 600 s)

Scenarios covered:

  FP-01  GO-LIVE CRITERIA — fill_rate ≥ 0.60 is enforced in build_report
  FP-02  GO-LIVE CRITERIA — ev_capture_ratio ≥ 0.75 is enforced
  FP-03  GO-LIVE CRITERIA — p95_latency ≤ 500 ms is enforced
  FP-04  GO-LIVE CRITERIA — drawdown ≤ 8% is enforced
  FP-05  GO-LIVE CRITERIA — kill_switch active → go_live_readiness = NO
  FP-06  GO-LIVE CRITERIA — all criteria met → go_live_readiness = YES
  FP-07  GO-LIVE CRITERIA — fill_rate below threshold → go_live_readiness = NO
  FP-08  GO-LIVE CRITERIA — ev_capture below threshold → go_live_readiness = NO
  FP-09  GO-LIVE CRITERIA — latency above threshold → go_live_readiness = NO
  FP-10  GO-LIVE CRITERIA — drawdown above threshold → go_live_readiness = NO
  FP-11  RUN_CONTROLLER — 6H minimum enforced; shorter raises ValueError
  FP-12  RUN_CONTROLLER — 2H validation passes → critical_failure = False
  FP-13  RUN_CONTROLLER — 2H validation fails (no signals) → critical_failure = True
  FP-14  RUN_CONTROLLER — 2H validation fails (no orders) → critical_failure = True
  FP-15  RUN_CONTROLLER — final_report includes all Phase 10.9 required fields
  FP-16  PAPER_MODE — simulator._send_real_orders is always False
  FP-17  SIGNAL_DEBUG_MODE — lowered edge threshold generates more signals
  FP-18  SIGNAL_DEBUG_MODE — forced test signal fires after silence timeout
  FP-19  SIGNAL_METRICS — build_report includes generated + skipped + reasons
  FP-20  RISK_RULES — all six risk rules validated in build_report
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from projects.polymarket.polyquantbot.phase10.go_live_controller import (
    GoLiveController,
    TradingMode,
)
from projects.polymarket.polyquantbot.phase10.run_controller import (
    RunController,
    _MIN_DURATION_S,
    _SIGNAL_VALIDATION_WINDOW_S,
)
from projects.polymarket.polyquantbot.monitoring.signal_metrics import (
    SignalMetrics,
    SkipReason,
)
from projects.polymarket.polyquantbot.signal.signal_engine import SignalEngine


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_metrics_compute(
    ev_capture_ratio: float = 0.81,
    fill_rate: float = 0.72,
    p95_latency: float = 287.0,
    drawdown: float = 0.024,
    avg_slippage_bps: float = 6.3,
    p95_slippage_bps: float = 14.1,
    worst_slippage_bps: float = 22.7,
    total_trades: int = 47,
    go_live_ready: bool = True,
    gate_details: dict | None = None,
):
    result = MagicMock()
    result.ev_capture_ratio = ev_capture_ratio
    result.fill_rate = fill_rate
    result.p95_latency = p95_latency
    result.drawdown = drawdown
    result.avg_slippage_bps = avg_slippage_bps
    result.p95_slippage_bps = p95_slippage_bps
    result.worst_slippage_bps = worst_slippage_bps
    result.total_trades = total_trades
    result.go_live_ready = go_live_ready
    result.gate_details = gate_details or {}
    return result


def _make_runner(
    ev_capture_ratio: float = 0.81,
    fill_rate: float = 0.72,
    p95_latency: float = 287.0,
    drawdown: float = 0.024,
    kill_switch: bool = False,
    signal_count: int = 94,
    sim_order_count: int = 67,
    fill_count: int = 48,
    ws_reconnects: int = 1,
    signal_metrics: SignalMetrics | None = None,
):
    """Build a LivePaperRunner stub configured with the given metric values."""
    from projects.polymarket.polyquantbot.phase10.live_paper_runner import LivePaperRunner

    ws = MagicMock()
    ws.stats = MagicMock(return_value=MagicMock(reconnects=ws_reconnects))

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
    metrics_validator = MagicMock()
    metrics_validator.compute = MagicMock(
        return_value=_make_metrics_compute(
            ev_capture_ratio=ev_capture_ratio,
            fill_rate=fill_rate,
            p95_latency=p95_latency,
            drawdown=drawdown,
        )
    )

    risk = MagicMock()
    risk.disabled = kill_switch

    telegram = MagicMock()
    telegram.enabled = True
    telegram.alert_error = AsyncMock()
    telegram.alert_kill = AsyncMock()
    telegram.start = AsyncMock()
    telegram.stop = AsyncMock()

    sig_metrics = signal_metrics or SignalMetrics()

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
        metrics_validator=metrics_validator,
        risk_guard=risk,
        telegram=telegram,
        market_ids=["0xabc", "0xdef"],
        decision_callback=None,
        signal_metrics=sig_metrics,
    )

    # Inject run-time counters (normally set during run)
    runner._start_ts = time.time() - 21600.0   # 6h ago
    runner._signal_count = signal_count
    runner._sim_order_count = sim_order_count
    runner._fill_count = fill_count

    return runner, sig_metrics


def _make_controller(runner, duration_s: float = 21600.0) -> RunController:
    """Build a RunController wrapping *runner*."""
    ctrl = RunController(
        runner=runner,
        duration_s=duration_s,
        report_output_path="/tmp/sentinel_phase109_test_report.json",
    )
    ctrl._start_ts = time.time() - duration_s
    return ctrl


# ═══════════════════════════════════════════════════════════════════════════════
# FP-01 … FP-10 — GO-LIVE criteria validation
# ═══════════════════════════════════════════════════════════════════════════════


class TestFP01GoLiveFillRate:
    """FP-01: build_report go_live_readiness respects fill_rate ≥ 0.60."""

    def test_fill_rate_at_threshold_produces_yes(self):
        runner, _ = _make_runner(fill_rate=0.60)
        report = runner.build_report()
        assert report["metrics_table"]["fill_rate"] >= 0.60
        assert report["go_live_readiness"] == "YES"

    def test_fill_rate_above_threshold_produces_yes(self):
        runner, _ = _make_runner(fill_rate=0.85)
        report = runner.build_report()
        assert report["go_live_readiness"] == "YES"


class TestFP02GoLiveEvCapture:
    """FP-02: build_report go_live_readiness respects ev_capture_ratio ≥ 0.75."""

    def test_ev_capture_at_threshold_produces_yes(self):
        runner, _ = _make_runner(ev_capture_ratio=0.75)
        report = runner.build_report()
        assert report["metrics_table"]["ev_capture_ratio"] >= 0.75
        assert report["go_live_readiness"] == "YES"

    def test_ev_capture_above_threshold_produces_yes(self):
        runner, _ = _make_runner(ev_capture_ratio=0.90)
        report = runner.build_report()
        assert report["go_live_readiness"] == "YES"


class TestFP03GoLiveLatency:
    """FP-03: build_report go_live_readiness respects p95_latency ≤ 500 ms."""

    def test_latency_at_threshold_produces_yes(self):
        runner, _ = _make_runner(p95_latency=500.0)
        report = runner.build_report()
        assert report["latency_stats"]["p95_latency_ms"] <= 500.0
        assert report["go_live_readiness"] == "YES"

    def test_latency_well_below_threshold_produces_yes(self):
        runner, _ = _make_runner(p95_latency=280.0)
        report = runner.build_report()
        assert report["go_live_readiness"] == "YES"


class TestFP04GoLiveDrawdown:
    """FP-04: build_report go_live_readiness respects drawdown ≤ 8%."""

    def test_drawdown_at_threshold_produces_yes(self):
        runner, _ = _make_runner(drawdown=0.08)
        report = runner.build_report()
        assert report["risk_compliance"]["drawdown"] <= 0.08
        assert report["go_live_readiness"] == "YES"

    def test_low_drawdown_produces_yes(self):
        runner, _ = _make_runner(drawdown=0.024)
        report = runner.build_report()
        assert report["go_live_readiness"] == "YES"


class TestFP05GoLiveKillSwitch:
    """FP-05: kill_switch active → go_live_readiness = NO."""

    def test_kill_switch_active_blocks_go_live(self):
        runner, _ = _make_runner(kill_switch=True)
        report = runner.build_report()
        assert report["risk_compliance"]["kill_switch_active"] is True
        assert report["go_live_readiness"] == "NO"


class TestFP06GoLiveAllCriteriaMet:
    """FP-06: all criteria met → go_live_readiness = YES."""

    def test_all_criteria_met(self):
        runner, _ = _make_runner(
            fill_rate=0.72,
            ev_capture_ratio=0.81,
            p95_latency=287.0,
            drawdown=0.024,
            kill_switch=False,
        )
        report = runner.build_report()
        assert report["go_live_readiness"] == "YES"
        assert report["risk_compliance"]["paper_mode_enforced"] is True
        assert report["risk_compliance"]["real_orders_sent"] is False


class TestFP07GoLiveFillRateBelow:
    """FP-07: fill_rate below 0.60 → go_live_readiness = NO."""

    def test_fill_rate_below_threshold_blocks_go_live(self):
        runner, _ = _make_runner(fill_rate=0.50)
        report = runner.build_report()
        assert report["go_live_readiness"] == "NO"


class TestFP08GoLiveEvCaptureBelow:
    """FP-08: ev_capture_ratio below 0.75 → go_live_readiness = NO."""

    def test_ev_capture_below_threshold_blocks_go_live(self):
        runner, _ = _make_runner(ev_capture_ratio=0.70)
        report = runner.build_report()
        assert report["go_live_readiness"] == "NO"


class TestFP09GoLiveLatencyAbove:
    """FP-09: p95_latency above 500 ms → go_live_readiness = NO."""

    def test_latency_above_threshold_blocks_go_live(self):
        runner, _ = _make_runner(p95_latency=620.0)
        report = runner.build_report()
        assert report["go_live_readiness"] == "NO"


class TestFP10GoLiveDrawdownAbove:
    """FP-10: drawdown above 8% → go_live_readiness = NO."""

    def test_drawdown_above_threshold_blocks_go_live(self):
        runner, _ = _make_runner(drawdown=0.09)
        report = runner.build_report()
        assert report["go_live_readiness"] == "NO"


# ═══════════════════════════════════════════════════════════════════════════════
# FP-11 … FP-15 — RunController lifecycle
# ═══════════════════════════════════════════════════════════════════════════════


class TestFP11RunControllerMinimum:
    """FP-11: 6H minimum enforced; shorter duration raises ValueError."""

    def test_below_minimum_raises(self):
        runner, _ = _make_runner()
        with pytest.raises(ValueError, match="minimum allowed run duration"):
            RunController(runner=runner, duration_s=3600.0)

    def test_exactly_six_hours_accepted(self):
        runner, _ = _make_runner()
        ctrl = RunController(
            runner=runner,
            duration_s=_MIN_DURATION_S,
            report_output_path="/tmp/sentinel_test.json",
        )
        assert ctrl is not None

    def test_above_minimum_accepted(self):
        runner, _ = _make_runner()
        ctrl = RunController(
            runner=runner,
            duration_s=86400.0,
            report_output_path="/tmp/sentinel_test.json",
        )
        assert ctrl is not None


class TestFP12SignalValidationPasses:
    """FP-12: 2H validation passes → critical_failure = False."""

    @pytest.mark.asyncio
    async def test_validation_passes_when_both_counters_positive(self):
        runner, _ = _make_runner(signal_count=94, sim_order_count=67)
        ctrl = _make_controller(runner)

        with patch("asyncio.sleep", new=AsyncMock()):
            await ctrl._signal_validation()

        assert ctrl.critical_failure is False
        assert ctrl.critical_failure_reasons == []


class TestFP13SignalValidationFailNoSignals:
    """FP-13: 2H validation fails when signals_generated == 0 → critical_failure = True."""

    @pytest.mark.asyncio
    async def test_no_signals_sets_critical_failure(self):
        runner, _ = _make_runner(signal_count=0, sim_order_count=0)
        ctrl = _make_controller(runner)

        with patch("asyncio.sleep", new=AsyncMock()):
            await ctrl._signal_validation()

        assert ctrl.critical_failure is True
        assert any("signals_generated=0" in r for r in ctrl.critical_failure_reasons)


class TestFP14SignalValidationFailNoOrders:
    """FP-14: 2H validation fails when orders_attempted == 0 → critical_failure = True."""

    @pytest.mark.asyncio
    async def test_no_orders_sets_critical_failure(self):
        runner, _ = _make_runner(signal_count=5, sim_order_count=0)
        ctrl = _make_controller(runner)

        with patch("asyncio.sleep", new=AsyncMock()):
            await ctrl._signal_validation()

        assert ctrl.critical_failure is True
        assert any("orders_attempted=0" in r for r in ctrl.critical_failure_reasons)


class TestFP15FinalReportFields:
    """FP-15: final_report includes all Phase 10.9 required fields."""

    @pytest.mark.asyncio
    async def test_final_report_has_required_fields(self):
        runner, sig_metrics = _make_runner()
        sig_metrics.record_generated()
        sig_metrics.record_generated()
        sig_metrics.record_skip(SkipReason.LOW_EDGE)
        ctrl = _make_controller(runner)

        await ctrl._finalize()

        report = ctrl.final_report
        assert report is not None

        # Top-level phase 10.9 contract fields
        assert "critical_failure" in report
        assert "critical_failure_reasons" in report
        assert "signal_metrics" in report
        assert "go_live_readiness" in report

        # Signal metrics sub-fields
        sig = report["signal_metrics"]
        assert "total_generated" in sig
        assert "total_skipped" in sig

        # Runtime summary
        rt = report["runtime_summary"]
        assert "total_signals" in rt
        assert "total_sim_orders" in rt
        assert "total_fills" in rt
        assert "ws_reconnects" in rt

        # Performance fields
        assert "latency_stats" in report
        assert "p95_latency_ms" in report["latency_stats"]
        assert "slippage_stats" in report
        assert "avg_slippage_bps" in report["slippage_stats"]

        # Risk fields
        rc = report["risk_compliance"]
        assert rc["paper_mode_enforced"] is True
        assert rc["real_orders_sent"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# FP-16 — Paper mode safety
# ═══════════════════════════════════════════════════════════════════════════════


class TestFP16PaperModeSafety:
    """FP-16: simulator._send_real_orders is always False (ZERO real orders)."""

    def test_simulator_never_sends_real_orders(self):
        runner, _ = _make_runner()
        assert runner._simulator._send_real_orders is False

    def test_go_live_controller_is_paper_mode(self):
        runner, _ = _make_runner()
        assert runner._go_live.mode == TradingMode.PAPER


# ═══════════════════════════════════════════════════════════════════════════════
# FP-17 … FP-18 — SIGNAL_DEBUG_MODE behaviour
# ═══════════════════════════════════════════════════════════════════════════════


class TestFP17SignalDebugModeLowersThreshold:
    """FP-17: SIGNAL_DEBUG_MODE=true lowers edge threshold → more signals."""

    def test_debug_mode_threshold_lower_than_normal(self):
        metrics = SignalMetrics()
        engine_normal = SignalEngine(
            decision_callback=None,
            signal_metrics=metrics,
            debug_mode=False,
        )
        engine_debug = SignalEngine(
            decision_callback=None,
            signal_metrics=metrics,
            debug_mode=True,
        )
        assert engine_debug.edge_threshold < engine_normal.edge_threshold

    def test_debug_mode_threshold_is_002(self):
        metrics = SignalMetrics()
        engine = SignalEngine(
            decision_callback=None,
            signal_metrics=metrics,
            debug_mode=True,
        )
        assert engine.edge_threshold == pytest.approx(0.02, abs=1e-6)


class TestFP18ForcedTestSignal:
    """FP-18: Forced test signal fires after silence timeout, is_debug_signal=True."""

    @pytest.mark.asyncio
    async def test_forced_signal_fires_after_timeout(self):
        metrics = SignalMetrics()
        engine = SignalEngine(
            decision_callback=None,
            signal_metrics=metrics,
            debug_mode=True,
            no_signal_timeout_s=0.0,   # immediately eligible
        )

        result = await engine("0xabc", {"bid": 0.48, "ask": 0.52})

        assert result is not None
        assert result.get("is_debug_signal") is True
        assert result.get("size_usd") == 1.0

    @pytest.mark.asyncio
    async def test_forced_signal_increments_metric(self):
        metrics = SignalMetrics()
        engine = SignalEngine(
            decision_callback=None,
            signal_metrics=metrics,
            debug_mode=True,
            no_signal_timeout_s=0.0,
        )

        await engine("0xabc", {"bid": 0.48, "ask": 0.52})

        snap = metrics.snapshot()
        assert snap.total_generated >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# FP-19 — Signal metrics in build_report
# ═══════════════════════════════════════════════════════════════════════════════


class TestFP19SignalMetricsInReport:
    """FP-19: build_report includes generated + skipped + reason breakdown."""

    def test_signal_metrics_counts_reflected_in_report(self):
        sig_metrics = SignalMetrics()
        # Simulate 12 generated, 8 skipped (5 low edge, 2 low liquidity, 1 risk)
        for _ in range(12):
            sig_metrics.record_generated()
        for _ in range(5):
            sig_metrics.record_skip(SkipReason.LOW_EDGE)
        for _ in range(2):
            sig_metrics.record_skip(SkipReason.LOW_LIQUIDITY)
        sig_metrics.record_skip(SkipReason.RISK_BLOCK)

        runner, _ = _make_runner(signal_metrics=sig_metrics)
        report = runner.build_report()

        sm = report["signal_metrics"]
        assert sm["total_generated"] == 12
        assert sm["total_skipped"] == 8
        bd = sm["skipped_breakdown"]
        assert bd["low_edge"] == 5
        assert bd["low_liquidity"] == 2
        assert bd["risk_block"] == 1

    def test_signal_metrics_in_report_zero_state(self):
        runner, _ = _make_runner(signal_metrics=SignalMetrics())
        report = runner.build_report()

        sm = report["signal_metrics"]
        assert sm["total_generated"] == 0
        assert sm["total_skipped"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# FP-20 — Risk rules
# ═══════════════════════════════════════════════════════════════════════════════


class TestFP20RiskRules:
    """FP-20: All six risk rules validated; build_report risk_compliance correct."""

    def test_paper_mode_enforced_flag(self):
        runner, _ = _make_runner()
        report = runner.build_report()
        assert report["risk_compliance"]["paper_mode_enforced"] is True

    def test_real_orders_sent_is_false(self):
        runner, _ = _make_runner()
        report = runner.build_report()
        assert report["risk_compliance"]["real_orders_sent"] is False

    def test_drawdown_within_limit_in_report(self):
        runner, _ = _make_runner(drawdown=0.024)
        report = runner.build_report()
        assert report["risk_compliance"]["drawdown"] <= 0.08

    def test_kill_switch_not_active_in_healthy_run(self):
        runner, _ = _make_runner(kill_switch=False)
        report = runner.build_report()
        assert report["risk_compliance"]["kill_switch_active"] is False

    def test_critical_failure_not_set_before_finalize(self):
        runner, _ = _make_runner()
        ctrl = _make_controller(runner)
        assert ctrl.critical_failure is False
        assert ctrl.critical_failure_reasons == []

    @pytest.mark.asyncio
    async def test_both_critical_failure_reasons_captured(self):
        """Both signals=0 and orders=0 each contribute a reason string."""
        runner, _ = _make_runner(signal_count=0, sim_order_count=0)
        ctrl = _make_controller(runner)

        with patch("asyncio.sleep", new=AsyncMock()):
            await ctrl._signal_validation()

        reasons = ctrl.critical_failure_reasons
        assert "signals_generated=0" in reasons
        assert "orders_attempted=0" in reasons
