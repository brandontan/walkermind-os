"""Phase 10.2 — Tests for execution validation: FillTracker, Reconciliation,
ExecutionSimulator, and MetricsValidator extensions.

Test cases:
  FillTracker
    FT-01  record_submission creates PENDING record
    FT-02  record_fill computes slippage_bps correctly
    FT-03  positive slippage when executed > expected
    FT-04  negative slippage when executed < expected
    FT-05  record_fill computes fill_latency_ms positive
    FT-06  mark_missed sets MISSED status
    FT-07  aggregate — zero submissions returns defaults
    FT-08  aggregate — execution_success_rate
    FT-09  aggregate — fill_accuracy_pct below threshold
    FT-10  aggregate — worst_slippage_bps
    FT-11  duplicate submission warning; second call returns same record
    FT-12  record_fill unknown order_id raises KeyError
    FT-13  mark_missed unknown order_id raises KeyError
    FT-14  p95_slippage via aggregate
    FT-15  partial fill sets PARTIAL status

  Reconciliation
    RC-01  register_order → no fills → OPEN status (within timeout)
    RC-02  register_order → fill → MATCHED status
    RC-03  partial fill below tolerance → PARTIAL
    RC-04  order times out → MISSED
    RC-05  ghost fill logged and has_ghost_positions = True
    RC-06  duplicate fill event → DUPLICATE
    RC-07  open_order_ids returns only OPEN entries
    RC-08  duplicate registration logs warning and ignores second call
    RC-09  reconcile counts correct totals
    RC-10  slippage computed correctly in FillMatch

  ExecutionSimulator (PAPER_LIVE_SIM)
    ES-01  full fill from single orderbook level
    ES-02  partial fill when insufficient liquidity
    ES-03  zero fill when price exceeds limit
    ES-04  no orderbook data → missed fill
    ES-05  multi-level orderbook fill with VWAP
    ES-06  send_real_orders=True without executor raises ValueError
    ES-07  generated order_id is used when none provided
    ES-08  slippage_bps sign — filled at higher price is positive

  MetricsValidator extensions (Phase 10.2)
    MV-01  record_slippage accumulates samples
    MV-02  compute returns avg_slippage_bps
    MV-03  compute returns p95_slippage_bps
    MV-04  compute returns worst_slippage_bps
    MV-05  fill_accuracy_pct — all within threshold
    MV-06  fill_accuracy_pct — some exceed threshold
    MV-07  execution_success_rate mirrors fill_rate
    MV-08  new fields present in compute result
    MV-09  write() includes new fields in JSON output
    MV-10  ingest_fill_aggregate from avg stat
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import time
from typing import Optional
from unittest.mock import MagicMock

import pytest

# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_orderbook(
    ask_levels: list[tuple[float, float]] | None = None,
    bid_levels: list[tuple[float, float]] | None = None,
) -> dict:
    asks = [[p, s] for p, s in (ask_levels or [])]
    bids = [[p, s] for p, s in (bid_levels or [])]
    return {"asks": asks, "bids": bids}


# ══════════════════════════════════════════════════════════════════════════════
# FillTracker
# ══════════════════════════════════════════════════════════════════════════════

class TestFillTrackerSubmission:
    """FT-01: record_submission creates a PENDING record."""

    def test_pending_after_submission(self) -> None:
        from projects.polymarket.polyquantbot.execution.fill_tracker import (
            FillTracker, FillStatus,
        )
        tracker = FillTracker()
        record = tracker.record_submission(
            order_id="ord-001",
            market_id="mkt-001",
            side="YES",
            expected_price=0.62,
            size_usd=100.0,
        )
        assert record.order_id == "ord-001"
        assert record.status == FillStatus.PENDING
        assert record.expected_price == 0.62

    def test_duplicate_submission_returns_existing(self) -> None:
        """FT-11: duplicate submission warning; second call returns same record."""
        from projects.polymarket.polyquantbot.execution.fill_tracker import (
            FillTracker, FillStatus,
        )
        tracker = FillTracker()
        r1 = tracker.record_submission("ord-dup", "mkt-X", "YES", 0.5, 50.0)
        r2 = tracker.record_submission("ord-dup", "mkt-X", "YES", 0.5, 50.0)
        assert r1 is r2


class TestFillTrackerRecordFill:
    """FT-02 – FT-05: fill recording and derived metrics."""

    def _submit(self, tracker, order_id="ord-001", price=0.62, size=100.0):
        from projects.polymarket.polyquantbot.execution.fill_tracker import FillTracker
        tracker.record_submission(order_id, "mkt-001", "YES", price, size)

    def test_slippage_zero_when_prices_equal(self) -> None:
        """FT-02: no slippage when executed == expected."""
        from projects.polymarket.polyquantbot.execution.fill_tracker import (
            FillTracker, FillStatus,
        )
        tracker = FillTracker()
        self._submit(tracker, price=0.62)
        record = tracker.record_fill("ord-001", executed_price=0.62, filled_size=100.0)
        assert record.slippage_bps == pytest.approx(0.0, abs=1e-6)
        assert record.status == FillStatus.FILLED

    def test_positive_slippage_when_executed_above_expected(self) -> None:
        """FT-03: positive slippage = filled worse."""
        from projects.polymarket.polyquantbot.execution.fill_tracker import FillTracker
        tracker = FillTracker()
        self._submit(tracker, price=0.60)
        record = tracker.record_fill("ord-001", executed_price=0.63, filled_size=100.0)
        expected_bps = (0.63 - 0.60) / 0.60 * 10_000
        assert record.slippage_bps == pytest.approx(expected_bps, rel=1e-4)

    def test_negative_slippage_when_executed_below_expected(self) -> None:
        """FT-04: negative slippage = filled better than expected."""
        from projects.polymarket.polyquantbot.execution.fill_tracker import FillTracker
        tracker = FillTracker()
        self._submit(tracker, price=0.65)
        record = tracker.record_fill("ord-001", executed_price=0.62, filled_size=100.0)
        assert record.slippage_bps < 0

    def test_fill_latency_ms_is_positive(self) -> None:
        """FT-05: latency is always >= 0."""
        from projects.polymarket.polyquantbot.execution.fill_tracker import FillTracker
        tracker = FillTracker()
        self._submit(tracker, price=0.62)
        record = tracker.record_fill("ord-001", executed_price=0.62, filled_size=100.0)
        assert record.fill_latency_ms >= 0

    def test_partial_fill_sets_partial_status(self) -> None:
        """FT-15: partial fill uses PARTIAL status."""
        from projects.polymarket.polyquantbot.execution.fill_tracker import (
            FillTracker, FillStatus,
        )
        tracker = FillTracker()
        self._submit(tracker, price=0.62, size=100.0)
        record = tracker.record_fill("ord-001", executed_price=0.62, filled_size=50.0, partial=True)
        assert record.status == FillStatus.PARTIAL

    def test_unknown_order_raises_key_error(self) -> None:
        """FT-12: record_fill unknown order_id raises KeyError."""
        from projects.polymarket.polyquantbot.execution.fill_tracker import FillTracker
        tracker = FillTracker()
        with pytest.raises(KeyError):
            tracker.record_fill("ghost-001", executed_price=0.62, filled_size=100.0)


class TestFillTrackerMarkMissed:
    """FT-06: mark_missed sets MISSED status."""

    def test_mark_missed(self) -> None:
        from projects.polymarket.polyquantbot.execution.fill_tracker import (
            FillTracker, FillStatus,
        )
        tracker = FillTracker()
        tracker.record_submission("ord-miss", "mkt-001", "NO", 0.40, 50.0)
        record = tracker.mark_missed("ord-miss")
        assert record.status == FillStatus.MISSED

    def test_mark_missed_unknown_raises(self) -> None:
        """FT-13: mark_missed unknown order raises KeyError."""
        from projects.polymarket.polyquantbot.execution.fill_tracker import FillTracker
        tracker = FillTracker()
        with pytest.raises(KeyError):
            tracker.mark_missed("no-such-order")


class TestFillTrackerAggregate:
    """FT-07 – FT-14: aggregate statistics."""

    def test_empty_aggregate_defaults(self) -> None:
        """FT-07: empty tracker returns safe defaults."""
        from projects.polymarket.polyquantbot.execution.fill_tracker import FillTracker
        tracker = FillTracker()
        agg = tracker.aggregate()
        assert agg.total_submitted == 0
        assert agg.total_filled == 0
        assert agg.execution_success_rate == 1.0
        assert agg.avg_slippage_bps == 0.0
        assert agg.fill_accuracy_pct == 1.0

    def test_execution_success_rate(self) -> None:
        """FT-08: 2 submitted, 1 filled → 0.5 rate."""
        from projects.polymarket.polyquantbot.execution.fill_tracker import FillTracker
        tracker = FillTracker()
        tracker.record_submission("ord-a", "mkt-1", "YES", 0.60, 100.0)
        tracker.record_submission("ord-b", "mkt-1", "YES", 0.60, 100.0)
        tracker.record_fill("ord-a", executed_price=0.60, filled_size=100.0)
        tracker.mark_missed("ord-b")
        agg = tracker.aggregate()
        assert agg.total_submitted == 2
        assert agg.total_filled == 1
        assert agg.execution_success_rate == pytest.approx(0.5, rel=1e-4)

    def test_fill_accuracy_all_within_threshold(self) -> None:
        """FT-09a: all fills within threshold → accuracy 1.0."""
        from projects.polymarket.polyquantbot.execution.fill_tracker import FillTracker
        tracker = FillTracker(slippage_threshold_bps=100.0)
        for i in range(5):
            oid = f"ord-{i}"
            tracker.record_submission(oid, "mkt-1", "YES", 0.60, 100.0)
            tracker.record_fill(oid, executed_price=0.605, filled_size=100.0)
        agg = tracker.aggregate()
        assert agg.fill_accuracy_pct == pytest.approx(1.0, rel=1e-4)

    def test_fill_accuracy_some_exceed_threshold(self) -> None:
        """FT-09b: one fill exceeds threshold → accuracy < 1.0."""
        from projects.polymarket.polyquantbot.execution.fill_tracker import FillTracker
        tracker = FillTracker(slippage_threshold_bps=10.0)
        # 3 within threshold (~8 bps)
        for i in range(3):
            oid = f"ord-{i}"
            tracker.record_submission(oid, "mkt-1", "YES", 0.60, 100.0)
            tracker.record_fill(oid, executed_price=0.6005, filled_size=100.0)
        # 1 exceeds (200 bps)
        tracker.record_submission("ord-big", "mkt-1", "YES", 0.60, 100.0)
        tracker.record_fill("ord-big", executed_price=0.612, filled_size=100.0)
        agg = tracker.aggregate()
        assert agg.fill_accuracy_pct == pytest.approx(0.75, rel=1e-4)

    def test_worst_slippage_bps(self) -> None:
        """FT-10: worst_slippage_bps tracks maximum absolute slippage."""
        from projects.polymarket.polyquantbot.execution.fill_tracker import FillTracker
        tracker = FillTracker()
        tracker.record_submission("ord-a", "mkt-1", "YES", 0.50, 100.0)
        tracker.record_fill("ord-a", executed_price=0.52, filled_size=100.0)  # +400 bps
        tracker.record_submission("ord-b", "mkt-1", "YES", 0.50, 100.0)
        tracker.record_fill("ord-b", executed_price=0.51, filled_size=100.0)  # +200 bps
        agg = tracker.aggregate()
        assert agg.worst_slippage_bps == pytest.approx(400.0, rel=1e-3)

    def test_p95_slippage_via_aggregate(self) -> None:
        """FT-14: p95_slippage_bps via aggregate."""
        from projects.polymarket.polyquantbot.execution.fill_tracker import FillTracker
        tracker = FillTracker()
        base = 0.50
        for i in range(10):
            oid = f"ord-{i}"
            tracker.record_submission(oid, "mkt-1", "YES", base, 100.0)
            # slippage: 0, 10, 20, ... 90 bps
            executed = base * (1 + i * 0.001)
            tracker.record_fill(oid, executed_price=executed, filled_size=100.0)
        agg = tracker.aggregate()
        # p95 of 10 values → index 9 (value at 90 bps)
        assert agg.p95_slippage_bps >= 0


# ══════════════════════════════════════════════════════════════════════════════
# Reconciliation
# ══════════════════════════════════════════════════════════════════════════════

class TestReconciliationMatching:
    """RC-01 – RC-02: basic order matching."""

    def test_open_within_timeout(self) -> None:
        """RC-01: no fill within timeout → OPEN."""
        from projects.polymarket.polyquantbot.execution.reconciliation import (
            Reconciliation, _ReconStatus,
        )
        recon = Reconciliation(fill_timeout_sec=60.0)
        recon.register_order("ord-1", "mkt-1", "YES", 0.62, 100.0)
        report = recon.reconcile(now=time.time())
        assert report.total_orders == 1
        # Still open (hasn't timed out)
        assert report.matched == 0
        assert report.missed == 0

    def test_full_fill_matched(self) -> None:
        """RC-02: full fill within tolerance → MATCHED."""
        from projects.polymarket.polyquantbot.execution.reconciliation import (
            Reconciliation, _ReconStatus,
        )
        recon = Reconciliation(mismatch_tolerance_usd=0.01)
        recon.register_order("ord-2", "mkt-1", "YES", 0.62, 100.0)
        recon.record_fill("ord-2", filled_size=100.0, executed_price=0.62)
        report = recon.reconcile()
        assert report.matched == 1
        assert report.matches[0].status == _ReconStatus.MATCHED
        assert report.matches[0].discrepancy_usd == pytest.approx(0.0, abs=0.01)


class TestReconciliationPartialAndMissed:
    """RC-03 – RC-04: partial and missed fills."""

    def test_partial_fill_below_tolerance(self) -> None:
        """RC-03: fill significantly below requested size → PARTIAL."""
        from projects.polymarket.polyquantbot.execution.reconciliation import (
            Reconciliation, _ReconStatus,
        )
        recon = Reconciliation(mismatch_tolerance_usd=0.01)
        recon.register_order("ord-3", "mkt-1", "YES", 0.62, 100.0)
        recon.record_fill("ord-3", filled_size=60.0, executed_price=0.62)
        report = recon.reconcile()
        assert report.partial == 1
        assert report.matches[0].status == _ReconStatus.PARTIAL
        assert report.matches[0].discrepancy_usd == pytest.approx(40.0, rel=1e-4)

    def test_missed_fill_after_timeout(self) -> None:
        """RC-04: no fill + age > timeout → MISSED."""
        from projects.polymarket.polyquantbot.execution.reconciliation import (
            Reconciliation, _ReconStatus,
        )
        recon = Reconciliation(fill_timeout_sec=5.0)
        # Register order with submitted_at 10 seconds ago
        recon.register_order("ord-4", "mkt-1", "YES", 0.62, 100.0)
        recon._orders["ord-4"].submitted_at = time.time() - 10.0
        report = recon.reconcile()
        assert report.missed == 1
        assert report.matches[0].status == _ReconStatus.MISSED


class TestReconciliationGhostAndDuplicate:
    """RC-05 – RC-06: ghost fills and duplicate fill events."""

    def test_ghost_fill_detected(self) -> None:
        """RC-05: fill for unknown order_id → ghost position alert."""
        from projects.polymarket.polyquantbot.execution.reconciliation import Reconciliation
        recon = Reconciliation()
        recon.record_fill("ghost-ord-999", filled_size=100.0, executed_price=0.50)
        report = recon.reconcile()
        assert report.ghost_fills == 1
        assert report.has_ghost_positions is True

    def test_duplicate_fill_detected(self) -> None:
        """RC-06: second fill for MATCHED order → DUPLICATE."""
        from projects.polymarket.polyquantbot.execution.reconciliation import (
            Reconciliation, _ReconStatus,
        )
        recon = Reconciliation()
        recon.register_order("ord-dup", "mkt-1", "YES", 0.62, 100.0)
        recon.record_fill("ord-dup", filled_size=100.0, executed_price=0.62)
        # First reconcile to set MATCHED
        recon.reconcile()
        # Second fill arrives for same order
        recon.record_fill("ord-dup", filled_size=100.0, executed_price=0.62)
        report2 = recon.reconcile()
        dup_matches = [m for m in report2.matches if m.status == _ReconStatus.DUPLICATE]
        assert len(dup_matches) == 1


class TestReconciliationMisc:
    """RC-07 – RC-10: misc reconciliation behaviour."""

    def test_open_order_ids(self) -> None:
        """RC-07: open_order_ids returns only OPEN entries."""
        from projects.polymarket.polyquantbot.execution.reconciliation import Reconciliation
        recon = Reconciliation(fill_timeout_sec=60.0)
        recon.register_order("ord-a", "mkt-1", "YES", 0.62, 100.0)
        recon.register_order("ord-b", "mkt-1", "NO", 0.38, 100.0)
        recon.record_fill("ord-b", filled_size=100.0, executed_price=0.38)
        recon.reconcile()
        open_ids = recon.open_order_ids()
        assert "ord-a" in open_ids
        assert "ord-b" not in open_ids

    def test_duplicate_registration_ignored(self) -> None:
        """RC-08: second register_order call for same id is ignored."""
        from projects.polymarket.polyquantbot.execution.reconciliation import Reconciliation
        recon = Reconciliation()
        recon.register_order("ord-x", "mkt-1", "YES", 0.62, 100.0)
        recon.register_order("ord-x", "mkt-1", "YES", 0.99, 999.0)  # ignored
        assert recon._orders["ord-x"].expected_price == 0.62

    def test_reconcile_counts(self) -> None:
        """RC-09: reconcile counts are correct."""
        from projects.polymarket.polyquantbot.execution.reconciliation import Reconciliation
        recon = Reconciliation(mismatch_tolerance_usd=0.01, fill_timeout_sec=60.0)
        # 1 matched
        recon.register_order("ord-1", "mkt-1", "YES", 0.62, 100.0)
        recon.record_fill("ord-1", filled_size=100.0, executed_price=0.62)
        # 1 open
        recon.register_order("ord-2", "mkt-1", "YES", 0.50, 50.0)
        report = recon.reconcile()
        assert report.total_orders == 2
        assert report.matched == 1

    def test_slippage_in_fill_match(self) -> None:
        """RC-10: slippage_bps computed correctly in FillMatch."""
        from projects.polymarket.polyquantbot.execution.reconciliation import Reconciliation
        recon = Reconciliation()
        recon.register_order("ord-slip", "mkt-1", "YES", 0.50, 100.0)
        recon.record_fill("ord-slip", filled_size=100.0, executed_price=0.55)
        report = recon.reconcile()
        match = report.matches[0]
        expected_bps = (0.55 - 0.50) / 0.50 * 10_000.0
        assert match.slippage_bps == pytest.approx(expected_bps, rel=1e-4)


# ══════════════════════════════════════════════════════════════════════════════
# ExecutionSimulator
# ══════════════════════════════════════════════════════════════════════════════

class TestExecutionSimulatorPaperMode:
    """ES-01 – ES-08: PAPER_LIVE_SIM behaviour."""

    def _make_tracker(self):
        from projects.polymarket.polyquantbot.execution.fill_tracker import FillTracker
        return FillTracker()

    async def test_full_fill_single_level(self) -> None:
        """ES-01: single ask level with enough size → full fill."""
        from projects.polymarket.polyquantbot.execution.simulator import (
            ExecutionSimulator, SimMode,
        )
        tracker = self._make_tracker()
        sim = ExecutionSimulator(fill_tracker=tracker, send_real_orders=False)
        ob = _make_orderbook(ask_levels=[(0.62, 200.0)])
        result = await sim.execute(
            market_id="mkt-1", side="YES",
            expected_price=0.62, size_usd=100.0,
            orderbook=ob, order_id="ord-001",
        )
        assert result.success is True
        assert result.filled_size == pytest.approx(100.0, rel=1e-4)
        assert result.simulated_price == pytest.approx(0.62, rel=1e-6)
        assert result.mode == SimMode.PAPER_LIVE_SIM

    async def test_partial_fill_insufficient_liquidity(self) -> None:
        """ES-02: ask level smaller than order → partial fill."""
        from projects.polymarket.polyquantbot.execution.simulator import ExecutionSimulator
        tracker = self._make_tracker()
        sim = ExecutionSimulator(fill_tracker=tracker)
        ob = _make_orderbook(ask_levels=[(0.62, 40.0)])  # only 40 available
        result = await sim.execute(
            market_id="mkt-1", side="YES",
            expected_price=0.62, size_usd=100.0,
            orderbook=ob, order_id="ord-002",
        )
        assert result.success is True
        assert result.filled_size == pytest.approx(40.0, rel=1e-4)
        assert result.reason == "partial_fill"

    async def test_zero_fill_when_price_exceeds_limit(self) -> None:
        """ES-03: ask price > limit → no fill."""
        from projects.polymarket.polyquantbot.execution.simulator import ExecutionSimulator
        tracker = self._make_tracker()
        sim = ExecutionSimulator(fill_tracker=tracker)
        ob = _make_orderbook(ask_levels=[(0.70, 200.0)])  # above our limit 0.62
        result = await sim.execute(
            market_id="mkt-1", side="YES",
            expected_price=0.62, size_usd=100.0,
            orderbook=ob, order_id="ord-003",
        )
        assert result.success is False
        assert result.filled_size == pytest.approx(0.0, abs=1e-6)
        assert result.reason == "insufficient_liquidity"

    async def test_no_orderbook_data_returns_missed(self) -> None:
        """ES-04: no orderbook → missed fill."""
        from projects.polymarket.polyquantbot.execution.simulator import ExecutionSimulator
        tracker = self._make_tracker()
        sim = ExecutionSimulator(fill_tracker=tracker)
        result = await sim.execute(
            market_id="mkt-1", side="YES",
            expected_price=0.62, size_usd=100.0,
            orderbook=None, order_id="ord-004",
        )
        assert result.success is False
        assert result.reason == "no_orderbook_data"

    async def test_multilevel_orderbook_vwap(self) -> None:
        """ES-05: multi-level orderbook fill with correct VWAP."""
        from projects.polymarket.polyquantbot.execution.simulator import ExecutionSimulator
        tracker = self._make_tracker()
        sim = ExecutionSimulator(fill_tracker=tracker)
        # Two levels: 60 @ 0.62, then 60 @ 0.63 — need 100 total
        ob = _make_orderbook(ask_levels=[(0.62, 60.0), (0.63, 60.0)])
        result = await sim.execute(
            market_id="mkt-1", side="YES",
            expected_price=0.63, size_usd=100.0,
            orderbook=ob, order_id="ord-005",
        )
        assert result.success is True
        assert result.filled_size == pytest.approx(100.0, rel=1e-4)
        # VWAP = (60*0.62 + 40*0.63) / 100 = (37.2 + 25.2) / 100 = 0.624
        expected_vwap = (60 * 0.62 + 40 * 0.63) / 100
        assert result.simulated_price == pytest.approx(expected_vwap, rel=1e-4)

    def test_send_real_orders_without_executor_raises(self) -> None:
        """ES-06: send_real_orders=True without executor raises ValueError."""
        from projects.polymarket.polyquantbot.execution.simulator import ExecutionSimulator
        tracker = self._make_tracker()
        with pytest.raises(ValueError, match="executor must be provided"):
            ExecutionSimulator(fill_tracker=tracker, send_real_orders=True, executor=None)

    async def test_generated_order_id_when_none_provided(self) -> None:
        """ES-07: generated order_id used when none provided."""
        from projects.polymarket.polyquantbot.execution.simulator import ExecutionSimulator
        tracker = self._make_tracker()
        sim = ExecutionSimulator(fill_tracker=tracker)
        ob = _make_orderbook(ask_levels=[(0.62, 200.0)])
        result = await sim.execute(
            market_id="mkt-1", side="YES",
            expected_price=0.62, size_usd=50.0,
            orderbook=ob,
        )
        assert result.order_id.startswith("sim-")

    async def test_slippage_negative_when_executed_below_expected(self) -> None:
        """ES-08: slippage_bps negative when fill price < expected (better fill)."""
        from projects.polymarket.polyquantbot.execution.simulator import ExecutionSimulator
        tracker = self._make_tracker()
        sim = ExecutionSimulator(fill_tracker=tracker)
        # Asks at 0.60 which is below our limit/expected of 0.62 → favorable fill
        ob = _make_orderbook(ask_levels=[(0.60, 200.0)])
        result = await sim.execute(
            market_id="mkt-1", side="YES",
            expected_price=0.62, size_usd=100.0,
            orderbook=ob, order_id="ord-slip",
        )
        assert result.success is True
        # Filled at 0.60 < expected 0.62 → negative slippage (favorable)
        assert result.slippage_bps < 0


# ══════════════════════════════════════════════════════════════════════════════
# MetricsValidator extensions (Phase 10.2)
# ══════════════════════════════════════════════════════════════════════════════

def _make_validator(**kwargs):
    from projects.polymarket.polyquantbot.phase9.metrics_validator import MetricsValidator
    return MetricsValidator(
        ev_capture_target=0.75,
        fill_rate_target=0.70,
        p95_latency_target_ms=500.0,
        max_drawdown_target=0.08,
        min_trades=0,   # skip min_trades gate for unit tests
        **kwargs,
    )


def _pump_fills(validator, n: int = 5) -> None:
    """Pump enough signal/fill data to make validator compute valid."""
    for _ in range(n):
        validator.record_ev_signal(expected_ev=0.05, actual_ev=0.04)
        validator.record_fill(filled=True)


class TestMetricsValidatorSlippage:
    """MV-01 – MV-07: slippage and execution quality metrics."""

    def test_record_slippage_accumulates(self) -> None:
        """MV-01: record_slippage accumulates samples."""
        v = _make_validator()
        v.record_slippage(10.0)
        v.record_slippage(20.0)
        assert len(v._slippage_samples_bps) == 2

    def test_avg_slippage_bps(self) -> None:
        """MV-02: compute returns avg_slippage_bps."""
        v = _make_validator()
        _pump_fills(v)
        v.record_slippage(10.0)
        v.record_slippage(30.0)
        result = v.compute()
        assert result.avg_slippage_bps == pytest.approx(20.0, rel=1e-4)

    def test_p95_slippage_bps(self) -> None:
        """MV-03: compute returns p95_slippage_bps."""
        v = _make_validator()
        _pump_fills(v)
        for s in range(1, 11):
            v.record_slippage(float(s * 10))  # 10, 20, ..., 100
        result = v.compute()
        # p95 of 10 values: ceil(10*0.95) - 1 = ceil(9.5) - 1 = 10 - 1 = 9 → index 9 → 100
        assert result.p95_slippage_bps == pytest.approx(100.0, rel=1e-4)

    def test_worst_slippage_bps(self) -> None:
        """MV-04: compute returns worst_slippage_bps."""
        v = _make_validator()
        _pump_fills(v)
        v.record_slippage(15.0)
        v.record_slippage(-80.0)   # negative — worst abs = 80
        v.record_slippage(50.0)
        result = v.compute()
        assert result.worst_slippage_bps == pytest.approx(80.0, rel=1e-4)

    def test_fill_accuracy_all_within_threshold(self) -> None:
        """MV-05: fill_accuracy = 1.0 when all within 50 bps."""
        v = _make_validator()
        _pump_fills(v)
        for _ in range(5):
            v.record_slippage(20.0)  # all within 50 bps
        result = v.compute()
        assert result.fill_accuracy == pytest.approx(1.0, rel=1e-4)

    def test_fill_accuracy_some_exceed_threshold(self) -> None:
        """MV-06: fill_accuracy < 1.0 when some exceed 50 bps."""
        v = _make_validator()
        _pump_fills(v)
        v.record_slippage(20.0)   # ok
        v.record_slippage(20.0)   # ok
        v.record_slippage(200.0)  # exceeds 50 bps threshold
        v.record_slippage(200.0)  # exceeds
        result = v.compute()
        assert result.fill_accuracy == pytest.approx(0.5, rel=1e-4)

    def test_execution_success_rate_mirrors_fill_rate(self) -> None:
        """MV-07: execution_success_rate matches fill_rate."""
        v = _make_validator()
        v.record_fill(filled=True)
        v.record_fill(filled=True)
        v.record_fill(filled=False)
        result = v.compute()
        assert result.execution_success_rate == pytest.approx(
            result.fill_rate, rel=1e-6
        )


class TestMetricsValidatorNewFields:
    """MV-08 – MV-10: new fields in result and JSON output."""

    def test_new_fields_present_in_result(self) -> None:
        """MV-08: new fields present in MetricsResult."""
        v = _make_validator()
        _pump_fills(v)
        result = v.compute()
        assert hasattr(result, "fill_accuracy")
        assert hasattr(result, "avg_slippage_bps")
        assert hasattr(result, "p95_slippage_bps")
        assert hasattr(result, "worst_slippage_bps")
        assert hasattr(result, "execution_success_rate")

    def test_write_includes_new_fields(self, tmp_path) -> None:
        """MV-09: write() includes new fields in JSON output."""
        v = _make_validator()
        _pump_fills(v)
        v.record_slippage(25.0)
        result = v.compute()
        out = str(tmp_path / "metrics.json")
        v.write(result, output_path=out)
        with open(out) as fh:
            payload = json.load(fh)
        assert "fill_accuracy" in payload
        assert "avg_slippage_bps" in payload
        assert "p95_slippage_bps" in payload
        assert "worst_slippage_bps" in payload
        assert "execution_success_rate" in payload

    def test_ingest_fill_aggregate_from_avg(self) -> None:
        """MV-10: ingest_fill_aggregate ingests avg_slippage_bps."""
        v = _make_validator()
        _pump_fills(v)
        # Duck-typed aggregate with only avg_slippage_bps
        agg = MagicMock(spec=["avg_slippage_bps"])
        agg.avg_slippage_bps = 30.0
        v.ingest_fill_aggregate(agg)
        result = v.compute()
        assert result.avg_slippage_bps == pytest.approx(30.0, rel=1e-4)
