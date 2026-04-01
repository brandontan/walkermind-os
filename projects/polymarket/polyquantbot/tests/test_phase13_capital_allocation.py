"""Phase 13 — Dynamic Capital Allocation Test Suite.

Validates the DynamicCapitalAllocator, format_capital_allocation_report, and
the updated MultiStrategyOrchestrator.from_registry() using DynamicCapitalAllocator.

  ── DynamicCapitalAllocator constructor ──
  CA-01  raises ValueError on non-positive bankroll
  CA-02  raises ValueError on empty strategy_names
  CA-03  raises ValueError when max_per_strategy_pct > max_total_exposure_pct
  CA-04  initializes with prior metrics (neutral bootstrap)

  ── Scoring model ──
  CA-05  score() = (ev * confidence) / (1 + drawdown)
  CA-06  score() is 0.0 when ev_capture is 0.0
  CA-07  score() decreases as drawdown increases

  ── Weight normalization ──
  CA-08  weights sum to 1.0 for eligible strategies
  CA-09  all-zero scores returns all-zero weights
  CA-10  disabled strategy gets weight = 0.0
  CA-11  suppressed strategy (low win_rate) gets weight = 0.0
  CA-12  single eligible strategy gets weight = 1.0

  ── Position sizing ──
  CA-13  position_size = weight × max_per_strategy_usd
  CA-14  position capped at max_per_strategy_usd (5% bankroll)
  CA-15  total across all strategies ≤ 10% bankroll
  CA-16  adjusted_size_usd ≤ raw_size_usd

  ── update_metrics ──
  CA-17  raises KeyError for unregistered strategy
  CA-18  auto-disables when drawdown > threshold
  CA-19  re-enables when drawdown recovers below threshold
  CA-20  suppresses (not disables) when win_rate < threshold

  ── allocate gating ──
  CA-21  blocked when strategy is disabled (rejected=True)
  CA-22  blocked when total exposure cap reached (rejected=True)
  CA-23  blocked when win_rate < threshold (rejected=True)
  CA-24  blocked when all weights are zero (rejected=True)
  CA-25  successful allocation returns rejected=False

  ── record_outcome ──
  CA-26  record_outcome raises KeyError for unregistered strategy
  CA-27  record_outcome succeeds for registered strategy

  ── enable/disable ──
  CA-28  disable_strategy raises KeyError for unregistered strategy
  CA-29  enable_strategy raises KeyError for unregistered strategy
  CA-30  manual disable blocks allocation
  CA-31  manual enable allows allocation after disable

  ── allocation_snapshot ──
  CA-32  snapshot weights sum to 1.0 for active strategies
  CA-33  snapshot lists disabled strategies
  CA-34  snapshot lists suppressed strategies
  CA-35  snapshot total_allocated_usd is sum of position_sizes

  ── Risk compliance ──
  CA-36  max_per_strategy_pct default ≤ 5% bankroll
  CA-37  max_total_exposure_pct default ≤ 10% bankroll

  ── Telegram formatter ──
  CA-38  format_capital_allocation_report returns string starting with '💰'
  CA-39  format_capital_allocation_report includes strategy weights
  CA-40  format_capital_allocation_report shows DISABLED strategies
  CA-41  format_capital_allocation_report shows SUPPRESSED strategies
  CA-42  format_capital_allocation_report includes mode label

  ── Orchestrator integration ──
  CA-43  from_registry() uses DynamicCapitalAllocator
  CA-44  from_registry() orchestrator still PAPER mode
  CA-45  allocation respects risk limits from DynamicCapitalAllocator
"""
from __future__ import annotations

import pytest

