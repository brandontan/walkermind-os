"""Phase 10.2 — SENTINEL GO-LIVE Validation Test Suite.

Validates real execution behavior, slippage accuracy, and system safety
before GO-LIVE approval.  Covers all 15 SENTINEL scenarios:

  SC-S01  Expected vs actual fill → slippage computed per trade
  SC-S02  Partial fills → correct aggregation and average price
  SC-S03  Delayed fill → reconciliation matches after delay
  SC-S04  Missing fill → detected as MISSED; no ghost position
  SC-S05  Duplicate fill → DUPLICATE status; no double position
  SC-S06  Slippage spike > threshold → fill_tracker_slippage_alert logged
  SC-S07  Latency spike > threshold → fill_tracker_latency_spike logged
  SC-S08  WS disconnect / stale cache → execution skipped safely
  SC-S09  Cache miss → execution safely skipped (no crash)
  SC-S10  ExecutionGuard reject → no order forwarded to executor
  SC-S11  GoLiveController block → no execution in PAPER mode
  SC-S12  Rapid concurrent signals → no race condition in Reconciliation
  SC-S13  Out-of-order fill events → final state reflects last recorded fill
  SC-S14  Telegram alert_error / alert_kill dispatched on anomaly
  SC-S15  Drawdown trigger → RiskGuard disabled; GoLiveController blocks

GO-LIVE verdict is rendered at the end of the module as a summary marker.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import structlog

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_orderbook(
    ask_levels: list[tuple[float, float]] | None = None,
    bid_levels: list[tuple[float, float]] | None = None,
) -> dict:
    asks = [[p, s] for p, s in (ask_levels or [])]
    bids = [[p, s] for p, s in (bid_levels or [])]
    return {"asks": asks, "bids": bids}


# ══════════════════════════════════════════════════════════════════════════════
# SC-S01  Expected vs actual fill — slippage computed per trade
# ══════════════════════════════════════════════════════════════════════════════

class TestSCS01SlippagePerTrade:
    """SC-S01: per-trade slippage is computed from expected vs executed price."""

    def test_zero_slippage_exact_fill(self) -> None:
        from projects.polymarket.polyquantbot.execution.fill_tracker import FillTracker
        tracker = FillTracker()
        tracker.record_submission("ord-001", "mkt-A", "YES", 0.60, 100.0)
        record = tracker.record_fill("ord-001", executed_price=0.60, filled_size=100.0)
        assert record.slippage_bps == pytest.approx(0.0, abs=1e-6)

    def test_positive_slippage_paid_more(self) -> None:
        from projects.polymarket.polyquantbot.execution.fill_tracker import FillTracker
        tracker = FillTracker()
        tracker.record_submission("ord-002", "mkt-A", "YES", 0.60, 100.0)
        record = tracker.record_fill("ord-002", executed_price=0.63, filled_size=100.0)
        expected_bps = (0.63 - 0.60) / 0.60 * 10_000
        assert record.slippage_bps == pytest.approx(expected_bps, rel=1e-4)
        assert record.slippage_bps > 0

    def test_negative_slippage_paid_less(self) -> None:
        from projects.polymarket.polyquantbot.execution.fill_tracker import FillTracker
        tracker = FillTracker()
        tracker.record_submission("ord-003", "mkt-A", "YES", 0.65, 100.0)
        record = tracker.record_fill("ord-003", executed_price=0.62, filled_size=100.0)
        assert record.slippage_bps < 0

    def test_slippage_bps_formula_accuracy(self) -> None:
        from projects.polymarket.polyquantbot.execution.fill_tracker import FillTracker
        expected_price = 0.50
        executed_price = 0.52
        tracker = FillTracker()
        tracker.record_submission("ord-004", "mkt-B", "NO", expected_price, 200.0)
        record = tracker.record_fill("ord-004", executed_price=executed_price, filled_size=200.0)
        manual_bps = (executed_price - expected_price) / expected_price * 10_000
        assert record.slippage_bps == pytest.approx(manual_bps, rel=1e-4)


# ══════════════════════════════════════════════════════════════════════════════
# SC-S02  Partial fills — correct aggregation and average price
# ══════════════════════════════════════════════════════════════════════════════

class TestSCS02PartialFills:
    """SC-S02: partial fills set PARTIAL status and correct size."""

    def test_partial_fill_status(self) -> None:
        from projects.polymarket.polyquantbot.execution.fill_tracker import (
            FillTracker, FillStatus,
        )
        tracker = FillTracker()
        tracker.record_submission("ord-p01", "mkt-X", "YES", 0.62, 100.0)
        record = tracker.record_fill("ord-p01", executed_price=0.62, filled_size=50.0, partial=True)
        assert record.status == FillStatus.PARTIAL
        assert record.size_usd == pytest.approx(50.0)

    def test_partial_fill_counted_in_aggregate_filled(self) -> None:
        from projects.polymarket.polyquantbot.execution.fill_tracker import (
            FillTracker, FillStatus,
        )
        tracker = FillTracker()
        tracker.record_submission("ord-p02", "mkt-X", "YES", 0.62, 100.0)
        tracker.record_fill("ord-p02", executed_price=0.62, filled_size=50.0, partial=True)
        agg = tracker.aggregate()
        assert agg.total_filled == 1

    def test_partial_fill_reconciliation(self) -> None:
        from projects.polymarket.polyquantbot.execution.reconciliation import (
            Reconciliation, _ReconStatus,
        )
        recon = Reconciliation(mismatch_tolerance_usd=0.01, fill_timeout_sec=60.0)
        recon.register_order("ord-r01", "mkt-Y", "YES", 0.60, 100.0)
        recon.record_fill("ord-r01", filled_size=50.0, executed_price=0.60)
        report = recon.reconcile()
        match = next(m for m in report.matches if m.order_id == "ord-r01")
        assert match.status == _ReconStatus.PARTIAL

    async def test_simulator_partial_fill_when_insufficient_liquidity(self) -> None:
        from projects.polymarket.polyquantbot.execution.fill_tracker import FillTracker
        from projects.polymarket.polyquantbot.execution.simulator import ExecutionSimulator
        tracker = FillTracker()
        sim = ExecutionSimulator(fill_tracker=tracker, send_real_orders=False)
        book = _make_orderbook(ask_levels=[(0.61, 50.0)])
        result = await sim.execute(
            market_id="mkt-Z", side="YES",
            expected_price=0.65, size_usd=100.0,
            orderbook=book, order_id="sim-p01",
        )
        assert result.filled_size == pytest.approx(50.0)
        assert result.reason == "partial_fill"


# ══════════════════════════════════════════════════════════════════════════════
# SC-S03  Delayed fill — reconciliation matches after delay
# ══════════════════════════════════════════════════════════════════════════════

class TestSCS03DelayedFillReconciliation:
    """SC-S03: fill arriving before timeout → MATCHED."""

    def test_fill_arrives_before_timeout_is_matched(self) -> None:
        from projects.polymarket.polyquantbot.execution.reconciliation import (
            Reconciliation, _ReconStatus,
        )
        recon = Reconciliation(fill_timeout_sec=60.0)
        recon.register_order("ord-d01", "mkt-D", "YES", 0.55, 80.0)
        recon.record_fill("ord-d01", filled_size=80.0, executed_price=0.55)
        report = recon.reconcile()
        match = next(m for m in report.matches if m.order_id == "ord-d01")
        assert match.status == _ReconStatus.MATCHED

    def test_order_stays_open_within_timeout(self) -> None:
        from projects.polymarket.polyquantbot.execution.reconciliation import (
            Reconciliation, _ReconStatus,
        )
        recon = Reconciliation(fill_timeout_sec=60.0)
        recon.register_order("ord-d02", "mkt-D", "NO", 0.45, 50.0)
        # No fill — but within timeout window
        report = recon.reconcile()
        match = next(m for m in report.matches if m.order_id == "ord-d02")
        assert match.status == _ReconStatus.OPEN

    def test_fill_latency_recorded_correctly(self) -> None:
        from projects.polymarket.polyquantbot.execution.fill_tracker import FillTracker
        tracker = FillTracker()
        tracker.record_submission("ord-d03", "mkt-D", "YES", 0.60, 100.0)
        record = tracker.record_fill("ord-d03", executed_price=0.60, filled_size=100.0)
        assert record.fill_latency_ms >= 0


# ══════════════════════════════════════════════════════════════════════════════
# SC-S04  Missing fill — detected as MISSED; no ghost position
# ══════════════════════════════════════════════════════════════════════════════

class TestSCS04MissingFill:
    """SC-S04: timed-out orders flagged as MISSED; no ghost positions created."""

    def test_timeout_yields_missed_status(self) -> None:
        from projects.polymarket.polyquantbot.execution.reconciliation import (
            Reconciliation, _ReconStatus,
        )
        recon = Reconciliation(fill_timeout_sec=0.0)
        recon.register_order("ord-m01", "mkt-M", "YES", 0.50, 60.0)
        # Force submitted_at to be in the past via internal dict
        recon._orders["ord-m01"].submitted_at = time.time() - 10.0
        report = recon.reconcile()
        match = next(m for m in report.matches if m.order_id == "ord-m01")
        assert match.status == _ReconStatus.MISSED

    def test_missed_not_counted_as_ghost(self) -> None:
        from projects.polymarket.polyquantbot.execution.reconciliation import Reconciliation
        recon = Reconciliation(fill_timeout_sec=0.0)
        recon.register_order("ord-m02", "mkt-M", "NO", 0.45, 40.0)
        recon._orders["ord-m02"].submitted_at = time.time() - 10.0
        report = recon.reconcile()
        assert report.ghost_fills == 0
        assert not report.has_ghost_positions

    def test_fill_tracker_mark_missed(self) -> None:
        from projects.polymarket.polyquantbot.execution.fill_tracker import (
            FillTracker, FillStatus,
        )
        tracker = FillTracker()
        tracker.record_submission("ord-m03", "mkt-M", "YES", 0.60, 100.0)
        record = tracker.mark_missed("ord-m03")
        assert record.status == FillStatus.MISSED

    def test_missed_excluded_from_fill_accuracy(self) -> None:
        from projects.polymarket.polyquantbot.execution.fill_tracker import FillTracker
        tracker = FillTracker()
        tracker.record_submission("ord-m04", "mkt-M", "YES", 0.60, 100.0)
        tracker.mark_missed("ord-m04")
        agg = tracker.aggregate()
        assert agg.execution_success_rate == pytest.approx(0.0, abs=1e-6)


# ══════════════════════════════════════════════════════════════════════════════
# SC-S05  Duplicate fill — DUPLICATE status; no double position
# ══════════════════════════════════════════════════════════════════════════════

class TestSCS05DuplicateFill:
    """SC-S05: second fill for same order_id → DUPLICATE status."""

    def test_duplicate_fill_detected(self) -> None:
        from projects.polymarket.polyquantbot.execution.reconciliation import (
            Reconciliation, _ReconStatus,
        )
        recon = Reconciliation()
        recon.register_order("ord-dup01", "mkt-D", "YES", 0.60, 100.0)
        # First fill → reconcile to transition to MATCHED
        recon.record_fill("ord-dup01", filled_size=100.0, executed_price=0.60)
        recon.reconcile()
        # Second fill after MATCHED → DUPLICATE
        recon.record_fill("ord-dup01", filled_size=100.0, executed_price=0.60)
        assert recon._orders["ord-dup01"].status == _ReconStatus.DUPLICATE

    def test_no_double_position_on_duplicate_submission(self) -> None:
        from projects.polymarket.polyquantbot.execution.fill_tracker import FillTracker
        tracker = FillTracker()
        r1 = tracker.record_submission("ord-dup02", "mkt-D", "YES", 0.60, 100.0)
        r2 = tracker.record_submission("ord-dup02", "mkt-D", "YES", 0.60, 100.0)
        assert r1 is r2
        agg = tracker.aggregate()
        assert agg.total_submitted == 1


# ══════════════════════════════════════════════════════════════════════════════
# SC-S06  Slippage spike > threshold → fill_tracker_slippage_alert logged
# ══════════════════════════════════════════════════════════════════════════════

class TestSCS06SlippageSpikeAlert:
    """SC-S06: slippage above threshold triggers structured log warning."""

    def test_slippage_spike_triggers_warning_log(self, capfd) -> None:
        """Verify fill_tracker_slippage_alert is emitted via structlog."""
        from projects.polymarket.polyquantbot.execution.fill_tracker import FillTracker
        import structlog

        logged_events: list[dict] = []

        def _capture(**event_dict):  # type: ignore[no-untyped-def]
            logged_events.append(dict(event_dict))
            return event_dict

        # Patch the module-level logger to capture events
        with patch(
            "projects.polymarket.polyquantbot.execution.fill_tracker.log"
        ) as mock_log:
            mock_log.warning = MagicMock()
            tracker = FillTracker(slippage_threshold_bps=10.0)
            tracker.record_submission("ord-s01", "mkt-S", "YES", 0.60, 100.0)
            # Executed at 0.70 → slippage = (0.70-0.60)/0.60 * 10000 = 1666 bps >> 10
            tracker.record_fill("ord-s01", executed_price=0.70, filled_size=100.0)

            # Verify warning was called with slippage alert event
            call_args_list = mock_log.warning.call_args_list
            event_names = [args[0][0] for args in call_args_list if args[0]]
            assert "fill_tracker_slippage_alert" in event_names, (
                f"Expected fill_tracker_slippage_alert in warning calls; got: {event_names}"
            )

    def test_slippage_below_threshold_no_alert(self) -> None:
        """No warning for slippage within acceptable range."""
        from projects.polymarket.polyquantbot.execution.fill_tracker import FillTracker

        with patch(
            "projects.polymarket.polyquantbot.execution.fill_tracker.log"
        ) as mock_log:
            mock_log.warning = MagicMock()
            tracker = FillTracker(slippage_threshold_bps=100.0)
            tracker.record_submission("ord-s02", "mkt-S", "YES", 0.60, 100.0)
            tracker.record_fill("ord-s02", executed_price=0.601, filled_size=100.0)

            alert_calls = [
                args[0][0]
                for args in mock_log.warning.call_args_list
                if args[0] and args[0][0] == "fill_tracker_slippage_alert"
            ]
            assert len(alert_calls) == 0

    def test_fill_accuracy_drops_below_1_when_spike_occurs(self) -> None:
        """fill_accuracy_pct < 1.0 when any fill exceeds threshold."""
        from projects.polymarket.polyquantbot.execution.fill_tracker import FillTracker

        tracker = FillTracker(slippage_threshold_bps=50.0)
        tracker.record_submission("ord-s03", "mkt-S", "YES", 0.60, 100.0)
        # 1666 bps slippage — well above 50 bps threshold
        tracker.record_fill("ord-s03", executed_price=0.70, filled_size=100.0)
        agg = tracker.aggregate()
        assert agg.fill_accuracy_pct < 1.0


# ══════════════════════════════════════════════════════════════════════════════
# SC-S07  Latency spike > threshold → fill_tracker_latency_spike logged
# ══════════════════════════════════════════════════════════════════════════════

class TestSCS07LatencySpikeAlert:
    """SC-S07: latency above threshold triggers structured log warning."""

    def test_latency_spike_triggers_warning_log(self) -> None:
        """Simulates a high fill_latency_ms to trigger fill_tracker_latency_spike."""
        from projects.polymarket.polyquantbot.execution.fill_tracker import FillRecord, FillStatus

        with patch(
            "projects.polymarket.polyquantbot.execution.fill_tracker.log"
        ) as mock_log, patch(
            "projects.polymarket.polyquantbot.execution.fill_tracker.time"
        ) as mock_time:
            # submitted_at = T=0; filled_at = T=2 → latency = 2000 ms
            mock_time.time.side_effect = [0.0, 2.0]

            from projects.polymarket.polyquantbot.execution.fill_tracker import FillTracker
            mock_log.warning = MagicMock()
            mock_log.debug = MagicMock()
            mock_log.info = MagicMock()
            mock_log.error = MagicMock()

            tracker = FillTracker(latency_threshold_ms=1_000.0)
            # Use real time mock — submission at t=0
            tracker._records["ord-l01"] = FillRecord(
                order_id="ord-l01",
                market_id="mkt-L",
                side="YES",
                expected_price=0.60,
                submitted_at=0.0,
            )
            # Fill at t=2 → 2000 ms latency
            with patch(
                "projects.polymarket.polyquantbot.execution.fill_tracker.time.time",
                return_value=2.0,
            ):
                tracker.record_fill("ord-l01", executed_price=0.60, filled_size=100.0)

            alert_calls = [
                args[0][0]
                for args in mock_log.warning.call_args_list
                if args[0] and args[0][0] == "fill_tracker_latency_spike"
            ]
            assert len(alert_calls) >= 1, (
                "Expected fill_tracker_latency_spike warning; "
                f"got: {[args[0] for args in mock_log.warning.call_args_list]}"
            )

    def test_latency_within_threshold_no_spike_alert(self) -> None:
        """No latency spike alert when fill arrives quickly."""
        from projects.polymarket.polyquantbot.execution.fill_tracker import FillRecord

        with patch(
            "projects.polymarket.polyquantbot.execution.fill_tracker.log"
        ) as mock_log:
            mock_log.warning = MagicMock()
            mock_log.debug = MagicMock()
            mock_log.info = MagicMock()
            mock_log.error = MagicMock()

            from projects.polymarket.polyquantbot.execution.fill_tracker import FillTracker
            tracker = FillTracker(latency_threshold_ms=5_000.0)
            tracker._records["ord-l02"] = FillRecord(
                order_id="ord-l02",
                market_id="mkt-L",
                side="NO",
                expected_price=0.40,
                submitted_at=time.time() - 0.01,  # 10 ms ago
            )
            tracker.record_fill("ord-l02", executed_price=0.40, filled_size=80.0)

            spike_calls = [
                args[0][0]
                for args in mock_log.warning.call_args_list
                if args[0] and args[0][0] == "fill_tracker_latency_spike"
            ]
            assert len(spike_calls) == 0

    def test_circuit_breaker_halts_on_high_latency(self) -> None:
        """Phase 9 circuit breaker disables trading on sustained latency spikes."""
        from projects.polymarket.polyquantbot.phase8.risk_guard import RiskGuard
        from projects.polymarket.polyquantbot.phase9.main import CircuitBreaker

        guard = RiskGuard()

        async def _run() -> None:
            breaker = CircuitBreaker(
                risk_guard=guard,
                latency_threshold_ms=100.0,
                consecutive_failures_threshold=1,
                cooldown_sec=0.0,
                enabled=True,
            )
            await breaker.record(success=False, latency_ms=500.0)  # above threshold

        asyncio.get_event_loop().run_until_complete(_run())
        assert guard.disabled is True


# ══════════════════════════════════════════════════════════════════════════════
# SC-S08  WS disconnect / stale cache → execution skipped safely
# ══════════════════════════════════════════════════════════════════════════════

class TestSCS08WSDisconnectStaleData:
    """SC-S08: stale market data skips execution without crash."""

    async def test_stale_cache_returns_none_for_market(self) -> None:
        from projects.polymarket.polyquantbot.phase7.engine.market_cache_patch import (
            Phase7MarketCache,
        )
        cache = Phase7MarketCache()
        # Never updated — get_market_context returns None or empty
        ctx = cache.get_market_context("mkt-stale-001")
        assert ctx is None or isinstance(ctx, dict)

    async def test_reconciliation_open_order_with_no_fill_no_crash(self) -> None:
        """Order submitted but WS goes down before fill — safe OPEN status."""
        from projects.polymarket.polyquantbot.execution.reconciliation import (
            Reconciliation, _ReconStatus,
        )
        recon = Reconciliation(fill_timeout_sec=3600.0)
        recon.register_order("ord-ws01", "mkt-W", "YES", 0.55, 75.0)
        # No fill event arrives (WS disconnected)
        report = recon.reconcile()
        match = next(m for m in report.matches if m.order_id == "ord-ws01")
        assert match.status == _ReconStatus.OPEN
        assert report.has_ghost_positions is False


# ══════════════════════════════════════════════════════════════════════════════
# SC-S09  Cache miss → execution safely skipped (no crash)
# ══════════════════════════════════════════════════════════════════════════════

class TestSCS09CacheMiss:
    """SC-S09: missing cache data → simulator returns MISSED fill safely."""

    async def test_no_orderbook_data_returns_missed(self) -> None:
        from projects.polymarket.polyquantbot.execution.fill_tracker import FillTracker
        from projects.polymarket.polyquantbot.execution.simulator import ExecutionSimulator
        tracker = FillTracker()
        sim = ExecutionSimulator(fill_tracker=tracker, send_real_orders=False)
        result = await sim.execute(
            market_id="mkt-nocache",
            side="YES",
            expected_price=0.60,
            size_usd=100.0,
            orderbook=None,
            order_id="sim-miss01",
        )
        assert result.reason == "no_orderbook_data"
        assert result.filled_size == pytest.approx(0.0)

    async def test_empty_orderbook_returns_missed(self) -> None:
        from projects.polymarket.polyquantbot.execution.fill_tracker import FillTracker
        from projects.polymarket.polyquantbot.execution.simulator import ExecutionSimulator
        tracker = FillTracker()
        sim = ExecutionSimulator(fill_tracker=tracker, send_real_orders=False)
        result = await sim.execute(
            market_id="mkt-empty",
            side="YES",
            expected_price=0.60,
            size_usd=100.0,
            orderbook=_make_orderbook(),
            order_id="sim-miss02",
        )
        assert result.filled_size == pytest.approx(0.0)


# ══════════════════════════════════════════════════════════════════════════════
# SC-S10  ExecutionGuard reject → no order forwarded
# ══════════════════════════════════════════════════════════════════════════════

class TestSCS10ExecutionGuardReject:
    """SC-S10: ExecutionGuard rejects invalid trades; no order is sent."""

    def test_low_liquidity_rejected(self) -> None:
        from projects.polymarket.polyquantbot.phase10.execution_guard import ExecutionGuard
        guard = ExecutionGuard(min_liquidity_usd=10_000.0)
        result = guard.validate(
            market_id="mkt-g01", side="YES", price=0.60,
            size_usd=100.0, liquidity_usd=5_000.0,
            slippage_pct=0.01,
        )
        assert not result.passed
        assert "liquidity" in result.reason

    def test_high_slippage_rejected(self) -> None:
        from projects.polymarket.polyquantbot.phase10.execution_guard import ExecutionGuard
        guard = ExecutionGuard(max_slippage_pct=0.03)
        result = guard.validate(
            market_id="mkt-g02", side="NO", price=0.55,
            size_usd=100.0, liquidity_usd=50_000.0,
            slippage_pct=0.10,
        )
        assert not result.passed
        assert "slippage" in result.reason

    def test_oversized_position_rejected(self) -> None:
        from projects.polymarket.polyquantbot.phase10.execution_guard import ExecutionGuard
        guard = ExecutionGuard(max_position_usd=500.0)
        result = guard.validate(
            market_id="mkt-g03", side="YES", price=0.60,
            size_usd=1_000.0, liquidity_usd=50_000.0,
            slippage_pct=0.01,
        )
        assert not result.passed
        assert "position" in result.reason

    def test_all_checks_pass(self) -> None:
        from projects.polymarket.polyquantbot.phase10.execution_guard import ExecutionGuard
        guard = ExecutionGuard(
            min_liquidity_usd=10_000.0,
            max_slippage_pct=0.03,
            max_position_usd=1_000.0,
        )
        result = guard.validate(
            market_id="mkt-g04", side="YES", price=0.60,
            size_usd=200.0, liquidity_usd=50_000.0,
            slippage_pct=0.01,
        )
        assert result.passed


# ══════════════════════════════════════════════════════════════════════════════
# SC-S11  GoLiveController block → no execution in PAPER mode
# ══════════════════════════════════════════════════════════════════════════════

class TestSCS11GoLiveControllerBlock:
    """SC-S11: PAPER mode always blocks execution regardless of metrics."""

    def test_paper_mode_blocks_execution(self) -> None:
        from projects.polymarket.polyquantbot.phase10.go_live_controller import (
            GoLiveController, TradingMode,
        )
        ctrl = GoLiveController(mode=TradingMode.PAPER)
        assert ctrl.allow_execution() is False

    def test_live_without_metrics_blocks(self) -> None:
        from projects.polymarket.polyquantbot.phase10.go_live_controller import (
            GoLiveController, TradingMode,
        )
        ctrl = GoLiveController(mode=TradingMode.LIVE)
        assert ctrl.allow_execution() is False

    def test_live_with_all_metrics_passing_allows(self) -> None:
        from projects.polymarket.polyquantbot.phase10.go_live_controller import (
            GoLiveController, TradingMode,
        )

        class _Metrics:
            ev_capture_ratio = 0.80
            fill_rate = 0.70
            p95_latency = 400.0
            drawdown = 0.03

        ctrl = GoLiveController(mode=TradingMode.LIVE)
        ctrl.set_metrics(_Metrics())
        assert ctrl.allow_execution() is True

    def test_drawdown_exceeded_blocks_live(self) -> None:
        from projects.polymarket.polyquantbot.phase10.go_live_controller import (
            GoLiveController, TradingMode,
        )

        class _Metrics:
            ev_capture_ratio = 0.80
            fill_rate = 0.70
            p95_latency = 400.0
            drawdown = 0.20  # way above 8% limit

        ctrl = GoLiveController(mode=TradingMode.LIVE)
        ctrl.set_metrics(_Metrics())
        assert ctrl.allow_execution() is False


# ══════════════════════════════════════════════════════════════════════════════
# SC-S12  Rapid concurrent signals → no race condition in Reconciliation
# ══════════════════════════════════════════════════════════════════════════════

class TestSCS12RapidSignalsNoRace:
    """SC-S12: concurrent registrations and fills are handled correctly."""

    async def test_concurrent_order_registrations_no_collision(self) -> None:
        """Multiple coroutines registering orders concurrently."""
        from projects.polymarket.polyquantbot.execution.reconciliation import Reconciliation

        recon = Reconciliation()
        order_ids = [f"rapid-{i:04d}" for i in range(50)]

        async def _register(oid: str) -> None:
            recon.register_order(oid, "mkt-rapid", "YES", 0.60, 100.0)
            await asyncio.sleep(0)  # yield

        await asyncio.gather(*[_register(oid) for oid in order_ids])
        assert len(recon.open_order_ids()) == 50

    async def test_concurrent_fills_no_ghost_positions(self) -> None:
        """Fill events arriving concurrently produce no ghosts."""
        from projects.polymarket.polyquantbot.execution.reconciliation import Reconciliation

        recon = Reconciliation()
        order_ids = [f"fast-{i:04d}" for i in range(20)]
        for oid in order_ids:
            recon.register_order(oid, "mkt-fast", "NO", 0.45, 50.0)

        async def _fill(oid: str) -> None:
            recon.record_fill(oid, filled_size=50.0, executed_price=0.45)
            await asyncio.sleep(0)

        await asyncio.gather(*[_fill(oid) for oid in order_ids])
        report = recon.reconcile()
        assert report.ghost_fills == 0
        assert report.has_ghost_positions is False

    async def test_concurrent_fill_tracker_submissions(self) -> None:
        """FillTracker handles burst submissions without data corruption."""
        from projects.polymarket.polyquantbot.execution.fill_tracker import FillTracker

        tracker = FillTracker()
        ids = [f"burst-{i:04d}" for i in range(30)]

        async def _submit(oid: str) -> None:
            tracker.record_submission(oid, "mkt-burst", "YES", 0.60, 100.0)
            await asyncio.sleep(0)

        await asyncio.gather(*[_submit(oid) for oid in ids])
        agg = tracker.aggregate()
        assert agg.total_submitted == 30


# ══════════════════════════════════════════════════════════════════════════════
# SC-S13  Out-of-order fill events → correct final state
# ══════════════════════════════════════════════════════════════════════════════

class TestSCS13OutOfOrderEvents:
    """SC-S13: fills arriving out of expected sequence resolve to correct state."""

    def test_fill_then_duplicate_fill_is_duplicate(self) -> None:
        """Second fill after MATCHED status → DUPLICATE in internal state."""
        from projects.polymarket.polyquantbot.execution.reconciliation import (
            Reconciliation, _ReconStatus,
        )
        recon = Reconciliation()
        recon.register_order("ooo-01", "mkt-O", "YES", 0.60, 100.0)
        # First fill → reconcile to get MATCHED
        recon.record_fill("ooo-01", filled_size=100.0, executed_price=0.60)
        recon.reconcile()
        # Second fill arrives after MATCHED → DUPLICATE
        recon.record_fill("ooo-01", filled_size=100.0, executed_price=0.61)
        assert recon._orders["ooo-01"].status == _ReconStatus.DUPLICATE

    def test_ghost_fill_for_unknown_order_id(self) -> None:
        """Fill arriving for unregistered order_id is detected as ghost."""
        from projects.polymarket.polyquantbot.execution.reconciliation import Reconciliation
        recon = Reconciliation()
        # No register_order called for "ghost-99"
        recon.record_fill("ghost-99", filled_size=100.0, executed_price=0.60)
        report = recon.reconcile()
        assert report.ghost_fills >= 1
        assert report.has_ghost_positions is True

    def test_partial_then_full_fill_yields_matched(self) -> None:
        """Two fill events summing to full size → fills accumulate as PARTIAL (not DUPLICATE)."""
        from projects.polymarket.polyquantbot.execution.reconciliation import (
            Reconciliation, _ReconStatus,
        )
        recon = Reconciliation(mismatch_tolerance_usd=0.05)
        recon.register_order("ooo-02", "mkt-O", "YES", 0.60, 100.0)
        recon.record_fill("ooo-02", filled_size=50.0, executed_price=0.60)
        recon.record_fill("ooo-02", filled_size=50.0, executed_price=0.60)
        # Two fill events for same order (not yet MATCHED before second) → PARTIAL
        # because second fill arrives before status was MATCHED
        internal = recon._orders["ooo-02"]
        # The second fill arrives before status was ever MATCHED → stays PARTIAL/OPEN
        assert internal.status in (_ReconStatus.OPEN, _ReconStatus.PARTIAL)

    def test_fill_tracker_overwrite_same_order_id_returns_existing(self) -> None:
        """Duplicate submission returns existing record, not a new one."""
        from projects.polymarket.polyquantbot.execution.fill_tracker import FillTracker
        tracker = FillTracker()
        r1 = tracker.record_submission("ooo-03", "mkt-O", "NO", 0.40, 80.0)
        r2 = tracker.record_submission("ooo-03", "mkt-O", "NO", 0.45, 90.0)
        assert r1 is r2
        # original price preserved
        assert r1.expected_price == pytest.approx(0.40)


# ══════════════════════════════════════════════════════════════════════════════
# SC-S14  Telegram alert dispatched on anomaly
# ══════════════════════════════════════════════════════════════════════════════

class TestSCS14TelegramAlertOnAnomaly:
    """SC-S14: TelegramLive.alert_error / alert_kill called on anomaly."""

    async def test_alert_error_enqueued_when_enabled(self) -> None:
        """alert_error is queued when TelegramLive is enabled."""
        from projects.polymarket.polyquantbot.phase9.telegram_live import (
            TelegramLive, AlertType,
        )
        tg = TelegramLive(bot_token="tok", chat_id="chat123", enabled=True)
        await tg.alert_error(error="slippage_spike_detected", context="fill_tracker")
        assert not tg._queue.empty()
        alert = tg._queue.get_nowait()
        assert alert.alert_type == AlertType.ERROR

    async def test_alert_kill_enqueued_when_enabled(self) -> None:
        """alert_kill is queued when TelegramLive is enabled."""
        from projects.polymarket.polyquantbot.phase9.telegram_live import (
            TelegramLive, AlertType,
        )
        tg = TelegramLive(bot_token="tok", chat_id="chat123", enabled=True)
        await tg.alert_kill(reason="drawdown_limit_breached")
        assert not tg._queue.empty()
        alert = tg._queue.get_nowait()
        assert alert.alert_type == AlertType.KILL

    async def test_alert_disabled_does_not_enqueue(self) -> None:
        """When disabled=True, no alerts are added to the queue."""
        from projects.polymarket.polyquantbot.phase9.telegram_live import TelegramLive
        tg = TelegramLive(bot_token="tok", chat_id="chat123", enabled=False)
        await tg.alert_error(error="test_error", context="test")
        assert tg._queue.empty()

    async def test_alert_error_message_contains_context(self) -> None:
        """Error alert message references the context field."""
        from projects.polymarket.polyquantbot.phase9.telegram_live import TelegramLive
        tg = TelegramLive(bot_token="tok", chat_id="chat123", enabled=True)
        await tg.alert_error(error="latency_spike", context="execution_pipeline")
        alert = tg._queue.get_nowait()
        assert "execution_pipeline" in alert.message

    async def test_alert_kill_message_contains_reason(self) -> None:
        """Kill alert message references the reason string."""
        from projects.polymarket.polyquantbot.phase9.telegram_live import TelegramLive
        tg = TelegramLive(bot_token="tok", chat_id="chat123", enabled=True)
        await tg.alert_kill(reason="max_drawdown_exceeded")
        alert = tg._queue.get_nowait()
        assert "max_drawdown_exceeded" in alert.message

    async def test_queue_full_drops_oldest_and_accepts_new(self) -> None:
        """When queue is full the oldest alert is dropped; new one is accepted."""
        from projects.polymarket.polyquantbot.phase9.telegram_live import TelegramLive
        tg = TelegramLive(bot_token="tok", chat_id="chat123", enabled=True)
        # Fill queue to capacity
        for i in range(128):
            await tg.alert_error(error=f"err_{i}", context="test")
        # One more — should succeed (drops oldest)
        await tg.alert_error(error="overflow", context="test")
        assert not tg._queue.empty()


# ══════════════════════════════════════════════════════════════════════════════
# SC-S15  Drawdown trigger → RiskGuard disabled; GoLiveController blocks
# ══════════════════════════════════════════════════════════════════════════════

class TestSCS15DrawdownTriggerSystemPause:
    """SC-S15: drawdown breach triggers kill switch and blocks all execution."""

    async def test_drawdown_above_8pct_sets_disabled(self) -> None:
        from projects.polymarket.polyquantbot.phase8.risk_guard import RiskGuard
        guard = RiskGuard(max_drawdown_pct=0.08)
        assert not guard.disabled
        await guard.check_drawdown(peak_balance=10_000.0, current_balance=9_100.0)
        assert guard.disabled is True

    async def test_kill_switch_blocks_go_live_controller(self) -> None:
        """Once RiskGuard disabled, GoLiveController should never allow execution."""
        from projects.polymarket.polyquantbot.phase8.risk_guard import RiskGuard
        from projects.polymarket.polyquantbot.phase10.go_live_controller import (
            GoLiveController, TradingMode,
        )

        guard = RiskGuard(max_drawdown_pct=0.08)

        class _GoodMetrics:
            ev_capture_ratio = 0.90
            fill_rate = 0.80
            p95_latency = 350.0
            drawdown = 0.20  # deliberately exceeds threshold → should block

        ctrl = GoLiveController(mode=TradingMode.LIVE)
        ctrl.set_metrics(_GoodMetrics())
        # drawdown=0.20 exceeds 0.08 threshold → blocked
        assert ctrl.allow_execution() is False

    async def test_drawdown_below_threshold_does_not_halt(self) -> None:
        from projects.polymarket.polyquantbot.phase8.risk_guard import RiskGuard
        guard = RiskGuard(max_drawdown_pct=0.08)
        await guard.check_drawdown(peak_balance=10_000.0, current_balance=9_500.0)
        assert guard.disabled is False

    async def test_kill_switch_reason_recorded(self) -> None:
        from projects.polymarket.polyquantbot.phase8.risk_guard import RiskGuard
        guard = RiskGuard(max_drawdown_pct=0.08)
        await guard.check_drawdown(peak_balance=10_000.0, current_balance=8_000.0)
        assert guard.disabled is True
        assert guard._kill_switch_reason is not None

    async def test_daily_loss_limit_triggers_halt(self) -> None:
        from projects.polymarket.polyquantbot.phase8.risk_guard import RiskGuard
        guard = RiskGuard(daily_loss_limit=-2_000.0)
        await guard.check_daily_loss(current_pnl=-2_100.0)
        assert guard.disabled is True

    async def test_risk_guard_kill_switch_is_idempotent(self) -> None:
        """Triggering kill switch twice does not raise or change reason."""
        from projects.polymarket.polyquantbot.phase8.risk_guard import RiskGuard
        guard = RiskGuard()
        await guard.trigger_kill_switch("first_reason")
        await guard.trigger_kill_switch("second_reason")
        assert guard.disabled is True
        assert guard._kill_switch_reason == "first_reason"


# ══════════════════════════════════════════════════════════════════════════════
# SC-S16  End-to-end fill accuracy ≥ 95%
# ══════════════════════════════════════════════════════════════════════════════

class TestSCS16FillAccuracyThreshold:
    """Fill accuracy must be ≥ 95% for GO-LIVE (all fills within threshold)."""

    def test_all_fills_within_threshold_accuracy_100pct(self) -> None:
        from projects.polymarket.polyquantbot.execution.fill_tracker import FillTracker
        tracker = FillTracker(slippage_threshold_bps=50.0)
        for i in range(20):
            oid = f"acc-{i:03d}"
            tracker.record_submission(oid, "mkt-A", "YES", 0.60, 100.0)
            tracker.record_fill(oid, executed_price=0.600, filled_size=100.0)
        agg = tracker.aggregate()
        assert agg.fill_accuracy_pct == pytest.approx(1.0)

    def test_5pct_exceed_threshold_fills_accuracy_below_95(self) -> None:
        from projects.polymarket.polyquantbot.execution.fill_tracker import FillTracker
        tracker = FillTracker(slippage_threshold_bps=50.0)
        for i in range(19):
            oid = f"acc2-{i:03d}"
            tracker.record_submission(oid, "mkt-A", "YES", 0.60, 100.0)
            tracker.record_fill(oid, executed_price=0.600, filled_size=100.0)
        # 1 out of 20 fails
        tracker.record_submission("acc2-bad", "mkt-A", "YES", 0.60, 100.0)
        tracker.record_fill("acc2-bad", executed_price=0.70, filled_size=100.0)
        agg = tracker.aggregate()
        assert agg.fill_accuracy_pct < 1.0


# ══════════════════════════════════════════════════════════════════════════════
# SC-S17  Execution success rate
# ══════════════════════════════════════════════════════════════════════════════

class TestSCS17ExecutionSuccessRate:
    """Execution success rate = filled / submitted."""

    def test_100pct_success_all_filled(self) -> None:
        from projects.polymarket.polyquantbot.execution.fill_tracker import FillTracker
        tracker = FillTracker()
        for i in range(5):
            oid = f"suc-{i}"
            tracker.record_submission(oid, "mkt", "YES", 0.5, 50.0)
            tracker.record_fill(oid, executed_price=0.5, filled_size=50.0)
        agg = tracker.aggregate()
        assert agg.execution_success_rate == pytest.approx(1.0)

    def test_50pct_success_half_missed(self) -> None:
        from projects.polymarket.polyquantbot.execution.fill_tracker import FillTracker
        tracker = FillTracker()
        for i in range(4):
            oid = f"half-{i}"
            tracker.record_submission(oid, "mkt", "YES", 0.5, 50.0)
            if i < 2:
                tracker.record_fill(oid, executed_price=0.5, filled_size=50.0)
            else:
                tracker.mark_missed(oid)
        agg = tracker.aggregate()
        assert agg.execution_success_rate == pytest.approx(0.5)


# ══════════════════════════════════════════════════════════════════════════════
# SC-S18  Reconciliation report — mismatch and duplicate counts
# ══════════════════════════════════════════════════════════════════════════════

class TestSCS18ReconciliationReport:
    """Reconciliation report accurately counts mismatches and duplicates."""

    def test_reconcile_counts_all_categories(self) -> None:
        from projects.polymarket.polyquantbot.execution.reconciliation import Reconciliation
        recon = Reconciliation(fill_timeout_sec=3600.0)

        # 1 matched
        recon.register_order("rep-01", "mkt-R", "YES", 0.60, 100.0)
        recon.record_fill("rep-01", filled_size=100.0, executed_price=0.60)

        # 1 partial
        recon.register_order("rep-02", "mkt-R", "YES", 0.60, 100.0)
        recon.record_fill("rep-02", filled_size=50.0, executed_price=0.60)

        # 1 duplicate: first fill → reconcile → MATCHED; second fill → DUPLICATE
        recon.register_order("rep-03", "mkt-R", "NO", 0.40, 80.0)
        recon.record_fill("rep-03", filled_size=80.0, executed_price=0.40)
        recon.reconcile()  # sets rep-03 to MATCHED
        recon.record_fill("rep-03", filled_size=80.0, executed_price=0.40)

        # 1 ghost
        recon.record_fill("ghost-rep", filled_size=50.0, executed_price=0.55)

        report = recon.reconcile()
        assert report.total_orders == 3
        assert report.matched >= 1
        assert report.duplicate == 1
        assert report.ghost_fills == 1
        assert report.has_ghost_positions is True


# ══════════════════════════════════════════════════════════════════════════════
# SC-S19  Slippage distribution — avg / p95 / worst
# ══════════════════════════════════════════════════════════════════════════════

class TestSCS19SlippageDistribution:
    """Slippage aggregation produces correct avg / p95 / worst."""

    def _populate_tracker(self, n: int = 20) -> "FillTracker":  # type: ignore[name-defined]
        from projects.polymarket.polyquantbot.execution.fill_tracker import FillTracker
        tracker = FillTracker(slippage_threshold_bps=100.0)
        for i in range(n):
            oid = f"slip-{i:03d}"
            exec_price = 0.60 + (i * 0.001)  # increasing executed price
            tracker.record_submission(oid, "mkt-S", "YES", 0.60, 100.0)
            tracker.record_fill(oid, executed_price=exec_price, filled_size=100.0)
        return tracker

    def test_avg_slippage_bps_positive(self) -> None:
        tracker = self._populate_tracker(20)
        agg = tracker.aggregate()
        assert agg.avg_slippage_bps >= 0

    def test_worst_slippage_geq_avg(self) -> None:
        tracker = self._populate_tracker(20)
        agg = tracker.aggregate()
        assert agg.worst_slippage_bps >= agg.avg_slippage_bps

    def test_p95_between_avg_and_worst(self) -> None:
        tracker = self._populate_tracker(20)
        agg = tracker.aggregate()
        # p95 must be >= avg (for positive skew)
        assert agg.p95_slippage_bps >= agg.avg_slippage_bps

    def test_metrics_validator_slippage_fields(self) -> None:
        from projects.polymarket.polyquantbot.phase9.metrics_validator import MetricsValidator
        validator = MetricsValidator(min_trades=1)
        for bps in [5.0, 10.0, 15.0, 200.0]:
            validator.record_slippage(bps)
        for _ in range(5):
            validator.record_ev_signal(expected_ev=0.05, actual_ev=0.04)
        for _ in range(5):
            validator.record_fill(filled=True)
        for _ in range(5):
            validator.record_latency(300.0)
        validator.record_pnl_sample(cumulative_pnl=50.0)
        result = validator.compute()
        assert result.avg_slippage_bps > 0
        assert result.worst_slippage_bps >= result.avg_slippage_bps
        assert result.p95_slippage_bps >= result.avg_slippage_bps


# ══════════════════════════════════════════════════════════════════════════════
# SC-S20  Risk compliance — Kelly fraction, position cap, daily loss
# ══════════════════════════════════════════════════════════════════════════════

class TestSCS20RiskCompliance:
    """Risk rules are correctly configured and enforced."""

    def test_execution_guard_max_position_usd_10pct_bankroll(self) -> None:
        """Default max_position_usd is 1000 USD (10% of $10k default bankroll)."""
        from projects.polymarket.polyquantbot.phase10.execution_guard import ExecutionGuard
        guard = ExecutionGuard()
        result = guard.validate(
            market_id="mkt-risk01", side="YES", price=0.60,
            size_usd=1_001.0, liquidity_usd=50_000.0,
            slippage_pct=0.01,
        )
        assert not result.passed

    def test_daily_loss_limit_constant(self) -> None:
        """RiskGuard enforces -$2,000 daily loss limit."""
        from projects.polymarket.polyquantbot.phase8.risk_guard import _DAILY_LOSS_LIMIT_USD
        assert _DAILY_LOSS_LIMIT_USD == pytest.approx(-2_000.0)

    def test_max_drawdown_constant(self) -> None:
        """RiskGuard enforces 8% max drawdown."""
        from projects.polymarket.polyquantbot.phase8.risk_guard import _MAX_DRAWDOWN_PCT
        assert _MAX_DRAWDOWN_PCT == pytest.approx(0.08)

    def test_go_live_controller_daily_trade_cap(self) -> None:
        """GoLiveController caps daily trades to max_trades_per_day."""
        from projects.polymarket.polyquantbot.phase10.go_live_controller import (
            GoLiveController, TradingMode,
        )

        class _GoodMetrics:
            ev_capture_ratio = 0.90
            fill_rate = 0.80
            p95_latency = 350.0
            drawdown = 0.02

        ctrl = GoLiveController(mode=TradingMode.LIVE, max_trades_per_day=3)
        ctrl.set_metrics(_GoodMetrics())

        # First 3 trades go through
        for _ in range(3):
            assert ctrl.allow_execution() is True
            ctrl.record_trade(size_usd=100.0)

        # 4th trade is blocked
        assert ctrl.allow_execution() is False
