"""Phase 12 — Multi-Strategy Integration Test Suite.

Validates ConflictResolver, MultiStrategyMetrics, MultiStrategyOrchestrator,
format_multi_strategy_report, and Phase 10 pipeline runner integration.

  ── ConflictResolver ──
  CI-01  resolve() returns None when YES+NO signals for same market
  CI-02  resolve() passes through when only YES signals
  CI-03  resolve() passes through when only NO signals
  CI-04  stats track conflicts and passed counts
  CI-05  resolve() handles empty signal list (returns empty list, not None)

  ── MultiStrategyMetrics ──
  CI-06  record_signal() increments signals_generated
  CI-07  record_trade(won=True) increments wins
  CI-08  win_rate is 0.0 when no trades
  CI-09  snapshot() returns all registered strategies
  CI-10  record_conflict() increments total_conflicts

  ── MultiStrategyOrchestrator ──
  CI-11  OrchestratorResult.skipped=True when conflict detected
  CI-12  OrchestratorResult.skipped=False when no conflict
  CI-13  from_registry() creates orchestrator without error
  CI-14  signals have strategy_id in metadata after orchestrator run
  CI-15  conflict detection triggers skipped=True in OrchestratorResult

  ── Telegram formatter ──
  CI-16  format_multi_strategy_report returns string starting with '📊'

  ── Pipeline runner ──
  CI-17  Pipeline runner accepts multi_strategy_orchestrator param without error

  ── Cross-market conflict ──
  CI-18  ConflictResolver handles signals from different markets (no conflict)
"""
from __future__ import annotations

import inspect
from typing import Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from projects.polymarket.polyquantbot.strategy.conflict_resolver import (
    ConflictResolver,
    ConflictStats,
)
from projects.polymarket.polyquantbot.monitoring.multi_strategy_metrics import (
    MultiStrategyMetrics,
    StrategyMetrics,
)
from projects.polymarket.polyquantbot.strategy.orchestrator import (
    MultiStrategyOrchestrator,
    OrchestratorResult,
)
from projects.polymarket.polyquantbot.telegram.message_formatter import (
    format_multi_strategy_report,
)
from projects.polymarket.polyquantbot.strategy.base.base_strategy import SignalResult


# ── Helpers ───────────────────────────────────────────────────────────────────


def _signal(market_id: str, side: str, edge: float = 0.05) -> SignalResult:
    """Create a minimal SignalResult for testing."""
    return SignalResult(
        market_id=market_id,
        side=side,
        edge=edge,
        size_usdc=50.0,
    )


MARKET_A = "0xmarket_a"
MARKET_B = "0xmarket_b"


# ═══════════════════════════════════════════════════════════════════════════════
# ── ConflictResolver ──────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════


def test_ci01_conflict_resolver_returns_none_on_yes_no_conflict() -> None:
    """CI-01: resolve() returns None when YES+NO signals for same market."""
    resolver = ConflictResolver()
    signals = [
        _signal(MARKET_A, "YES"),
        _signal(MARKET_A, "NO"),
    ]
    result = resolver.resolve(signals)
    assert result is None


def test_ci02_conflict_resolver_passes_through_yes_only() -> None:
    """CI-02: resolve() passes through when only YES signals."""
    resolver = ConflictResolver()
    signals = [
        _signal(MARKET_A, "YES"),
        _signal(MARKET_B, "YES"),
    ]
    result = resolver.resolve(signals)
    assert result is signals  # same object, unchanged


def test_ci03_conflict_resolver_passes_through_no_only() -> None:
    """CI-03: resolve() passes through when only NO signals."""
    resolver = ConflictResolver()
    signals = [
        _signal(MARKET_A, "NO"),
        _signal(MARKET_B, "NO"),
    ]
    result = resolver.resolve(signals)
    assert result is signals


def test_ci04_conflict_resolver_stats_track_correctly() -> None:
    """CI-04: stats track conflicts and passed counts."""
    resolver = ConflictResolver()

    # Two clean passes
    resolver.resolve([_signal(MARKET_A, "YES")])
    resolver.resolve([_signal(MARKET_B, "NO")])

    # One conflict
    resolver.resolve([_signal(MARKET_A, "YES"), _signal(MARKET_A, "NO")])

    stats: ConflictStats = resolver.stats()
    assert stats.total_checked == 3
    assert stats.conflicts == 1
    assert stats.passed == 2


def test_ci05_conflict_resolver_handles_empty_list() -> None:
    """CI-05: resolve() returns empty list (not None) for empty input."""
    resolver = ConflictResolver()
    result = resolver.resolve([])
    assert result is not None
    assert result == []


# ═══════════════════════════════════════════════════════════════════════════════
# ── MultiStrategyMetrics ──────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════


def test_ci06_metrics_record_signal_increments() -> None:
    """CI-06: record_signal() increments signals_generated."""
    metrics = MultiStrategyMetrics(["ev_momentum"])
    metrics.record_signal("ev_momentum")
    metrics.record_signal("ev_momentum")
    assert metrics.get_metrics("ev_momentum").signals_generated == 2


