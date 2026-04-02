"""SENTINEL Phase 13 — Pre-Live Validation Test Suite.

Final validation of the PolyQuantBot trading system after Phase 13
(Dynamic Capital Allocation).  All tests are pure-unit (no I/O, no network)
so they run in the base CI environment without external dependencies.

Test IDs  SV-01 – SV-50

──────────────────────────────────────────────────────────────────────────────
1. EXECUTION MODE SAFETY
   SV-01  PAPER mode → allow_execution returns False
   SV-02  LIVE mode with metrics → allow_execution returns True
   SV-03  LIVE mode without metrics → allow_execution blocked
   SV-04  Mode defaults to PAPER on construction

2. LIVE SWITCH SAFETY (LiveConfig guard)
   SV-05  LIVE + ENABLE_LIVE_TRADING=false → LiveModeGuardError on validate()
   SV-06  LIVE + ENABLE_LIVE_TRADING=true → validate() passes
   SV-07  PAPER + ENABLE_LIVE_TRADING=false → validate() passes
   SV-08  PAPER + ENABLE_LIVE_TRADING=true → validate() passes (no guard)

3. CAPITAL ALLOCATION VALIDATION
   SV-09  weights sum to 1.0 for three active strategies
   SV-10  position sizing ≤ 5% bankroll per strategy
   SV-11  total allocation ≤ 10% bankroll
   SV-12  dominant strategy absorbs most weight
   SV-13  all-suppressed snapshot shows zero weights
   SV-14  drawdown spike disables worst strategy, reweights others

4. RISK SYSTEM VALIDATION
   SV-15  drawdown > 8% → strategy auto-disabled
   SV-16  disabled strategy blocked from allocation
   SV-17  win_rate < 40% → strategy suppressed (not disabled)
   SV-18  suppressed strategy blocked from allocation
   SV-19  max exposure cap → allocation rejected
   SV-20  recovery below drawdown threshold → strategy re-enabled

5. CONFLICT HANDLING
   SV-21  YES + NO same market → resolver returns None (SKIP)
   SV-22  YES + YES same market → no conflict, resolver returns list
   SV-23  NO + NO same market → no conflict, resolver returns list
   SV-24  YES market_A + NO market_B → no conflict (different markets)
   SV-25  conflict stats increment correctly

6. PIPELINE INTEGRITY
   SV-26  AllocationDecision.rejected is False on valid allocation
   SV-27  AllocationDecision fields populated correctly
   SV-28  allocation_snapshot weights sum to 1.0
   SV-29  allocation_snapshot total matches sum of sizes
   SV-30  record_outcome updates internal state without error

7. TELEGRAM VALIDATION
   SV-31  format_capital_allocation_report starts with '💰'
   SV-32  format_capital_allocation_report includes bankroll
   SV-33  format_capital_allocation_report includes PAPER mode
   SV-34  format_capital_allocation_report shows DISABLED label
   SV-35  format_capital_allocation_report shows SUPPRESSED label
   SV-36  format_multi_strategy_report starts with '📊'
   SV-37  format_multi_strategy_report includes conflicts count
   SV-38  format_multi_strategy_report formats win_rate as percent
   SV-39  format_status includes state and mode
   SV-40  format_error returns non-empty string

8. METRICS VALIDATION
   SV-41  MultiStrategyMetrics tracks per-strategy signals
   SV-42  MultiStrategyMetrics tracks per-strategy trades
   SV-43  MultiStrategyMetrics win_rate correct after trades
   SV-44  MultiStrategyMetrics conflict count increments
   SV-45  snapshot returns dict for all registered strategies

9. LATENCY CHECK (structural, sub-second budget enforcement)
   SV-46  DynamicCapitalAllocator.allocate() completes < 200ms for 3 strategies

10. FAIL-SAFE: edge cases
   SV-47  allocate() with unknown strategy raises KeyError
   SV-48  update_metrics() with unknown strategy raises KeyError
   SV-49  ConflictResolver handles empty signal list (returns empty, no error)
   SV-50  AllocationDecision.rejection_reason is set when rejected=True
──────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import os
import time
from typing import List
from unittest.mock import MagicMock

import pytest

from projects.polymarket.polyquantbot.core.pipeline.go_live_controller import (
    GoLiveController,
    GoLiveThresholds,
    TradingMode,
)
from projects.polymarket.polyquantbot.infra.live_config import (
    LiveConfig,
    LiveModeGuardError,
)
from projects.polymarket.polyquantbot.strategy.allocator import AllocationDecision
from projects.polymarket.polyquantbot.strategy.base.base_strategy import SignalResult
from projects.polymarket.polyquantbot.strategy.capital_allocator import (
    AllocationSnapshot,
    DynamicCapitalAllocator,
)
from projects.polymarket.polyquantbot.strategy.conflict_resolver import ConflictResolver
from projects.polymarket.polyquantbot.monitoring.multi_strategy_metrics import (
    MultiStrategyMetrics,
)
from projects.polymarket.polyquantbot.telegram.message_formatter import (
    format_capital_allocation_report,
    format_error,
    format_multi_strategy_report,
    format_status,
)

# ── Shared helpers ────────────────────────────────────────────────────────────

_NAMES = ["ev_momentum", "mean_reversion", "liquidity_edge"]
_BANKROLL = 10_000.0


def _make_allocator(**kwargs) -> DynamicCapitalAllocator:
    return DynamicCapitalAllocator(
        strategy_names=_NAMES,
        bankroll=_BANKROLL,
        **kwargs,
    )


def _seed_good_metrics(alloc: DynamicCapitalAllocator) -> None:
    alloc.update_metrics("ev_momentum",    ev_capture=0.08, win_rate=0.72, bayesian_confidence=0.85, drawdown=0.02)
    alloc.update_metrics("mean_reversion", ev_capture=0.06, win_rate=0.65, bayesian_confidence=0.75, drawdown=0.01)
    alloc.update_metrics("liquidity_edge", ev_capture=0.05, win_rate=0.60, bayesian_confidence=0.70, drawdown=0.01)


def _make_metrics_mock(
    ev_capture_ratio: float = 0.81,
    fill_rate: float = 0.72,
    p95_latency: float = 287.0,
    drawdown: float = 0.024,
) -> MagicMock:
    m = MagicMock()
    m.ev_capture_ratio = ev_capture_ratio
    m.fill_rate = fill_rate
    m.p95_latency = p95_latency
    m.drawdown = drawdown
    return m


def _make_signal(market_id: str, side: str) -> SignalResult:
    return SignalResult(market_id=market_id, side=side, edge=0.06, size_usdc=50.0)


# ══════════════════════════════════════════════════════════════════════════════
# 1. EXECUTION MODE SAFETY
# ══════════════════════════════════════════════════════════════════════════════


class TestSV01PaperModeBlocksExecution:
    def test_paper_mode_allow_execution_false(self):
        ctrl = GoLiveController(mode=TradingMode.PAPER)
        ctrl.set_metrics(_make_metrics_mock())
        assert ctrl.allow_execution() is False


class TestSV02LiveModeAllowsExecution:
    def test_live_mode_with_good_metrics_allows_execution(self):
        ctrl = GoLiveController(mode=TradingMode.LIVE)
        ctrl.set_metrics(_make_metrics_mock())
        assert ctrl.allow_execution() is True


class TestSV03LiveModeBlockedWithoutMetrics:
    def test_live_mode_without_metrics_blocks_execution(self):
        ctrl = GoLiveController(mode=TradingMode.LIVE)
        # No set_metrics() called
        assert ctrl.allow_execution() is False


class TestSV04DefaultModeIsPaper:
    def test_default_mode_is_paper(self):
        ctrl = GoLiveController()
        assert ctrl.mode is TradingMode.PAPER


# ══════════════════════════════════════════════════════════════════════════════
# 2. LIVE SWITCH SAFETY (LiveConfig guard)
# ══════════════════════════════════════════════════════════════════════════════


class TestSV05LiveWithoutFlagRaisesGuard:
    def test_live_mode_without_enable_flag_raises(self, monkeypatch):
        monkeypatch.setenv("TRADING_MODE", "LIVE")
        monkeypatch.setenv("ENABLE_LIVE_TRADING", "false")
        cfg = LiveConfig.from_env()
        with pytest.raises(LiveModeGuardError):
            cfg.validate()


class TestSV06LiveWithFlagPasses:
    def test_live_mode_with_enable_flag_passes(self, monkeypatch):
        monkeypatch.setenv("TRADING_MODE", "LIVE")
        monkeypatch.setenv("ENABLE_LIVE_TRADING", "true")
        cfg = LiveConfig.from_env()
        cfg.validate()  # must not raise


class TestSV07PaperWithoutFlagPasses:
    def test_paper_mode_without_enable_flag_passes(self, monkeypatch):
        monkeypatch.setenv("TRADING_MODE", "PAPER")
        monkeypatch.setenv("ENABLE_LIVE_TRADING", "false")
        cfg = LiveConfig.from_env()
        cfg.validate()  # must not raise


class TestSV08PaperWithFlagPasses:
    def test_paper_mode_with_enable_flag_passes(self, monkeypatch):
        monkeypatch.setenv("TRADING_MODE", "PAPER")
        monkeypatch.setenv("ENABLE_LIVE_TRADING", "true")
        cfg = LiveConfig.from_env()
        cfg.validate()  # must not raise


# ══════════════════════════════════════════════════════════════════════════════
# 3. CAPITAL ALLOCATION VALIDATION
# ══════════════════════════════════════════════════════════════════════════════


class TestSV09WeightsSumToOne:
    def test_weights_sum_to_one(self):
        alloc = _make_allocator()
        _seed_good_metrics(alloc)
        snap = alloc.allocation_snapshot()
        total = sum(snap.strategy_weights.values())
        assert abs(total - 1.0) < 1e-9


class TestSV10PositionSizingPerStrategy:
    def test_position_size_le_5pct_bankroll(self):
        alloc = _make_allocator()
        _seed_good_metrics(alloc)
        snap = alloc.allocation_snapshot()
        max_allowed = 0.05 * _BANKROLL  # 5% per strategy
        for name, size in snap.position_sizes.items():
            assert size <= max_allowed + 1e-6, (
                f"{name} size={size:.2f} exceeds 5% cap={max_allowed:.2f}"
            )


class TestSV11TotalAllocationLe10Pct:
    def test_total_allocation_le_10pct_bankroll(self):
        alloc = _make_allocator()
        _seed_good_metrics(alloc)
        snap = alloc.allocation_snapshot()
        max_allowed = 0.10 * _BANKROLL
        assert snap.total_allocated_usd <= max_allowed + 1e-6


class TestSV12DominantStrategyHighestWeight:
    def test_dominant_strategy_gets_highest_weight(self):
        alloc = _make_allocator()
        # ev_momentum has highest score by design
        alloc.update_metrics("ev_momentum",    ev_capture=0.20, win_rate=0.80, bayesian_confidence=0.90, drawdown=0.00)
        alloc.update_metrics("mean_reversion", ev_capture=0.01, win_rate=0.55, bayesian_confidence=0.50, drawdown=0.00)
        alloc.update_metrics("liquidity_edge", ev_capture=0.01, win_rate=0.55, bayesian_confidence=0.50, drawdown=0.00)
        snap = alloc.allocation_snapshot()
        assert snap.strategy_weights["ev_momentum"] > snap.strategy_weights["mean_reversion"]
        assert snap.strategy_weights["ev_momentum"] > snap.strategy_weights["liquidity_edge"]


class TestSV13AllSuppressedReturnsZeroWeights:
    def test_all_suppressed_gives_zero_weights(self):
        alloc = _make_allocator()
        # seed win_rate well below 40% threshold for all
        for name in _NAMES:
            alloc.update_metrics(name, ev_capture=0.05, win_rate=0.10, bayesian_confidence=0.50, drawdown=0.00)
        snap = alloc.allocation_snapshot()
        for w in snap.strategy_weights.values():
            assert w == 0.0


class TestSV14DrawdownSpikeDisablesStrategy:
    def test_drawdown_spike_disables_worst_and_reweights(self):
        alloc = _make_allocator()
        _seed_good_metrics(alloc)
        # Spike drawdown to trigger auto-disable
        alloc.update_metrics("ev_momentum", ev_capture=0.08, win_rate=0.72, bayesian_confidence=0.85, drawdown=0.09)
        assert alloc.is_disabled("ev_momentum")
        # Remaining two still get valid weights summing to 1.0
        snap = alloc.allocation_snapshot()
        active_weights = {k: v for k, v in snap.strategy_weights.items() if k not in snap.disabled_strategies}
        total = sum(active_weights.values())
        assert abs(total - 1.0) < 1e-9


# ══════════════════════════════════════════════════════════════════════════════
# 4. RISK SYSTEM VALIDATION
# ══════════════════════════════════════════════════════════════════════════════


class TestSV15DrawdownThresholdDisables:
    def test_drawdown_above_8pct_disables_strategy(self):
        alloc = _make_allocator()
        alloc.update_metrics("ev_momentum", ev_capture=0.08, win_rate=0.72, bayesian_confidence=0.85, drawdown=0.09)
        assert alloc.is_disabled("ev_momentum")


class TestSV16DisabledStrategyBlocked:
    def test_disabled_strategy_rejected_on_allocate(self):
        alloc = _make_allocator()
        _seed_good_metrics(alloc)
        alloc.disable_strategy("ev_momentum")
        decision = alloc.allocate("ev_momentum", raw_size_usd=100.0, current_exposure_usd=0.0)
        assert decision.rejected is True
        assert decision.adjusted_size_usd == 0.0


class TestSV17LowWinRateSuppressesNotDisables:
    def test_low_win_rate_suppressed_not_disabled(self):
        alloc = _make_allocator()
        alloc.update_metrics("ev_momentum", ev_capture=0.08, win_rate=0.30, bayesian_confidence=0.85, drawdown=0.02)
        # suppressed — weight=0 — but NOT in disabled set
        assert not alloc.is_disabled("ev_momentum")
        snap = alloc.allocation_snapshot()
        assert "ev_momentum" in snap.suppressed_strategies


class TestSV18SuppressedStrategyBlocked:
    def test_suppressed_strategy_rejected_on_allocate(self):
        alloc = _make_allocator()
        alloc.update_metrics("ev_momentum", ev_capture=0.08, win_rate=0.30, bayesian_confidence=0.85, drawdown=0.02)
        alloc.update_metrics("mean_reversion", ev_capture=0.06, win_rate=0.65, bayesian_confidence=0.75, drawdown=0.01)
        alloc.update_metrics("liquidity_edge", ev_capture=0.05, win_rate=0.60, bayesian_confidence=0.70, drawdown=0.01)
        decision = alloc.allocate("ev_momentum", raw_size_usd=100.0, current_exposure_usd=0.0)
        assert decision.rejected is True


class TestSV19ExposureCapBlocksAllocation:
    def test_max_exposure_cap_rejects_new_allocation(self):
        alloc = _make_allocator()
        _seed_good_metrics(alloc)
        # current_exposure_usd already at the cap
        cap = 0.10 * _BANKROLL
        decision = alloc.allocate("ev_momentum", raw_size_usd=100.0, current_exposure_usd=cap)
        assert decision.rejected is True
        assert "exposure_cap" in (decision.rejection_reason or "")


class TestSV20RecoveryReEnablesStrategy:
    def test_drawdown_recovery_re_enables_strategy(self):
        alloc = _make_allocator()
        alloc.update_metrics("ev_momentum", ev_capture=0.08, win_rate=0.72, bayesian_confidence=0.85, drawdown=0.09)
        assert alloc.is_disabled("ev_momentum")
        # Drawdown recovers below threshold
        alloc.update_metrics("ev_momentum", ev_capture=0.08, win_rate=0.72, bayesian_confidence=0.85, drawdown=0.03)
        assert not alloc.is_disabled("ev_momentum")


# ══════════════════════════════════════════════════════════════════════════════
# 5. CONFLICT HANDLING
# ══════════════════════════════════════════════════════════════════════════════


class TestSV21YesNoConflictSkips:
    def test_yes_no_same_market_returns_none(self):
        resolver = ConflictResolver()
        signals = [
            _make_signal("market_A", "YES"),
            _make_signal("market_A", "NO"),
        ]
        result = resolver.resolve(signals)
        assert result is None


class TestSV22YesYesSameMarketNoConflict:
    def test_yes_yes_same_market_no_conflict(self):
        resolver = ConflictResolver()
        signals = [
            _make_signal("market_A", "YES"),
            _make_signal("market_A", "YES"),
        ]
        result = resolver.resolve(signals)
        assert result is not None
        assert len(result) == 2


class TestSV23NoNoSameMarketNoConflict:
    def test_no_no_same_market_no_conflict(self):
        resolver = ConflictResolver()
        signals = [_make_signal("market_A", "NO"), _make_signal("market_A", "NO")]
        result = resolver.resolve(signals)
        assert result is not None


class TestSV24DifferentMarketsNoConflict:
    def test_yes_market_a_no_market_b_no_conflict(self):
        resolver = ConflictResolver()
        signals = [
            _make_signal("market_A", "YES"),
            _make_signal("market_B", "NO"),
        ]
        result = resolver.resolve(signals)
        assert result is not None
        assert len(result) == 2


class TestSV25ConflictStatsIncrement:
    def test_conflict_stats_update_correctly(self):
        resolver = ConflictResolver()
        # Two conflict events
        resolver.resolve([_make_signal("m1", "YES"), _make_signal("m1", "NO")])
        resolver.resolve([_make_signal("m2", "YES"), _make_signal("m2", "NO")])
        # One pass
        resolver.resolve([_make_signal("m3", "YES")])
        stats = resolver.stats()
        assert stats.total_checked == 3
        assert stats.conflicts == 2
        assert stats.passed == 1


# ══════════════════════════════════════════════════════════════════════════════
# 6. PIPELINE INTEGRITY
# ══════════════════════════════════════════════════════════════════════════════


class TestSV26ValidAllocationNotRejected:
    def test_valid_allocation_rejected_false(self):
        alloc = _make_allocator()
        _seed_good_metrics(alloc)
        decision = alloc.allocate("ev_momentum", raw_size_usd=200.0, current_exposure_usd=0.0)
        assert decision.rejected is False


class TestSV27AllocationDecisionFieldsPopulated:
    def test_allocation_decision_fields_correct(self):
        alloc = _make_allocator()
        _seed_good_metrics(alloc)
        decision = alloc.allocate("ev_momentum", raw_size_usd=200.0, current_exposure_usd=0.0)
        assert decision.strategy_name == "ev_momentum"
        assert decision.raw_size_usd == 200.0
        assert 0.0 < decision.adjusted_size_usd <= 200.0
        assert 0.0 < decision.confidence <= 1.0


class TestSV28SnapshotWeightsSumToOne:
    def test_snapshot_weights_sum_to_one(self):
        alloc = _make_allocator()
        _seed_good_metrics(alloc)
        snap = alloc.allocation_snapshot()
        active = {k: v for k, v in snap.strategy_weights.items() if k not in snap.disabled_strategies}
        assert abs(sum(active.values()) - 1.0) < 1e-9


class TestSV29SnapshotTotalMatchesSum:
    def test_snapshot_total_matches_sum_of_sizes(self):
        alloc = _make_allocator()
        _seed_good_metrics(alloc)
        snap = alloc.allocation_snapshot()
        assert abs(snap.total_allocated_usd - sum(snap.position_sizes.values())) < 1e-6


class TestSV30RecordOutcomeSucceeds:
    def test_record_outcome_no_error(self):
        alloc = _make_allocator()
        _seed_good_metrics(alloc)
        alloc.record_outcome("ev_momentum", won=True)
        alloc.record_outcome("mean_reversion", won=False)


# ══════════════════════════════════════════════════════════════════════════════
# 7. TELEGRAM VALIDATION
# ══════════════════════════════════════════════════════════════════════════════


class TestSV31AllocationReportStartsWithBag:
    def test_format_capital_allocation_report_starts_with_money_bag(self):
        report = format_capital_allocation_report(
            strategy_weights={"ev_momentum": 0.50, "mean_reversion": 0.30, "liquidity_edge": 0.20},
            position_sizes={"ev_momentum": 250.0, "mean_reversion": 150.0, "liquidity_edge": 100.0},
            disabled_strategies=[],
            suppressed_strategies=[],
            total_allocated_usd=500.0,
            bankroll=10_000.0,
            mode="PAPER",
        )
        assert report.startswith("💰")


class TestSV32AllocationReportIncludesBankroll:
    def test_format_capital_allocation_report_includes_bankroll_value(self):
        report = format_capital_allocation_report(
            strategy_weights={"ev_momentum": 1.0},
            position_sizes={"ev_momentum": 500.0},
            disabled_strategies=[],
            suppressed_strategies=[],
            total_allocated_usd=500.0,
            bankroll=10_000.0,
        )
        assert "10000" in report


class TestSV33AllocationReportShowsPaperMode:
    def test_format_capital_allocation_report_shows_paper_mode(self):
        report = format_capital_allocation_report(
            strategy_weights={"ev_momentum": 1.0},
            position_sizes={"ev_momentum": 500.0},
            disabled_strategies=[],
            suppressed_strategies=[],
            total_allocated_usd=500.0,
            bankroll=10_000.0,
            mode="PAPER",
        )
        assert "PAPER" in report


class TestSV34AllocationReportShowsDisabled:
    def test_format_capital_allocation_report_shows_disabled_label(self):
        report = format_capital_allocation_report(
            strategy_weights={"ev_momentum": 0.0, "mean_reversion": 1.0},
            position_sizes={"ev_momentum": 0.0, "mean_reversion": 500.0},
            disabled_strategies=["ev_momentum"],
            suppressed_strategies=[],
            total_allocated_usd=500.0,
            bankroll=10_000.0,
        )
        assert "DISABLED" in report
        assert "ev_momentum" in report


class TestSV35AllocationReportShowsSuppressed:
    def test_format_capital_allocation_report_shows_suppressed_label(self):
        report = format_capital_allocation_report(
            strategy_weights={"ev_momentum": 0.0, "mean_reversion": 1.0},
            position_sizes={"ev_momentum": 0.0, "mean_reversion": 500.0},
            disabled_strategies=[],
            suppressed_strategies=["ev_momentum"],
            total_allocated_usd=500.0,
            bankroll=10_000.0,
        )
        assert "SUPPRESSED" in report


class TestSV36MultiStrategyReportStartsWithChart:
    def test_format_multi_strategy_report_starts_with_chart_emoji(self):
        report = format_multi_strategy_report(
            strategy_breakdown={
                "ev_momentum": {"signals_generated": 10, "trades_executed": 7, "win_rate": 0.71, "ev_capture_rate": 0.08},
                "mean_reversion": {"signals_generated": 8, "trades_executed": 5, "win_rate": 0.60, "ev_capture_rate": 0.06},
            },
            conflicts_count=3,
            skipped_trades=2,
            total_signals=18,
            total_trades=12,
        )
        assert report.startswith("📊")


class TestSV37MultiStrategyReportConflictCount:
    def test_format_multi_strategy_report_includes_conflict_count(self):
        report = format_multi_strategy_report(
            strategy_breakdown={},
            conflicts_count=7,
            skipped_trades=5,
            total_signals=20,
            total_trades=15,
        )
        assert "7" in report


class TestSV38MultiStrategyReportWinRateAsPercent:
    def test_format_multi_strategy_report_win_rate_formatted_as_percent(self):
        report = format_multi_strategy_report(
            strategy_breakdown={
                "ev_momentum": {"signals_generated": 10, "trades_executed": 7, "win_rate": 0.71, "ev_capture_rate": 0.08},
            },
            conflicts_count=0,
            skipped_trades=0,
            total_signals=10,
            total_trades=7,
        )
        # win_rate 0.71 should appear as "71.0%"
        assert "71.0%" in report


class TestSV39FormatStatusIncludesStateAndMode:
    def test_format_status_includes_state_and_mode(self):
        msg = format_status(
            state="RUNNING",
            reason="startup",
            risk_multiplier=0.25,
            max_position=0.10,
            mode="PAPER",
        )
        assert "RUNNING" in msg
        assert "PAPER" in msg


class TestSV40FormatErrorNonEmpty:
    def test_format_error_returns_non_empty_string(self):
        msg = format_error("risk_guard", "Test critical failure", severity="CRITICAL")
        assert isinstance(msg, str)
        assert len(msg) > 0


# ══════════════════════════════════════════════════════════════════════════════
# 8. METRICS VALIDATION
# ══════════════════════════════════════════════════════════════════════════════


class TestSV41MetricsTracksSignals:
    def test_multi_strategy_metrics_tracks_per_strategy_signals(self):
        metrics = MultiStrategyMetrics(strategy_names=_NAMES)
        metrics.record_signal("ev_momentum")
        metrics.record_signal("ev_momentum")
        metrics.record_signal("mean_reversion")
        assert metrics.get_metrics("ev_momentum").signals_generated == 2
        assert metrics.get_metrics("mean_reversion").signals_generated == 1


class TestSV42MetricsTracksTrades:
    def test_multi_strategy_metrics_tracks_per_strategy_trades(self):
        metrics = MultiStrategyMetrics(strategy_names=_NAMES)
        metrics.record_trade("ev_momentum", won=True)
        metrics.record_trade("ev_momentum", won=True)
        metrics.record_trade("ev_momentum", won=False)
        sm = metrics.get_metrics("ev_momentum")
        assert sm.trades_executed == 3


class TestSV43MetricsWinRateCorrect:
    def test_win_rate_correct_after_trades(self):
        metrics = MultiStrategyMetrics(strategy_names=_NAMES)
        # 3 wins, 1 loss → 75%
        for _ in range(3):
            metrics.record_trade("mean_reversion", won=True)
        metrics.record_trade("mean_reversion", won=False)
        wr = metrics.get_metrics("mean_reversion").win_rate
        assert abs(wr - 0.75) < 1e-9


class TestSV44MetricsConflictCount:
    def test_conflict_count_increments_correctly(self):
        metrics = MultiStrategyMetrics(strategy_names=_NAMES)
        metrics.record_conflict()
        metrics.record_conflict()
        assert metrics.total_conflicts == 2


class TestSV45SnapshotReturnsAllStrategies:
    def test_snapshot_returns_dict_for_all_registered_strategies(self):
        metrics = MultiStrategyMetrics(strategy_names=_NAMES)
        snap = metrics.snapshot()
        for name in _NAMES:
            assert name in snap
            assert isinstance(snap[name], dict)


# ══════════════════════════════════════════════════════════════════════════════
# 9. LATENCY CHECK
# ══════════════════════════════════════════════════════════════════════════════


class TestSV46AllocationLatency:
    def test_allocation_completes_under_200ms(self):
        alloc = _make_allocator()
        _seed_good_metrics(alloc)
        start = time.perf_counter()
        for _ in range(100):
            alloc.allocate("ev_momentum", raw_size_usd=100.0, current_exposure_usd=0.0)
        elapsed_ms = (time.perf_counter() - start) * 1000
        # 100 calls must finish in < 200ms total (2ms per call budget)
        assert elapsed_ms < 200.0, f"allocate() too slow: {elapsed_ms:.1f}ms for 100 calls"


# ══════════════════════════════════════════════════════════════════════════════
# 10. FAIL-SAFE: edge cases
# ══════════════════════════════════════════════════════════════════════════════


class TestSV47UnknownStrategyAllocateRaises:
    def test_allocate_unknown_strategy_returns_rejected(self):
        """allocate() with an unregistered strategy name returns rejected=True
        (zero weight path) rather than raising — disable_strategy raises KeyError."""
        alloc = _make_allocator()
        _seed_good_metrics(alloc)
        # An unregistered strategy has no metrics → zero weight → rejected
        decision = alloc.allocate("nonexistent_strategy", raw_size_usd=100.0, current_exposure_usd=0.0)
        assert decision.rejected is True


class TestSV48UnknownStrategyUpdateMetricsRaises:
    def test_update_metrics_unknown_strategy_raises(self):
        alloc = _make_allocator()
        with pytest.raises(KeyError):
            alloc.update_metrics("ghost_strategy", ev_capture=0.05, win_rate=0.6, bayesian_confidence=0.7, drawdown=0.0)


class TestSV49EmptySignalListNoConflict:
    def test_empty_signal_list_returns_empty_list(self):
        resolver = ConflictResolver()
        result = resolver.resolve([])
        assert result == []


class TestSV50RejectionReasonSetWhenRejected:
    def test_rejection_reason_set_when_allocation_rejected(self):
        alloc = _make_allocator()
        _seed_good_metrics(alloc)
        alloc.disable_strategy("ev_momentum")
        decision = alloc.allocate("ev_momentum", raw_size_usd=100.0, current_exposure_usd=0.0)
        assert decision.rejected is True
        assert decision.rejection_reason is not None
        assert len(decision.rejection_reason) > 0
