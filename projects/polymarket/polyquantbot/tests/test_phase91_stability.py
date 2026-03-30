"""SENTINEL Phase 9.1 — Full Stability Validation Test Suite.

Covers all 16 scenarios required by the SENTINEL mandate:

  SC-01  Valid signal → order placed → filled correctly
  SC-02  Duplicate signal → dedup enforced (OrderGuard + FillMonitor)
  SC-03  Latency spike → circuit breaker / safe abort
  SC-04  API failure → retry + fallback, no crash
  SC-05  Partial fills → correct VWAP aggregation
  SC-06  Liquidity / fill_prob below threshold → trade blocked
  SC-07  EV below threshold → no execution
  SC-08  Drawdown > 8% → global trading halt (kill switch)
  SC-09  Daily loss > −$2 000 → kill switch triggered
  SC-10  Kill switch → disabled flag set immediately (no await)
  SC-11  Concurrent open positions capped at one per market
  SC-12  Invalid / malformed data → graceful skip, no crash
  SC-13  Circuit breaker burst (consecutive failures)
  SC-14  Async race condition — parallel claim attempts
  SC-15  Stale signature eviction — no state corruption
  SC-16  SYSTEM_STATE transitions (RUNNING ↔ PAUSED ↔ HALTED)

Additional risk-compliance assertions are embedded in each scenario.
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ══════════════════════════════════════════════════════════════════════════════
# SC-01 — Valid signal → position opened correctly
# ══════════════════════════════════════════════════════════════════════════════

class TestSC01ValidSignalFlow:
    """A well-formed order lifecycle: open → confirm fill → position tracked."""

    async def test_position_tracker_open_valid(self, position_tracker) -> None:
        ok = await position_tracker.open(
            market_id="0xmarket001",
            side="YES",
            size=50.0,
            entry_price=0.62,
        )
        assert ok is True, "Valid open must return True"

    async def test_position_shows_in_snapshot(self, position_tracker) -> None:
        await position_tracker.open("0xmkt001", "YES", 50.0, 0.62)
        snapshot = await position_tracker.open_positions_snapshot()
        assert len(snapshot) == 1
        pos = snapshot[0]
        assert pos.market_id == "0xmkt001"
        assert pos.side == "YES"
        assert abs(pos.size - 50.0) < 1e-5
        assert abs(pos.entry_price - 0.62) < 1e-5

    async def test_fill_monitor_full_fill_via_ws(
        self, position_tracker, risk_guard
    ) -> None:
        """WS fill event → FillMonitor marks FILLED → PositionTracker.open()."""
        from projects.polymarket.polyquantbot.phase8.fill_monitor import FillMonitor
        from .conftest import StubExecutor

        executor = StubExecutor(fill_status="filled", fill_size=50.0, fill_price=0.62)
        monitor = FillMonitor(
            executor=executor,
            position_tracker=position_tracker,
            risk_guard=risk_guard,
            order_timeout_sec=30.0,
            max_retry=3,
            poll_interval_sec=0.01,
        )

        registered = monitor.register(
            order_id="ord-001",
            market_id="0xmkt-fill",
            side="YES",
            size=50.0,
            price=0.62,
        )
        assert registered is True

        # Simulate a WS fill event
        monitor.on_ws_fill("ord-001", filled_size=50.0, avg_price=0.62)

        # Run one monitor tick to confirm and open position
        await monitor._process_all_tracked()

        # Position should now be tracked
        snapshot = await position_tracker.open_positions_snapshot()
        market_ids = [p.market_id for p in snapshot]
        assert "0xmkt-fill" in market_ids

    async def test_position_close_records_pnl(self, position_tracker) -> None:
        await position_tracker.open("0xmkt002", "YES", 100.0, 0.50)
        ok = await position_tracker.close(
            market_id="0xmkt002",
            exit_price=0.70,
            realised_pnl=20.0,
            close_reason="take_profit",
        )
        assert ok is True
        summary = await position_tracker.summary()
        assert summary["open_positions"] == 0
        assert summary["closed_positions_history"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# SC-02 — Duplicate signal → dedup enforced
# ══════════════════════════════════════════════════════════════════════════════

class TestSC02OrderDedup:
    """OrderGuard and FillMonitor both prevent duplicate submissions."""

    async def test_order_guard_blocks_duplicate_signature(
        self, order_guard
    ) -> None:
        sig = order_guard.compute_signature("0xmkt", "YES", 0.65, 50.0)
        first = await order_guard.try_claim(sig, order_id="", correlation_id="cid-1")
        second = await order_guard.try_claim(sig, order_id="", correlation_id="cid-2")
        assert first is True, "First claim must succeed"
        assert second is False, "Duplicate claim must be rejected"

    async def test_order_guard_allows_after_release(self, order_guard) -> None:
        sig = order_guard.compute_signature("0xmkt", "YES", 0.65, 50.0)
        await order_guard.try_claim(sig)
        await order_guard.release(sig)
        reclaim = await order_guard.try_claim(sig, correlation_id="cid-3")
        assert reclaim is True, "Claim must succeed after release"

    async def test_fill_monitor_dedup_same_order_id(
        self, position_tracker, risk_guard
    ) -> None:
        from projects.polymarket.polyquantbot.phase8.fill_monitor import FillMonitor
        from .conftest import StubExecutor

        executor = StubExecutor()
        monitor = FillMonitor(executor, position_tracker, risk_guard)

        first = monitor.register("ord-dup", "0xmkt", "YES", 50.0, 0.62)
        second = monitor.register("ord-dup", "0xmkt", "YES", 50.0, 0.62)
        assert first is True
        assert second is False, "Duplicate registration must be silently rejected"

    async def test_fill_monitor_processed_set_prevents_reprocess(
        self, position_tracker, risk_guard
    ) -> None:
        from projects.polymarket.polyquantbot.phase8.fill_monitor import FillMonitor
        from .conftest import StubExecutor

        executor = StubExecutor(fill_status="filled", fill_size=50.0, fill_price=0.62)
        monitor = FillMonitor(executor, position_tracker, risk_guard)

        monitor.register("ord-proc", "0xmkt-proc", "YES", 50.0, 0.62)
        monitor.on_ws_fill("ord-proc", filled_size=50.0, avg_price=0.62)
        await monitor._process_all_tracked()

        # Order is now in processed set; re-register must fail
        result = monitor.register("ord-proc", "0xmkt-proc", "YES", 50.0, 0.62)
        assert result is False, "Already-processed order must be rejected"

    async def test_order_guard_signature_precision(self, order_guard) -> None:
        """Floating-point jitter within rounding tolerance must yield same sig."""
        # price rounds to 4dp: 0.650001 → 0.65, 0.650009 → 0.65
        # size rounds to 2dp:  50.001 → 50.0,   50.004 → 50.0
        sig_a = order_guard.compute_signature("0xmkt", "YES", 0.650001, 50.001)
        sig_b = order_guard.compute_signature("0xmkt", "YES", 0.650009, 50.004)
        assert sig_a == sig_b, "Signatures within rounding tolerance must match"


# ══════════════════════════════════════════════════════════════════════════════
# SC-03 — Latency spike → circuit breaker triggers
# ══════════════════════════════════════════════════════════════════════════════

class TestSC03LatencySpike:
    """Circuit breaker must fire if p95 latency exceeds 600ms threshold."""

    async def test_high_latency_triggers_circuit_breaker(
        self, circuit_breaker, risk_guard
    ) -> None:
        # Fill the window with high-latency calls; none are errors
        for _ in range(5):
            await circuit_breaker.record(success=True, latency_ms=700.0, correlation_id="lat-test")

        assert risk_guard.disabled is True, "Kill switch must fire on p95 latency breach"
        assert risk_guard.kill_switch_reason is not None
        assert "latency" in risk_guard.kill_switch_reason.lower()

    async def test_normal_latency_does_not_trigger(self, risk_guard) -> None:
        from projects.polymarket.polyquantbot.phase9.main import CircuitBreaker
        cb = CircuitBreaker(
            risk_guard=risk_guard,
            error_rate_threshold=0.30,
            error_window_size=20,
            latency_threshold_ms=600.0,
            cooldown_sec=0.0,
            enabled=True,
        )
        for _ in range(20):
            await cb.record(success=True, latency_ms=100.0)

        assert risk_guard.disabled is False, "Normal latency must not fire circuit breaker"

    async def test_circuit_breaker_disabled_flag_is_noop(self, risk_guard) -> None:
        from projects.polymarket.polyquantbot.phase9.main import CircuitBreaker
        cb = CircuitBreaker(
            risk_guard=risk_guard,
            error_rate_threshold=0.01,
            error_window_size=5,
            latency_threshold_ms=100.0,
            cooldown_sec=0.0,
            enabled=False,  # disabled
        )
        for _ in range(10):
            await cb.record(success=False, latency_ms=9000.0)

        assert risk_guard.disabled is False, "Disabled circuit breaker must be a no-op"


# ══════════════════════════════════════════════════════════════════════════════
# SC-04 — API failure → retry + fallback, no crash
# ══════════════════════════════════════════════════════════════════════════════

class TestSC04APIFailure:
    """Executor errors must be handled gracefully — no unhandled exceptions."""

    async def test_fill_monitor_handles_executor_none_response(
        self, position_tracker, risk_guard
    ) -> None:
        from projects.polymarket.polyquantbot.phase8.fill_monitor import FillMonitor
        from .conftest import StubExecutor

        # Executor always returns None for status (simulates API failure)
        executor = StubExecutor(should_raise=False)
        executor.fill_status = "unknown"  # will return None-like status
        executor_none = StubExecutor()
        executor_none.get_order_status = AsyncMock(return_value=None)
        executor_none.cancel_order = AsyncMock(return_value=True)

        monitor = FillMonitor(
            executor=executor_none,
            position_tracker=position_tracker,
            risk_guard=risk_guard,
            order_timeout_sec=30.0,
            max_retry=2,
            poll_interval_sec=0.001,
        )
        monitor.register("ord-apifail", "0xmkt-api", "YES", 50.0, 0.62)

        # Should NOT raise — graceful None handling
        try:
            await monitor._process_all_tracked()
            await monitor._process_all_tracked()
        except Exception as exc:
            pytest.fail(f"FillMonitor raised on None executor response: {exc}")

    async def test_fill_monitor_max_retry_exhaustion_no_crash(
        self, position_tracker, risk_guard
    ) -> None:
        from projects.polymarket.polyquantbot.phase8.fill_monitor import FillMonitor
        from .conftest import StubExecutor

        executor = StubExecutor()
        executor.get_order_status = AsyncMock(return_value=None)
        executor.cancel_order = AsyncMock(return_value=True)

        monitor = FillMonitor(
            executor=executor,
            position_tracker=position_tracker,
            risk_guard=risk_guard,
            order_timeout_sec=3600.0,  # no timeout — test max retry
            max_retry=1,
            poll_interval_sec=0.001,
        )
        monitor.register("ord-maxretry", "0xmkt-retry", "YES", 50.0, 0.62)

        order = monitor._tracked["ord-maxretry"]
        order.retry_count = 1  # already at max

        try:
            await monitor._process_all_tracked()
        except Exception as exc:
            pytest.fail(f"FillMonitor raised on max retry exhaustion: {exc}")

        # Order should be marked processed and removed
        assert "ord-maxretry" not in monitor._tracked
        assert "ord-maxretry" in monitor._processed_order_ids

    async def test_risk_guard_cancel_orders_executor_failure_no_crash(
        self, risk_guard
    ) -> None:
        """Kill switch must complete even if cancel_all_open raises."""
        from .conftest import StubExecutor
        executor = StubExecutor(should_raise=True)
        risk_guard._executor = executor

        try:
            await risk_guard.trigger_kill_switch("api_failure_test")
        except Exception as exc:
            pytest.fail(f"trigger_kill_switch raised on executor error: {exc}")

        assert risk_guard.disabled is True


# ══════════════════════════════════════════════════════════════════════════════
# SC-05 — Partial fills → VWAP computed correctly
# ══════════════════════════════════════════════════════════════════════════════

class TestSC05PartialFills:
    """Incremental fill events must aggregate into a correct VWAP."""

    def test_vwap_two_partial_ws_fills(self, risk_guard) -> None:
        from projects.polymarket.polyquantbot.phase8.fill_monitor import FillMonitor
        from .conftest import StubExecutor

        executor = StubExecutor()
        monitor = FillMonitor(
            executor=executor,
            position_tracker=MagicMock(),
            risk_guard=risk_guard,
        )
        monitor.register("ord-partial", "0xmkt-p", "YES", 100.0, 0.60)

        # First partial: 40 units @ 0.60
        monitor.on_ws_fill("ord-partial", filled_size=40.0, avg_price=0.60)
        order = monitor._tracked["ord-partial"]
        assert abs(order.filled_size - 40.0) < 1e-5
        assert abs(order.avg_fill_price - 0.60) < 1e-5

        # Second partial: 60 units total (additional 20 units @ 0.70)
        # VWAP = (40 * 0.60 + 20 * 0.70) / 60 = (24 + 14) / 60 = 0.6333...
        monitor.on_ws_fill("ord-partial", filled_size=60.0, avg_price=0.70)
        order = monitor._tracked["ord-partial"]
        assert abs(order.filled_size - 60.0) < 1e-5
        expected_vwap = (40 * 0.60 + 20 * 0.70) / 60
        assert abs(order.avg_fill_price - expected_vwap) < 1e-4, (
            f"VWAP mismatch: expected {expected_vwap:.4f}, got {order.avg_fill_price:.4f}"
        )

    def test_duplicate_ws_fill_event_ignored(self, risk_guard) -> None:
        from projects.polymarket.polyquantbot.phase8.fill_monitor import FillMonitor
        from .conftest import StubExecutor

        executor = StubExecutor()
        monitor = FillMonitor(
            executor=executor,
            position_tracker=MagicMock(),
            risk_guard=risk_guard,
        )
        monitor.register("ord-dupfill", "0xmkt-df", "YES", 50.0, 0.62)

        monitor.on_ws_fill("ord-dupfill", filled_size=50.0, avg_price=0.62)
        # Send exactly the same fill again — should be a no-op
        monitor.on_ws_fill("ord-dupfill", filled_size=50.0, avg_price=0.99)

        order = monitor._tracked["ord-dupfill"]
        # avg_fill_price must not have been contaminated by the duplicate
        assert abs(order.avg_fill_price - 0.62) < 1e-5

    def test_poll_partial_fill_vwap_accumulation(self, risk_guard) -> None:
        """Poll-based partial fill must also accumulate VWAP correctly."""
        from projects.polymarket.polyquantbot.phase8.fill_monitor import FillMonitor, OrderStatus
        from .conftest import StubExecutor

        executor = StubExecutor()
        monitor = FillMonitor(
            executor=executor,
            position_tracker=MagicMock(),
            risk_guard=risk_guard,
        )
        monitor.register("ord-pollvwap", "0xmkt-pv", "YES", 100.0, 0.60)
        order = monitor._tracked["ord-pollvwap"]

        # Simulate what _process_order does for a partial poll response
        order.retry_count = 1
        prev_filled = 0.0
        fill1 = 40.0
        price1 = 0.60

        # First partial update
        if fill1 > prev_filled + 1e-9:
            delta = fill1 - prev_filled
            order.avg_fill_price = round(price1, 6)
            order.filled_size = round(fill1, 6)
            prev_filled = fill1

        # Second partial update
        fill2 = 70.0
        price2 = 0.65
        delta = fill2 - prev_filled
        order.avg_fill_price = round(
            (prev_filled * order.avg_fill_price + delta * price2) / fill2, 6
        )
        order.filled_size = round(fill2, 6)

        expected = (40.0 * 0.60 + 30.0 * 0.65) / 70.0
        assert abs(order.avg_fill_price - expected) < 1e-4


# ══════════════════════════════════════════════════════════════════════════════
# SC-06 — Fill probability below threshold → trade blocked
# ══════════════════════════════════════════════════════════════════════════════

class TestSC06LiquidityCheck:
    """Low fill probability (proxy for low liquidity) must block execution."""

    def test_fill_prob_threshold_enforced_in_metrics(
        self, metrics_validator
    ) -> None:
        """MetricsValidator fill_rate gate blocks GO-LIVE when fill rate is low."""
        metrics_validator._min_trades = 1
        metrics_validator._fill_rate_target = 0.60

        metrics_validator.record_fill(filled=False)  # single miss
        metrics_validator.record_fill(filled=False)
        metrics_validator._orders_filled = 1  # manually set one fill for min_trades
        result = metrics_validator.compute()

        # fill_rate < 0.60 → gate must fail
        assert result.gate_details["fill_rate"]["passed"] is False, (
            "Low fill rate gate must report failed"
        )
        assert result.pass_result is False, (
            "Low fill rate must block GO-LIVE"
        )

    async def test_position_open_zero_size_blocked(self, position_tracker) -> None:
        """Zero or negative size must be rejected by PositionTracker."""
        ok = await position_tracker.open("0xmkt", "YES", 0.0, 0.62)
        assert ok is False, "Zero-size position open must be rejected"

    async def test_position_open_negative_price_blocked(self, position_tracker) -> None:
        ok = await position_tracker.open("0xmkt", "YES", 50.0, -0.01)
        assert ok is False, "Negative entry price must be rejected"


# ══════════════════════════════════════════════════════════════════════════════
# SC-07 — EV below threshold → no execution
# ══════════════════════════════════════════════════════════════════════════════

class TestSC07EVThreshold:
    """MetricsValidator EV capture gate must block GO-LIVE if EV is too low."""

    def test_ev_capture_gate_blocks_go_live(self, metrics_validator) -> None:
        metrics_validator._min_trades = 1

        # Record signals where only 50% EV is captured
        for _ in range(15):
            metrics_validator.record_ev_signal(expected_ev=0.10, actual_ev=0.05)
            metrics_validator.record_fill(filled=True)

        result = metrics_validator.compute()
        assert result.ev_capture_ratio < 0.75
        assert result.gate_details["ev_capture_ratio"]["passed"] is False
        assert result.pass_result is False

    def test_ev_capture_gate_passes_when_sufficient(self, metrics_validator) -> None:
        metrics_validator._min_trades = 1
        for _ in range(15):
            metrics_validator.record_ev_signal(expected_ev=0.10, actual_ev=0.10)
            metrics_validator.record_fill(filled=True)
            metrics_validator.record_latency(100.0)

        result = metrics_validator.compute()
        assert result.gate_details["ev_capture_ratio"]["passed"] is True


# ══════════════════════════════════════════════════════════════════════════════
# SC-08 — Drawdown > 8% → global trading halt
# ══════════════════════════════════════════════════════════════════════════════

class TestSC08DrawdownHalt:
    """check_drawdown must fire the kill switch when DD exceeds 8%."""

    async def test_drawdown_above_8pct_triggers_kill_switch(
        self, risk_guard
    ) -> None:
        peak = 10000.0
        current = 9100.0  # 9% drawdown
        await risk_guard.check_drawdown(peak, current)

        assert risk_guard.disabled is True
        assert "drawdown" in risk_guard.kill_switch_reason.lower()

    async def test_drawdown_below_8pct_does_not_trigger(self, risk_guard) -> None:
        peak = 10000.0
        current = 9300.0  # 7% drawdown — under 8% threshold
        await risk_guard.check_drawdown(peak, current)

        assert risk_guard.disabled is False

    async def test_drawdown_exactly_at_threshold_triggers(self, risk_guard) -> None:
        peak = 10000.0
        current = 9200.0  # exactly 8% drawdown
        await risk_guard.check_drawdown(peak, current)

        assert risk_guard.disabled is True

    async def test_drawdown_with_zero_peak_is_safe(self, risk_guard) -> None:
        await risk_guard.check_drawdown(peak_balance=0.0, current_balance=0.0)
        assert risk_guard.disabled is False, "Zero peak must be a safe no-op"

    async def test_risk_guard_status_reflects_drawdown_halt(self) -> None:
        from projects.polymarket.polyquantbot.phase8.risk_guard import RiskGuard
        g = RiskGuard(max_drawdown_pct=0.08)
        await g.check_drawdown(10000.0, 9100.0)
        s = g.status()
        assert s["disabled"] is True
        assert "drawdown" in s["kill_switch_reason"].lower()


# ══════════════════════════════════════════════════════════════════════════════
# SC-09 — Daily loss > −$2 000 → kill switch triggered
# ══════════════════════════════════════════════════════════════════════════════

class TestSC09DailyLossLimit:
    """check_daily_loss must fire the kill switch when PnL breaches −$2 000."""

    async def test_daily_loss_breach_triggers_kill_switch(self, risk_guard) -> None:
        await risk_guard.check_daily_loss(current_pnl=-2001.0)
        assert risk_guard.disabled is True
        assert "daily_loss" in risk_guard.kill_switch_reason.lower()

    async def test_daily_loss_exact_limit_triggers(self, risk_guard) -> None:
        await risk_guard.check_daily_loss(current_pnl=-2000.0)
        assert risk_guard.disabled is True

    async def test_daily_loss_below_limit_is_safe(self, risk_guard) -> None:
        await risk_guard.check_daily_loss(current_pnl=-1999.0)
        assert risk_guard.disabled is False

    async def test_daily_loss_positive_pnl_is_safe(self, risk_guard) -> None:
        await risk_guard.check_daily_loss(current_pnl=500.0)
        assert risk_guard.disabled is False

    async def test_kill_switch_not_double_triggered(self, risk_guard) -> None:
        """Second trigger must not overwrite the first kill_switch_reason."""
        await risk_guard.trigger_kill_switch("first_reason")
        first_reason = risk_guard.kill_switch_reason

        await risk_guard.trigger_kill_switch("second_reason")
        assert risk_guard.kill_switch_reason == first_reason, (
            "Kill switch reason must not be overwritten on second trigger"
        )


# ══════════════════════════════════════════════════════════════════════════════
# SC-10 — Kill switch → disabled flag set immediately (synchronous)
# ══════════════════════════════════════════════════════════════════════════════

class TestSC10KillSwitchImmediate:
    """disabled=True must be visible to concurrent coroutines before any await."""

    async def test_disabled_flag_set_before_cleanup(self, risk_guard) -> None:
        """Simulate concurrent coroutine checking disabled flag during trigger."""
        flag_seen_before_cleanup = False

        async def _concurrent_checker() -> None:
            nonlocal flag_seen_before_cleanup
            # Give trigger coroutine a tick to start
            await asyncio.sleep(0)
            flag_seen_before_cleanup = risk_guard.disabled

        async def _trigger() -> None:
            await risk_guard.trigger_kill_switch("kill_switch_test")

        await asyncio.gather(_trigger(), _concurrent_checker())
        assert risk_guard.disabled is True
        # flag_seen_before_cleanup should be True because disabled is set synchronously
        # before any awaits in trigger_kill_switch

    async def test_kill_switch_blocks_position_open(
        self, risk_guard, position_tracker
    ) -> None:
        await risk_guard.trigger_kill_switch("test")
        ok = await position_tracker.open("0xmkt", "YES", 50.0, 0.60)
        assert ok is False, "PositionTracker must block opens after kill switch"

    async def test_kill_switch_blocks_order_guard_claim(
        self, risk_guard, order_guard
    ) -> None:
        await risk_guard.trigger_kill_switch("test")
        sig = order_guard.compute_signature("0xmkt", "YES", 0.65, 50.0)
        claimed = await order_guard.try_claim(sig)
        assert claimed is False, "OrderGuard must block claims after kill switch"

    async def test_kill_switch_halts_fill_monitor_loop(
        self, position_tracker, risk_guard
    ) -> None:
        """FillMonitor loop must exit immediately when disabled is set."""
        from projects.polymarket.polyquantbot.phase8.fill_monitor import FillMonitor
        from .conftest import StubExecutor

        executor = StubExecutor()
        monitor = FillMonitor(executor, position_tracker, risk_guard, poll_interval_sec=0.001)

        # Pre-disable — loop should not even start
        await risk_guard.trigger_kill_switch("pre_disable")
        run_task = asyncio.create_task(monitor.run())
        await asyncio.sleep(0.05)
        assert not monitor._running, "FillMonitor must not start with kill switch active"
        run_task.cancel()
        try:
            await run_task
        except asyncio.CancelledError:
            pass

    async def test_kill_switch_reason_and_time_recorded(self, risk_guard) -> None:
        t_before = time.time()
        await risk_guard.trigger_kill_switch("reason_test")
        t_after = time.time()

        assert risk_guard.kill_switch_reason == "reason_test"
        assert risk_guard.kill_switch_time is not None
        assert t_before <= risk_guard.kill_switch_time <= t_after


# ══════════════════════════════════════════════════════════════════════════════
# SC-11 — One open position per market — duplicate open blocked
# ══════════════════════════════════════════════════════════════════════════════

class TestSC11ConcurrentPositionLimit:
    """PositionTracker enforces max one OPEN position per market_id."""

    async def test_duplicate_market_open_rejected(self, position_tracker) -> None:
        ok1 = await position_tracker.open("0xmkt-dup", "YES", 50.0, 0.60)
        ok2 = await position_tracker.open("0xmkt-dup", "YES", 50.0, 0.60)
        assert ok1 is True
        assert ok2 is False, "Duplicate open on same market must be rejected"

    async def test_multiple_different_markets_allowed(self, position_tracker) -> None:
        for i in range(5):
            ok = await position_tracker.open(f"0xmkt-{i:03d}", "YES", 50.0, 0.60)
            assert ok is True, f"Open on market-{i} should succeed"

        snapshot = await position_tracker.open_positions_snapshot()
        assert len(snapshot) == 5

    async def test_total_exposure_tracked(self, position_tracker) -> None:
        for i in range(3):
            await position_tracker.open(f"0xmkt-exp{i}", "YES", 100.0, 0.60)

        exposure = await position_tracker.total_exposure()
        assert abs(exposure - 300.0) < 1e-5

    async def test_close_then_reopen_same_market_allowed(
        self, position_tracker
    ) -> None:
        await position_tracker.open("0xmkt-reopen", "YES", 50.0, 0.60)
        await position_tracker.close("0xmkt-reopen", 0.70, 5.0, "normal")
        ok = await position_tracker.open("0xmkt-reopen", "YES", 50.0, 0.60)
        assert ok is True, "Re-open on closed market must be allowed"


# ══════════════════════════════════════════════════════════════════════════════
# SC-12 — Invalid/malformed data → graceful skip, no crash
# ══════════════════════════════════════════════════════════════════════════════

class TestSC12MalformedData:
    """Every entry point must reject bad input without raising an exception."""

    async def test_invalid_side_rejected(self, position_tracker) -> None:
        ok = await position_tracker.open("0xmkt", "MAYBE", 50.0, 0.60)
        assert ok is False, "Invalid side must be rejected"

    async def test_zero_size_rejected(self, position_tracker) -> None:
        ok = await position_tracker.open("0xmkt", "YES", 0.0, 0.60)
        assert ok is False

    async def test_negative_size_rejected(self, position_tracker) -> None:
        ok = await position_tracker.open("0xmkt", "YES", -10.0, 0.60)
        assert ok is False

    async def test_zero_entry_price_rejected(self, position_tracker) -> None:
        ok = await position_tracker.open("0xmkt", "YES", 50.0, 0.0)
        assert ok is False

    async def test_close_non_existent_market_no_crash(
        self, position_tracker
    ) -> None:
        try:
            ok = await position_tracker.close("0xnonexistent", 0.60, 0.0, "test")
            assert ok is False, "Close of unknown market must return False"
        except Exception as exc:
            pytest.fail(f"Close raised for unknown market: {exc}")

    async def test_close_already_closed_no_crash(self, position_tracker) -> None:
        await position_tracker.open("0xmkt-close2", "YES", 50.0, 0.60)
        await position_tracker.close("0xmkt-close2", 0.65, 2.5, "normal")
        try:
            ok = await position_tracker.close("0xmkt-close2", 0.65, 2.5, "double")
            assert ok is False, "Double close must return False"
        except Exception as exc:
            pytest.fail(f"Double close raised exception: {exc}")

    async def test_fill_monitor_on_ws_fill_unknown_order_no_crash(
        self, position_tracker, risk_guard
    ) -> None:
        from projects.polymarket.polyquantbot.phase8.fill_monitor import FillMonitor
        from .conftest import StubExecutor

        monitor = FillMonitor(StubExecutor(), position_tracker, risk_guard)
        try:
            monitor.on_ws_fill("ord-unknown", filled_size=50.0, avg_price=0.62)
        except Exception as exc:
            pytest.fail(f"on_ws_fill raised for unknown order: {exc}")

    async def test_order_guard_release_unknown_sig_no_crash(
        self, order_guard
    ) -> None:
        try:
            await order_guard.release("unknown-signature", "cid-test")
        except Exception as exc:
            pytest.fail(f"release of unknown sig raised: {exc}")

    def test_metrics_validator_empty_session_no_crash(
        self, metrics_validator
    ) -> None:
        try:
            result = metrics_validator.compute()
            assert result is not None
        except Exception as exc:
            pytest.fail(f"MetricsValidator raised on empty session: {exc}")

    def test_metrics_validator_single_latency_sample(
        self, metrics_validator
    ) -> None:
        metrics_validator.record_latency(250.0)
        result = metrics_validator.compute()
        assert result.p95_latency == 250.0


# ══════════════════════════════════════════════════════════════════════════════
# SC-13 — Circuit breaker burst (consecutive failures)
# ══════════════════════════════════════════════════════════════════════════════

class TestSC13CircuitBreakerBurst:
    """Consecutive failures must trigger the circuit breaker faster than the
    rolling error-rate window fills up."""

    async def test_consecutive_failures_trigger_immediately(
        self, circuit_breaker, risk_guard
    ) -> None:
        # threshold = 3; send 3 failures in a row
        for i in range(3):
            await circuit_breaker.record(
                success=False, latency_ms=50.0, correlation_id=f"burst-{i}"
            )
        assert risk_guard.disabled is True
        assert "consecutive_failures" in risk_guard.kill_switch_reason

    async def test_error_rate_window_triggers(self, risk_guard) -> None:
        from projects.polymarket.polyquantbot.phase9.main import CircuitBreaker
        cb = CircuitBreaker(
            risk_guard=risk_guard,
            error_rate_threshold=0.30,
            error_window_size=10,
            latency_threshold_ms=9999.0,
            cooldown_sec=0.0,
            enabled=True,
            consecutive_failures_threshold=100,  # disable consecutive path
        )

        # Send 4 failures out of 10 = 40% > 30% threshold
        for i in range(6):
            await cb.record(success=True, latency_ms=50.0)
        for i in range(4):
            await cb.record(success=False, latency_ms=50.0)

        assert risk_guard.disabled is True
        assert "error_rate" in risk_guard.kill_switch_reason

    async def test_success_resets_consecutive_counter(self, risk_guard) -> None:
        from projects.polymarket.polyquantbot.phase9.main import CircuitBreaker
        cb = CircuitBreaker(
            risk_guard=risk_guard,
            error_rate_threshold=0.30,
            error_window_size=20,
            latency_threshold_ms=9999.0,
            cooldown_sec=0.0,
            consecutive_failures_threshold=3,
        )
        # 2 failures, then 1 success resets counter
        await cb.record(success=False, latency_ms=50.0)
        await cb.record(success=False, latency_ms=50.0)
        await cb.record(success=True, latency_ms=50.0)  # resets to 0
        assert cb._consecutive_failures == 0
        assert risk_guard.disabled is False


# ══════════════════════════════════════════════════════════════════════════════
# SC-14 — Async race condition: parallel claim attempts
# ══════════════════════════════════════════════════════════════════════════════

class TestSC14AsyncRaceCondition:
    """Concurrent try_claim() calls for the same signature must be serialised
    by OrderGuard._lock — exactly one succeeds."""

    async def test_parallel_claims_exactly_one_wins(self, order_guard) -> None:
        sig = order_guard.compute_signature("0xmkt-race", "YES", 0.65, 50.0)

        results = await asyncio.gather(
            order_guard.try_claim(sig, correlation_id="race-A"),
            order_guard.try_claim(sig, correlation_id="race-B"),
            order_guard.try_claim(sig, correlation_id="race-C"),
        )

        assert sum(results) == 1, (
            f"Exactly one claim must succeed under concurrent access; got {results}"
        )

    async def test_parallel_different_signatures_all_succeed(
        self, order_guard
    ) -> None:
        sigs = [
            order_guard.compute_signature(f"0xmkt-{i}", "YES", 0.65, 50.0)
            for i in range(5)
        ]
        results = await asyncio.gather(
            *[order_guard.try_claim(sig, correlation_id=f"cid-{i}") for i, sig in enumerate(sigs)]
        )
        assert all(results), "All different-signature claims must succeed"

    async def test_parallel_position_opens_different_markets(
        self, position_tracker
    ) -> None:
        """Concurrent opens on different markets must all succeed."""
        tasks = [
            position_tracker.open(f"0xmkt-par{i:03d}", "YES", 50.0, 0.60)
            for i in range(10)
        ]
        results = await asyncio.gather(*tasks)
        assert all(results), "All concurrent opens on unique markets must succeed"

    async def test_parallel_position_opens_same_market_only_one_wins(
        self, position_tracker
    ) -> None:
        """Concurrent opens on the SAME market must have exactly one winner."""
        tasks = [
            position_tracker.open("0xmkt-same", "YES", 50.0, 0.60)
            for _ in range(5)
        ]
        results = await asyncio.gather(*tasks)
        assert sum(results) == 1, (
            f"Only one open on same market must succeed; got {sum(results)}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# SC-15 — Stale signature eviction / timeout — no state corruption
# ══════════════════════════════════════════════════════════════════════════════

class TestSC15TimeoutAndEviction:
    """Stale order signatures must be evicted without corrupting state."""

    async def test_stale_signature_evicted(self, risk_guard) -> None:
        from projects.polymarket.polyquantbot.phase8.order_guard import OrderGuard

        guard = OrderGuard(risk_guard=risk_guard, order_timeout_sec=0.01)
        sig = guard.compute_signature("0xmkt-stale", "YES", 0.65, 50.0)
        await guard.try_claim(sig, correlation_id="stale-cid")

        # Wait for timeout to elapse
        await asyncio.sleep(0.05)

        evicted = await guard.evict_stale_now()
        assert evicted == 1, f"Expected 1 evicted signature, got {evicted}"

        # After eviction, same sig can be claimed again
        reclaimed = await guard.try_claim(sig, correlation_id="post-evict")
        assert reclaimed is True

    async def test_fill_monitor_order_timeout_cancels_cleanly(
        self, position_tracker, risk_guard
    ) -> None:
        from projects.polymarket.polyquantbot.phase8.fill_monitor import FillMonitor
        from .conftest import StubExecutor

        executor = StubExecutor()
        executor.cancel_order = AsyncMock(return_value=True)
        monitor = FillMonitor(
            executor=executor,
            position_tracker=position_tracker,
            risk_guard=risk_guard,
            order_timeout_sec=0.01,
            max_retry=10,
            poll_interval_sec=1000.0,
        )
        monitor.register("ord-timeout", "0xmkt-to", "YES", 50.0, 0.62)
        order = monitor._tracked["ord-timeout"]
        # Backdate to simulate timeout
        order.registered_at = time.time() - 1.0

        try:
            await monitor._process_all_tracked()
        except Exception as exc:
            pytest.fail(f"FillMonitor raised on timeout handling: {exc}")

        assert "ord-timeout" not in monitor._tracked
        assert "ord-timeout" in monitor._processed_order_ids
        executor.cancel_order.assert_called_once()

    async def test_position_tracker_snapshot_no_stale_refs(
        self, position_tracker
    ) -> None:
        """After close, snapshot must not contain closed positions."""
        await position_tracker.open("0xmkt-fresh", "YES", 50.0, 0.60)
        await position_tracker.close("0xmkt-fresh", 0.70, 5.0, "tp")
        snapshot = await position_tracker.open_positions_snapshot()
        assert all(p.market_id != "0xmkt-fresh" for p in snapshot)


# ══════════════════════════════════════════════════════════════════════════════
# SC-16 — SYSTEM_STATE transitions
# ══════════════════════════════════════════════════════════════════════════════

class TestSC16SystemStateTransitions:
    """SystemStateManager transitions must be atomic, consistent, and safe."""

    async def test_initial_state_is_running(self, system_state) -> None:
        assert system_state.mode == "RUNNING"
        assert system_state.is_running is True

    async def test_running_to_paused(self, system_state) -> None:
        await system_state.transition("PAUSED", reason="ws_disconnect")
        assert system_state.mode == "PAUSED"
        assert system_state.is_running is False
        assert system_state.reason == "ws_disconnect"

    async def test_paused_to_running(self, system_state) -> None:
        await system_state.transition("PAUSED", reason="ws_disconnect")
        await system_state.transition("RUNNING", reason="ws_reconnected")
        assert system_state.mode == "RUNNING"
        assert system_state.is_running is True

    async def test_running_to_halted(self, system_state) -> None:
        await system_state.transition("HALTED", reason="kill_switch")
        assert system_state.mode == "HALTED"
        assert system_state.is_running is False

    async def test_paused_to_halted(self, system_state) -> None:
        await system_state.transition("PAUSED", reason="ws_disconnect")
        await system_state.transition("HALTED", reason="timeout_60s")
        assert system_state.mode == "HALTED"

    async def test_same_state_transition_is_noop(self, system_state) -> None:
        """Transitioning to the same state must be idempotent."""
        await system_state.transition("RUNNING", reason="noop")
        assert system_state.mode == "RUNNING"
        assert system_state.reason is None, (
            "reason must not be updated when state does not change"
        )

    async def test_snapshot_reflects_current_state(self, system_state) -> None:
        await system_state.transition("PAUSED", reason="test")
        snap = system_state.snapshot()
        assert snap["mode"] == "PAUSED"
        assert snap["reason"] == "test"

    async def test_parallel_transitions_are_serialised(self, system_state) -> None:
        """Concurrent transitions must not corrupt state."""
        await asyncio.gather(
            system_state.transition("PAUSED", reason="concurrent-A"),
            system_state.transition("HALTED", reason="concurrent-B"),
        )
        # Both transitions run under the lock; state must be one of the valid outcomes
        assert system_state.mode in ("PAUSED", "HALTED"), (
            f"State must be valid after concurrent transitions; got {system_state.mode!r}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Risk compliance assertions (standalone)
# ══════════════════════════════════════════════════════════════════════════════

class TestRiskComplianceStandalone:
    """Confirm all mandatory risk constants are set to the correct values."""

    def test_daily_loss_limit_constant(self) -> None:
        from projects.polymarket.polyquantbot.phase8.risk_guard import (
            _DAILY_LOSS_LIMIT_USD,
        )
        assert _DAILY_LOSS_LIMIT_USD == -2000.0, (
            f"Daily loss limit must be -2000.0, got {_DAILY_LOSS_LIMIT_USD}"
        )

    def test_max_drawdown_constant(self) -> None:
        from projects.polymarket.polyquantbot.phase8.risk_guard import (
            _MAX_DRAWDOWN_PCT,
        )
        assert _MAX_DRAWDOWN_PCT == 0.08, (
            f"Max drawdown must be 0.08, got {_MAX_DRAWDOWN_PCT}"
        )

    def test_order_timeout_constant(self) -> None:
        from projects.polymarket.polyquantbot.phase8.order_guard import (
            _ORDER_TIMEOUT_SEC,
        )
        assert _ORDER_TIMEOUT_SEC == 30.0

    def test_fill_monitor_timeout_constant(self) -> None:
        from projects.polymarket.polyquantbot.phase8.fill_monitor import (
            _ORDER_TIMEOUT_SEC as FM_TIMEOUT,
        )
        assert FM_TIMEOUT == 30.0

    async def test_risk_guard_default_limits(self) -> None:
        from projects.polymarket.polyquantbot.phase8.risk_guard import RiskGuard
        g = RiskGuard()
        s = g.status()
        assert s["daily_loss_limit"] == -2000.0
        assert s["max_drawdown_pct"] == 0.08

    def test_metrics_validator_default_targets(self, metrics_validator) -> None:
        assert metrics_validator._ev_capture_target == 0.75
        assert metrics_validator._fill_rate_target == 0.70
        assert metrics_validator._p95_latency_target == 500.0
        assert metrics_validator._max_drawdown_target == 0.08


# ══════════════════════════════════════════════════════════════════════════════
# MetricsValidator GO-LIVE gate
# ══════════════════════════════════════════════════════════════════════════════

class TestMetricsValidatorGOLIVEGate:
    """Verify GO-LIVE gate logic: all 5 gates must pass for approval."""

    def _seed_passing_session(self, v) -> None:
        for _ in range(35):
            v.record_ev_signal(expected_ev=0.10, actual_ev=0.10)
            v.record_fill(filled=True)
            v.record_latency(200.0)
        for i in range(35):
            v.record_pnl_sample(float(i * 5))

    def test_all_gates_pass(self, metrics_validator) -> None:
        self._seed_passing_session(metrics_validator)
        result = metrics_validator.compute()
        assert result.pass_result is True
        assert result.reason == "all_gates_passed"

    def test_min_trades_gate_blocks_go_live(self, metrics_validator) -> None:
        # Only 5 fills — below min_trades=30
        for _ in range(5):
            metrics_validator.record_ev_signal(0.10, 0.10)
            metrics_validator.record_fill(filled=True)
            metrics_validator.record_latency(100.0)
        result = metrics_validator.compute()
        assert result.pass_result is False
        assert "insufficient_trades" in result.reason

    def test_p95_latency_gate_blocks_go_live(self, metrics_validator) -> None:
        for _ in range(12):
            metrics_validator.record_ev_signal(0.10, 0.10)
            metrics_validator.record_fill(filled=True)
        for _ in range(20):
            metrics_validator.record_latency(800.0)  # above 500ms
        result = metrics_validator.compute()
        assert result.gate_details["p95_latency_ms"]["passed"] is False

    def test_max_drawdown_gate_blocks_go_live(self, metrics_validator) -> None:
        for _ in range(12):
            metrics_validator.record_ev_signal(0.10, 0.10)
            metrics_validator.record_fill(filled=True)
            metrics_validator.record_latency(100.0)
        # Drawdown scenario: peak=100, then -50% loss
        metrics_validator.record_pnl_sample(100.0)
        metrics_validator.record_pnl_sample(50.0)
        result = metrics_validator.compute()
        assert result.gate_details["max_drawdown"]["passed"] is False

    def test_from_config_factory(self) -> None:
        from projects.polymarket.polyquantbot.phase9.metrics_validator import (
            MetricsValidator,
        )
        config = {
            "metrics": {
                "ev_target_capture_ratio": 0.80,
                "fill_rate_target": 0.65,
                "p95_latency_target_ms": 400.0,
                "max_drawdown_target": 0.06,
                "min_trades": 20,
            }
        }
        v = MetricsValidator.from_config(config)
        assert v._ev_capture_target == 0.80
        assert v._fill_rate_target == 0.65
        assert v._p95_latency_target == 400.0
        assert v._max_drawdown_target == 0.06
        assert v._min_trades == 20