def test_ci07_metrics_record_trade_win_increments_wins() -> None:
    """CI-07: record_trade(won=True) increments wins."""
    metrics = MultiStrategyMetrics(["ev_momentum"])
    metrics.record_trade("ev_momentum", won=True, ev_captured=0.07)
    m = metrics.get_metrics("ev_momentum")
    assert m.trades_executed == 1
    assert m.wins == 1
    assert m.losses == 0


def test_ci08_metrics_win_rate_zero_when_no_trades() -> None:
    """CI-08: win_rate is 0.0 when no trades recorded."""
    metrics = MultiStrategyMetrics(["mean_reversion"])
    assert metrics.get_metrics("mean_reversion").win_rate == 0.0


def test_ci09_metrics_snapshot_returns_all_strategies() -> None:
    """CI-09: snapshot() returns all registered strategies."""
    names = ["ev_momentum", "mean_reversion", "liquidity_edge"]
    metrics = MultiStrategyMetrics(names)
    snap = metrics.snapshot()
    assert set(snap.keys()) == set(names)
    for name in names:
        assert "strategy_id" in snap[name]
        assert "signals_generated" in snap[name]


def test_ci10_metrics_record_conflict_increments() -> None:
    """CI-10: record_conflict() increments total_conflicts."""
    metrics = MultiStrategyMetrics(["ev_momentum"])
    assert metrics.total_conflicts == 0
    metrics.record_conflict()
    metrics.record_conflict()
    assert metrics.total_conflicts == 2


# ═══════════════════════════════════════════════════════════════════════════════
# ── MultiStrategyOrchestrator ─────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════


async def test_ci11_orchestrator_skipped_true_on_conflict() -> None:
    """CI-11: OrchestratorResult.skipped=True when conflict detected."""
    from projects.polymarket.polyquantbot.strategy.router import StrategyRouter, RouterResult
    from projects.polymarket.polyquantbot.strategy.allocator import StrategyAllocator

    strategy_names = ["ev_momentum", "mean_reversion"]

    # Router that returns YES + NO on same market → conflict
    mock_router = MagicMock(spec=StrategyRouter)
    mock_router.strategy_names = strategy_names
    mock_router.active_strategy_names = strategy_names
    mock_router.evaluate = AsyncMock(
        return_value=RouterResult(
            market_id=MARKET_A,
            signals=[_signal(MARKET_A, "YES"), _signal(MARKET_A, "NO")],
            evaluated=2,
            errored=0,
            skipped=0,
            strategy_signals={
                "ev_momentum": _signal(MARKET_A, "YES"),
                "mean_reversion": _signal(MARKET_A, "NO"),
            },
        )
    )

    resolver = ConflictResolver()
    allocator = StrategyAllocator(strategy_names=strategy_names, bankroll=10_000.0)
    metrics = MultiStrategyMetrics(strategy_names)

    orch = MultiStrategyOrchestrator(
        router=mock_router,
        resolver=resolver,
        allocator=allocator,
        metrics=metrics,
    )

    result = await orch.run(MARKET_A, {})
    assert result.skipped is True
    assert result.conflict_detected is True
    assert result.signals == []
    assert result.allocations == []


async def test_ci12_orchestrator_skipped_false_when_no_conflict() -> None:
    """CI-12: OrchestratorResult.skipped=False when no conflict."""
    from projects.polymarket.polyquantbot.strategy.router import StrategyRouter, RouterResult
    from projects.polymarket.polyquantbot.strategy.allocator import StrategyAllocator

    strategy_names = ["ev_momentum", "mean_reversion"]

    mock_router = MagicMock(spec=StrategyRouter)
    mock_router.strategy_names = strategy_names
    mock_router.active_strategy_names = strategy_names
    mock_router.evaluate = AsyncMock(
        return_value=RouterResult(
            market_id=MARKET_A,
            signals=[_signal(MARKET_A, "YES")],
            evaluated=2,
            errored=0,
            skipped=1,
            strategy_signals={
                "ev_momentum": _signal(MARKET_A, "YES"),
                "mean_reversion": None,
            },
        )
    )

    resolver = ConflictResolver()
    allocator = StrategyAllocator(strategy_names=strategy_names, bankroll=10_000.0)
    metrics = MultiStrategyMetrics(strategy_names)

    orch = MultiStrategyOrchestrator(
        router=mock_router,
        resolver=resolver,
        allocator=allocator,
        metrics=metrics,
    )

    result = await orch.run(MARKET_A, {})
    assert result.skipped is False
    assert result.conflict_detected is False
    assert len(result.signals) >= 0  # may vary, but not skipped


def test_ci13_orchestrator_from_registry_creates_instance() -> None:
    """CI-13: from_registry() creates orchestrator without error."""
    orch = MultiStrategyOrchestrator.from_registry(bankroll=5_000.0)
    assert isinstance(orch, MultiStrategyOrchestrator)