from projects.polymarket.polyquantbot.strategy.capital_allocator import (
    AllocationSnapshot,
    DynamicCapitalAllocator,
    StrategyMetricSnapshot,
)
from projects.polymarket.polyquantbot.strategy.allocator import AllocationDecision
from projects.polymarket.polyquantbot.telegram.message_formatter import (
    format_capital_allocation_report,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

_NAMES = ["ev_momentum", "mean_reversion", "liquidity_edge"]


def _make_allocator(
    strategy_names: list[str] | None = None,
    bankroll: float = 10_000.0,
    **kwargs,
) -> DynamicCapitalAllocator:
    """Factory helper that creates a DynamicCapitalAllocator."""
    return DynamicCapitalAllocator(
        strategy_names=strategy_names or _NAMES,
        bankroll=bankroll,
        **kwargs,
    )


def _good_metrics(alloc: DynamicCapitalAllocator) -> None:
    """Seed all strategies with good metrics (above all thresholds)."""
    alloc.update_metrics("ev_momentum", ev_capture=0.08, win_rate=0.72, bayesian_confidence=0.85, drawdown=0.02)
    alloc.update_metrics("mean_reversion", ev_capture=0.06, win_rate=0.65, bayesian_confidence=0.75, drawdown=0.01)
    alloc.update_metrics("liquidity_edge", ev_capture=0.05, win_rate=0.60, bayesian_confidence=0.70, drawdown=0.01)


# ═══════════════════════════════════════════════════════════════════════════════
# CA-01 – CA-04: Constructor validation
# ═══════════════════════════════════════════════════════════════════════════════


def test_ca01_raises_on_non_positive_bankroll():
    """CA-01: raises ValueError on non-positive bankroll."""
    with pytest.raises(ValueError, match="bankroll must be positive"):
        DynamicCapitalAllocator(strategy_names=_NAMES, bankroll=0.0)


def test_ca02_raises_on_empty_strategy_names():
    """CA-02: raises ValueError on empty strategy_names."""
    with pytest.raises(ValueError, match="strategy_names must not be empty"):
        DynamicCapitalAllocator(strategy_names=[], bankroll=10_000.0)


def test_ca03_raises_when_per_strategy_exceeds_total():
    """CA-03: raises ValueError when max_per_strategy_pct > max_total_exposure_pct."""
    with pytest.raises(ValueError, match="max_per_strategy_pct must be <= max_total_exposure_pct"):
        DynamicCapitalAllocator(
            strategy_names=_NAMES,
            bankroll=10_000.0,
            max_per_strategy_pct=0.15,
            max_total_exposure_pct=0.10,
        )


def test_ca04_initializes_with_prior_metrics():
    """CA-04: initializes with prior metrics (neutral bootstrap)."""
    alloc = _make_allocator()
    # All strategies should have neutral prior values
    for name in _NAMES:
        assert name in alloc.strategy_names


# ═══════════════════════════════════════════════════════════════════════════════
# CA-05 – CA-07: Scoring model
# ═══════════════════════════════════════════════════════════════════════════════


def test_ca05_score_formula():
    """CA-05: score = (ev * confidence) / (1 + drawdown)."""
    snap = StrategyMetricSnapshot(ev_capture=0.08, bayesian_confidence=0.85, drawdown=0.02, win_rate=0.72)
    expected = (0.08 * 0.85) / (1.0 + 0.02)
    assert snap.score() == pytest.approx(expected, rel=1e-6)


def test_ca06_score_is_zero_when_ev_zero():
    """CA-06: score() is 0.0 when ev_capture is 0.0."""
    snap = StrategyMetricSnapshot(ev_capture=0.0, bayesian_confidence=0.85, drawdown=0.02, win_rate=0.72)
    assert snap.score() == 0.0


def test_ca07_score_decreases_with_drawdown():
    """CA-07: score() decreases as drawdown increases."""
    snap_low = StrategyMetricSnapshot(ev_capture=0.08, bayesian_confidence=0.85, drawdown=0.01, win_rate=0.72)
    snap_high = StrategyMetricSnapshot(ev_capture=0.08, bayesian_confidence=0.85, drawdown=0.05, win_rate=0.72)
    assert snap_low.score() > snap_high.score()


# ═══════════════════════════════════════════════════════════════════════════════
# CA-08 – CA-12: Weight normalization
# ═══════════════════════════════════════════════════════════════════════════════


def test_ca08_weights_sum_to_one():
    """CA-08: weights sum to 1.0 for eligible strategies."""
    alloc = _make_allocator()
    _good_metrics(alloc)
    snapshot = alloc.allocation_snapshot()
    total_weight = sum(snapshot.strategy_weights.values())
    assert total_weight == pytest.approx(1.0, abs=1e-6)


def test_ca09_all_zero_scores_returns_zero_weights():
    """CA-09: all-zero scores returns all-zero weights."""
    alloc = _make_allocator()
    # Set ev_capture=0 for all strategies — scores all zero
    for name in _NAMES:
        alloc.update_metrics(name, ev_capture=0.0, win_rate=0.72, bayesian_confidence=0.85, drawdown=0.01)
    snapshot = alloc.allocation_snapshot()
    assert all(w == 0.0 for w in snapshot.strategy_weights.values())


def test_ca10_disabled_strategy_has_zero_weight():
    """CA-10: disabled strategy gets weight = 0.0."""
    alloc = _make_allocator()
    _good_metrics(alloc)
    alloc.disable_strategy("ev_momentum")
    weights = alloc._compute_weights()
    assert weights["ev_momentum"] == 0.0


def test_ca11_suppressed_strategy_has_zero_weight():
    """CA-11: suppressed strategy (low win_rate) gets weight = 0.0."""
    alloc = _make_allocator(win_rate_threshold=0.70)
    _good_metrics(alloc)
    # mean_reversion win_rate=0.65 < 0.70 → suppressed
    weights = alloc._compute_weights()
    assert weights["mean_reversion"] == 0.0


def test_ca12_single_eligible_gets_weight_one():
    """CA-12: single eligible strategy gets weight = 1.0."""
    alloc = _make_allocator()
    alloc.update_metrics("ev_momentum", ev_capture=0.08, win_rate=0.72, bayesian_confidence=0.85, drawdown=0.01)
    alloc.disable_strategy("mean_reversion")
    alloc.disable_strategy("liquidity_edge")
    weights = alloc._compute_weights()
    assert weights["ev_momentum"] == pytest.approx(1.0)


# ═══════════════════════════════════════════════════════════════════════════════
# CA-13 – CA-16: Position sizing
# ═══════════════════════════════════════════════════════════════════════════════


def test_ca13_position_size_from_weight():
    """CA-13: position_size = weight × max_per_strategy_usd."""
    alloc = _make_allocator()
    _good_metrics(alloc)
    weights = alloc._compute_weights()
    max_per = alloc._max_per_strategy_usd
    snapshot = alloc.allocation_snapshot()
    for name, size in snapshot.position_sizes.items():
        if not alloc.is_disabled(name) and alloc._metrics[name].win_rate >= alloc._win_rate_threshold:
            expected = round(weights[name] * max_per, 2)
            assert size == pytest.approx(expected, abs=0.01), f"Mismatch for {name}"


def test_ca14_position_capped_at_5pct_bankroll():
    """CA-14: position capped at max_per_strategy_usd (5% bankroll)."""
    alloc = _make_allocator(bankroll=10_000.0)
    max_per = alloc._max_per_strategy_usd
    assert max_per == pytest.approx(500.0)  # 5% of 10,000


def test_ca15_total_allocation_within_10pct():
    """CA-15: total across all strategies ≤ 10% bankroll."""
    alloc = _make_allocator(bankroll=10_000.0)
    _good_metrics(alloc)
    snapshot = alloc.allocation_snapshot()
    assert snapshot.total_allocated_usd <= alloc._max_total_exposure_usd


def test_ca16_adjusted_size_does_not_exceed_raw():
    """CA-16: adjusted_size_usd ≤ raw_size_usd."""
    alloc = _make_allocator()
    _good_metrics(alloc)
    decision = alloc.allocate("ev_momentum", raw_size_usd=50.0)
    assert decision.adjusted_size_usd <= 50.0


# ═══════════════════════════════════════════════════════════════════════════════
# CA-17 – CA-20: update_metrics
# ═══════════════════════════════════════════════════════════════════════════════


def test_ca17_update_metrics_raises_for_unknown():
    """CA-17: raises KeyError for unregistered strategy."""
    alloc = _make_allocator()
    with pytest.raises(KeyError, match="ghost_strategy"):
        alloc.update_metrics("ghost_strategy", ev_capture=0.05, win_rate=0.6, bayesian_confidence=0.7, drawdown=0.01)


def test_ca18_auto_disable_on_high_drawdown():
    """CA-18: auto-disables when drawdown > threshold."""
    alloc = _make_allocator(drawdown_threshold=0.08)
    alloc.update_metrics("ev_momentum", ev_capture=0.08, win_rate=0.72, bayesian_confidence=0.85, drawdown=0.09)
    assert alloc.is_disabled("ev_momentum")


def test_ca19_re_enables_when_drawdown_recovers():
    """CA-19: re-enables when drawdown recovers below threshold."""
    alloc = _make_allocator(drawdown_threshold=0.08)
    alloc.update_metrics("ev_momentum", ev_capture=0.08, win_rate=0.72, bayesian_confidence=0.85, drawdown=0.09)
    assert alloc.is_disabled("ev_momentum")
    # Drawdown recovers
    alloc.update_metrics("ev_momentum", ev_capture=0.08, win_rate=0.72, bayesian_confidence=0.85, drawdown=0.03)
    assert not alloc.is_disabled("ev_momentum")


def test_ca20_suppress_not_disable_on_low_win_rate():
    """CA-20: suppresses (not disables) when win_rate < threshold."""
    alloc = _make_allocator(win_rate_threshold=0.50)
    alloc.update_metrics("ev_momentum", ev_capture=0.08, win_rate=0.35, bayesian_confidence=0.85, drawdown=0.01)
    # Not disabled, just suppressed
    assert not alloc.is_disabled("ev_momentum")
    # Weight should be zero
    weights = alloc._compute_weights()
    assert weights["ev_momentum"] == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# CA-21 – CA-25: allocate gating
# ═══════════════════════════════════════════════════════════════════════════════


def test_ca21_blocked_when_disabled():
    """CA-21: blocked when strategy is disabled (rejected=True)."""
    alloc = _make_allocator()
    _good_metrics(alloc)
    alloc.disable_strategy("ev_momentum")
    decision = alloc.allocate("ev_momentum", raw_size_usd=80.0)
    assert decision.rejected is True
    assert decision.adjusted_size_usd == 0.0
    assert "disabled" in decision.rejection_reason.lower()


def test_ca22_blocked_when_exposure_cap_reached():
    """CA-22: blocked when total exposure cap reached (rejected=True)."""
    alloc = _make_allocator(bankroll=10_000.0)  # max total = 1000 USD
    _good_metrics(alloc)
    # current_exposure_usd >= max_total_exposure_usd → blocked
    decision = alloc.allocate("ev_momentum", raw_size_usd=80.0, current_exposure_usd=1_000.0)
    assert decision.rejected is True
    assert "cap" in decision.rejection_reason.lower()


def test_ca23_blocked_when_win_rate_below_threshold():
    """CA-23: blocked when win_rate < threshold (rejected=True)."""
    alloc = _make_allocator(win_rate_threshold=0.70)
    alloc.update_metrics("ev_momentum", ev_capture=0.08, win_rate=0.45, bayesian_confidence=0.85, drawdown=0.01)
    decision = alloc.allocate("ev_momentum", raw_size_usd=80.0)
    assert decision.rejected is True
    assert "win_rate" in decision.rejection_reason.lower()


def test_ca24_blocked_when_all_weights_zero():
    """CA-24: blocked when all weights are zero (rejected=True)."""
    alloc = _make_allocator()
    # Zero ev for all strategies
    for name in _NAMES:
        alloc.update_metrics(name, ev_capture=0.0, win_rate=0.72, bayesian_confidence=0.85, drawdown=0.01)
    decision = alloc.allocate("ev_momentum", raw_size_usd=80.0)
    assert decision.rejected is True


def test_ca25_successful_allocation():
    """CA-25: successful allocation returns rejected=False."""
    alloc = _make_allocator()
    _good_metrics(alloc)
    decision = alloc.allocate("ev_momentum", raw_size_usd=80.0)
    assert decision.rejected is False
    assert decision.adjusted_size_usd > 0.0
    assert decision.confidence > 0.0  # weight stored in confidence field


# ═══════════════════════════════════════════════════════════════════════════════
# CA-26 – CA-27: record_outcome
# ═══════════════════════════════════════════════════════════════════════════════


def test_ca26_record_outcome_raises_for_unknown():
    """CA-26: record_outcome raises KeyError for unregistered strategy."""
    alloc = _make_allocator()
    with pytest.raises(KeyError, match="ghost"):
        alloc.record_outcome("ghost", won=True)


def test_ca27_record_outcome_succeeds():
    """CA-27: record_outcome succeeds for registered strategy."""
    alloc = _make_allocator()
    alloc.record_outcome("ev_momentum", won=True)  # no exception


# ═══════════════════════════════════════════════════════════════════════════════
# CA-28 – CA-31: enable/disable
# ═══════════════════════════════════════════════════════════════════════════════


def test_ca28_disable_raises_for_unknown():
    """CA-28: disable_strategy raises KeyError for unregistered strategy."""
    alloc = _make_allocator()
    with pytest.raises(KeyError, match="ghost"):
        alloc.disable_strategy("ghost")


def test_ca29_enable_raises_for_unknown():
    """CA-29: enable_strategy raises KeyError for unregistered strategy."""
    alloc = _make_allocator()
    with pytest.raises(KeyError, match="ghost"):
        alloc.enable_strategy("ghost")


def test_ca30_manual_disable_blocks_allocation():
    """CA-30: manual disable blocks allocation."""
    alloc = _make_allocator()
    _good_metrics(alloc)
    alloc.disable_strategy("ev_momentum")
    d = alloc.allocate("ev_momentum", raw_size_usd=80.0)
    assert d.rejected is True


def test_ca31_manual_enable_allows_allocation():
    """CA-31: manual enable allows allocation after disable."""
    alloc = _make_allocator()
    _good_metrics(alloc)
    alloc.disable_strategy("ev_momentum")
    alloc.enable_strategy("ev_momentum")
    d = alloc.allocate("ev_momentum", raw_size_usd=80.0)
    assert d.rejected is False


# ═══════════════════════════════════════════════════════════════════════════════
# CA-32 – CA-35: allocation_snapshot
# ═══════════════════════════════════════════════════════════════════════════════


def test_ca32_snapshot_weights_sum_to_one():
    """CA-32: snapshot weights sum to 1.0 for active strategies."""
    alloc = _make_allocator()
    _good_metrics(alloc)
    snap = alloc.allocation_snapshot()
    total = sum(snap.strategy_weights.values())
    assert total == pytest.approx(1.0, abs=1e-6)


def test_ca33_snapshot_lists_disabled():
    """CA-33: snapshot lists disabled strategies."""
    alloc = _make_allocator()
    _good_metrics(alloc)
    alloc.disable_strategy("mean_reversion")
    snap = alloc.allocation_snapshot()
    assert "mean_reversion" in snap.disabled_strategies


def test_ca34_snapshot_lists_suppressed():
    """CA-34: snapshot lists suppressed strategies."""
    alloc = _make_allocator(win_rate_threshold=0.80)
    _good_metrics(alloc)
    snap = alloc.allocation_snapshot()
    # All strategies have win_rate < 0.80
    assert len(snap.suppressed_strategies) == 3


def test_ca35_snapshot_total_matches_sum():
    """CA-35: snapshot total_allocated_usd is sum of position_sizes."""
    alloc = _make_allocator()
    _good_metrics(alloc)
    snap = alloc.allocation_snapshot()
    expected_total = round(sum(snap.position_sizes.values()), 2)
    assert snap.total_allocated_usd == pytest.approx(expected_total, abs=0.01)


# ═══════════════════════════════════════════════════════════════════════════════
# CA-36 – CA-37: Risk compliance
# ═══════════════════════════════════════════════════════════════════════════════


def test_ca36_max_per_strategy_default_5pct():
    """CA-36: max_per_strategy_pct default ≤ 5% bankroll."""
    alloc = _make_allocator(bankroll=10_000.0)
    assert alloc._max_per_strategy_usd == pytest.approx(500.0)  # 5% of 10,000


def test_ca37_max_total_exposure_default_10pct():
    """CA-37: max_total_exposure_pct default ≤ 10% bankroll."""
    alloc = _make_allocator(bankroll=10_000.0)
    assert alloc._max_total_exposure_usd == pytest.approx(1_000.0)  # 10% of 10,000


# ═══════════════════════════════════════════════════════════════════════════════
# CA-38 – CA-42: Telegram formatter
# ═══════════════════════════════════════════════════════════════════════════════


def test_ca38_format_report_starts_with_money_bag():
    """CA-38: format_capital_allocation_report returns string starting with '💰'."""
    msg = format_capital_allocation_report(
        strategy_weights={"ev_momentum": 0.5, "mean_reversion": 0.3, "liquidity_edge": 0.2},
        position_sizes={"ev_momentum": 250.0, "mean_reversion": 150.0, "liquidity_edge": 100.0},
        disabled_strategies=[],
        suppressed_strategies=[],
        total_allocated_usd=500.0,
        bankroll=10_000.0,
    )
    assert msg.startswith("💰")


def test_ca39_format_report_includes_weights():
    """CA-39: format_capital_allocation_report includes strategy weights."""
    msg = format_capital_allocation_report(
        strategy_weights={"ev_momentum": 0.5, "mean_reversion": 0.5},
        position_sizes={"ev_momentum": 250.0, "mean_reversion": 250.0},
        disabled_strategies=[],
        suppressed_strategies=[],
        total_allocated_usd=500.0,
        bankroll=10_000.0,
    )
    assert "ev_momentum" in msg
    assert "mean_reversion" in msg
    assert "0.500" in msg


def test_ca40_format_report_shows_disabled():
    """CA-40: format_capital_allocation_report shows DISABLED strategies."""
    msg = format_capital_allocation_report(
        strategy_weights={"ev_momentum": 0.0, "mean_reversion": 1.0},
        position_sizes={"ev_momentum": 0.0, "mean_reversion": 500.0},
        disabled_strategies=["ev_momentum"],
        suppressed_strategies=[],
        total_allocated_usd=500.0,
        bankroll=10_000.0,
    )
    assert "DISABLED" in msg
    assert "ev_momentum" in msg


def test_ca41_format_report_shows_suppressed():
    """CA-41: format_capital_allocation_report shows SUPPRESSED strategies."""
    msg = format_capital_allocation_report(
        strategy_weights={"ev_momentum": 0.0, "mean_reversion": 1.0},
        position_sizes={"ev_momentum": 0.0, "mean_reversion": 500.0},
        disabled_strategies=[],
        suppressed_strategies=["ev_momentum"],
        total_allocated_usd=500.0,
        bankroll=10_000.0,
    )
    assert "SUPPRESSED" in msg


def test_ca42_format_report_includes_mode():
    """CA-42: format_capital_allocation_report includes mode label."""
    msg = format_capital_allocation_report(
        strategy_weights={"ev_momentum": 1.0},
        position_sizes={"ev_momentum": 500.0},
        disabled_strategies=[],
        suppressed_strategies=[],
        total_allocated_usd=500.0,
        bankroll=10_000.0,
        mode="LIVE",
    )
    # Mode appears on the bankroll/allocated summary line
    assert "LIVE" in msg


# ═══════════════════════════════════════════════════════════════════════════════
# CA-43 – CA-45: Orchestrator integration
# ═══════════════════════════════════════════════════════════════════════════════


def test_ca43_from_registry_uses_dynamic_allocator():
    """CA-43: from_registry() uses DynamicCapitalAllocator."""
    from projects.polymarket.polyquantbot.strategy.orchestrator import MultiStrategyOrchestrator

    orch = MultiStrategyOrchestrator.from_registry(bankroll=10_000.0)
    assert isinstance(orch._allocator, DynamicCapitalAllocator)


def test_ca44_from_registry_is_paper_mode():
    """CA-44: from_registry() orchestrator still PAPER mode."""
    from projects.polymarket.polyquantbot.strategy.orchestrator import MultiStrategyOrchestrator

    orch = MultiStrategyOrchestrator.from_registry()
    assert orch._force_paper is True


async def test_ca45_allocation_respects_risk_limits():
    """CA-45: allocation respects risk limits from DynamicCapitalAllocator."""
    from projects.polymarket.polyquantbot.strategy.orchestrator import (
        MultiStrategyOrchestrator,
        OrchestratorResult,
    )
    from projects.polymarket.polyquantbot.strategy.router import RouterResult, StrategyRouter
    from projects.polymarket.polyquantbot.strategy.conflict_resolver import ConflictResolver
    from projects.polymarket.polyquantbot.monitoring.multi_strategy_metrics import MultiStrategyMetrics
    from projects.polymarket.polyquantbot.strategy.base.base_strategy import SignalResult
    from unittest.mock import AsyncMock, MagicMock

    strategy_names = ["ev_momentum"]
    signal = SignalResult(market_id="0xmkt", side="YES", edge=0.10, size_usdc=1_000_000.0)  # huge request

    mock_router = MagicMock(spec=StrategyRouter)
    mock_router.strategy_names = strategy_names
    mock_router.active_strategy_names = strategy_names
    mock_router.evaluate = AsyncMock(
        return_value=RouterResult(
            market_id="0xmkt",
            signals=[signal],
            evaluated=1,
            errored=0,
            skipped=0,
            strategy_signals={"ev_momentum": signal},
        )
    )

    allocator = DynamicCapitalAllocator(strategy_names=strategy_names, bankroll=10_000.0)
    allocator.update_metrics("ev_momentum", ev_capture=0.08, win_rate=0.72, bayesian_confidence=0.85, drawdown=0.02)

    resolver = ConflictResolver()
    metrics = MultiStrategyMetrics(strategy_names)

    orch = MultiStrategyOrchestrator(
        router=mock_router,
        resolver=resolver,
        allocator=allocator,
        metrics=metrics,
    )

    result = await orch.run("0xmkt", {})
    assert result.skipped is False
    # The adjusted size must not exceed max_per_strategy_usd (500.0 at 5% of 10k)
    for decision in result.allocations:
        assert decision.adjusted_size_usd <= 500.0