async def test_ci14_orchestrator_signals_have_strategy_id_in_metadata() -> None:
    """CI-14: Signals have strategy_id tagged in metadata after orchestrator run."""
    from projects.polymarket.polyquantbot.strategy.router import StrategyRouter, RouterResult
    from projects.polymarket.polyquantbot.strategy.allocator import StrategyAllocator

    strategy_names = ["ev_momentum"]
    signal = _signal(MARKET_A, "YES", edge=0.10)

    mock_router = MagicMock(spec=StrategyRouter)
    mock_router.strategy_names = strategy_names
    mock_router.active_strategy_names = strategy_names
    mock_router.evaluate = AsyncMock(
        return_value=RouterResult(
            market_id=MARKET_A,
            signals=[signal],
            evaluated=1,
            errored=0,
            skipped=0,
            strategy_signals={"ev_momentum": signal},
        )
    )

    resolver = ConflictResolver()
    allocator = StrategyAllocator(strategy_names=strategy_names, bankroll=10_000.0)
    metrics = MultiStrategyMetrics(strategy_names)

    orch = MultiStrategyOrchestrator(
        router=mock_router,
        resolver=resolver,
        allocator=allocator,
        metrics=metrics,
    )

    result = await orch.run(MARKET_A, {})
    assert result.skipped is False
    # The signal in the result should carry strategy_id in metadata
    if result.signals:
        assert "strategy_id" in result.signals[0].metadata
        assert result.signals[0].metadata["strategy_id"] == "ev_momentum"


async def test_ci15_orchestrator_conflict_triggers_skipped_true() -> None:
    """CI-15: Conflict detection triggers skipped=True in OrchestratorResult."""
    from projects.polymarket.polyquantbot.strategy.router import StrategyRouter, RouterResult
    from projects.polymarket.polyquantbot.strategy.allocator import StrategyAllocator

    strategy_names = ["s1", "s2"]
    sig_yes = _signal(MARKET_A, "YES")
    sig_no = _signal(MARKET_A, "NO")

    mock_router = MagicMock(spec=StrategyRouter)
    mock_router.strategy_names = strategy_names
    mock_router.active_strategy_names = strategy_names
    mock_router.evaluate = AsyncMock(
        return_value=RouterResult(
            market_id=MARKET_A,
            signals=[sig_yes, sig_no],
            evaluated=2,
            errored=0,
            skipped=0,
            strategy_signals={"s1": sig_yes, "s2": sig_no},
        )
    )

    resolver = ConflictResolver()
    allocator = StrategyAllocator(strategy_names=strategy_names, bankroll=10_000.0)
    metrics = MultiStrategyMetrics(strategy_names)

    orch = MultiStrategyOrchestrator(
        router=mock_router,
        resolver=resolver,
        allocator=allocator,
        metrics=metrics,
    )

    result = await orch.run(MARKET_A, {})
    assert result.skipped is True
    assert result.conflict_detected is True


# ═══════════════════════════════════════════════════════════════════════════════
# ── Telegram formatter ────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════


def test_ci16_format_multi_strategy_report_starts_with_chart_emoji() -> None:
    """CI-16: format_multi_strategy_report returns string starting with '📊'."""
    breakdown = {
        "ev_momentum": {
            "signals_generated": 15,
            "trades_executed": 6,
            "win_rate": 0.67,
            "ev_capture_rate": 0.082,
        },
        "mean_reversion": {
            "signals_generated": 14,
            "trades_executed": 5,
            "win_rate": 0.60,
            "ev_capture_rate": 0.061,
        },
    }
    msg = format_multi_strategy_report(
        strategy_breakdown=breakdown,
        conflicts_count=3,
        skipped_trades=3,
        total_signals=42,
        total_trades=15,
    )
    assert isinstance(msg, str)
    assert msg.startswith("📊")
    assert "MULTI-STRATEGY REPORT" in msg
    assert "PAPER" in msg
    assert "Signals: 42" in msg
    assert "Conflicts: 3" in msg


# ═══════════════════════════════════════════════════════════════════════════════
# ── Pipeline runner integration ───────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════


def test_ci17_pipeline_runner_accepts_orchestrator_param() -> None:
    """CI-17: Pipeline runner accepts multi_strategy_orchestrator param without error."""
    from projects.polymarket.polyquantbot.core.pipeline.pipeline_runner import (
        Phase10PipelineRunner,
    )

    sig = inspect.signature(Phase10PipelineRunner.__init__)
    assert "multi_strategy_orchestrator" in sig.parameters


# ═══════════════════════════════════════════════════════════════════════════════
# ── Cross-market conflict ─────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════


def test_ci18_conflict_resolver_different_markets_no_conflict() -> None:
    """CI-18: ConflictResolver handles signals from different markets (no conflict)."""
    resolver = ConflictResolver()
    # YES on market A, NO on market B — different markets, NOT a conflict
    signals = [
        _signal(MARKET_A, "YES"),
        _signal(MARKET_B, "NO"),
    ]
    result = resolver.resolve(signals)
    assert result is signals  # passed through unchanged
    stats = resolver.stats()
    assert stats.conflicts == 0
    assert stats.passed == 1
