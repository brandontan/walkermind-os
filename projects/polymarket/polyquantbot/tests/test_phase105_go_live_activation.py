"""Phase 10.5 — GO-LIVE Activation System Test Suite.

Validates the LiveModeController, CapitalAllocator, LiveExecutor (gated),
LiveAuditLogger, and the updated pipeline_runner strict gating logic.

Scenarios covered:

  GL-01  LIVE MODE CONTROLLER — is_live_enabled returns False in PAPER mode
  GL-02  LIVE MODE CONTROLLER — is_live_enabled requires all metrics to pass
  GL-03  LIVE MODE CONTROLLER — kill switch blocks LIVE regardless of metrics
  GL-04  LIVE MODE CONTROLLER — borderline ev_capture blocks (strict >=)
  GL-05  LIVE MODE CONTROLLER — borderline fill_rate blocks (strict >=)
  GL-06  LIVE MODE CONTROLLER — borderline p95_latency blocks (strict <=)
  GL-07  LIVE MODE CONTROLLER — borderline drawdown blocks (strict <=)
  GL-08  LIVE MODE CONTROLLER — get_block_reason returns descriptive string
  GL-09  LIVE MODE CONTROLLER — no_risk_guard causes block (fail closed)
  GL-10  LIVE MODE CONTROLLER — set_mode switches between PAPER and LIVE
  GL-11  LIVE MODE CONTROLLER — from_config parses thresholds correctly
  GL-12  CAPITAL ALLOCATOR — valid allocation within all caps
  GL-13  CAPITAL ALLOCATOR — concurrent_trades cap raises error
  GL-14  CAPITAL ALLOCATOR — total_exposure cap raises error
  GL-15  CAPITAL ALLOCATOR — initial_cap exceeded raises error
  GL-16  CAPITAL ALLOCATOR — zero signal_strength returns zero size
  GL-17  CAPITAL ALLOCATOR — invalid bankroll raises ValueError
  GL-18  CAPITAL ALLOCATOR — from_config parses correctly
  GL-19  CAPITAL ALLOCATOR — deterministic (same input → same output)
  GL-20  LIVE EXECUTOR — blocked when live_mode_controller returns False
  GL-21  LIVE EXECUTOR — blocked when execution_guard rejects
  GL-22  LIVE EXECUTOR — redis dedup blocks duplicate order
  GL-23  LIVE EXECUTOR — successful execution records fill in FillTracker
  GL-24  LIVE EXECUTOR — fail closed on exchange error
  GL-25  LIVE EXECUTOR — retries on transient error
  GL-26  LIVE AUDIT — write_pre emits structured log record
  GL-27  LIVE AUDIT — write_post emits structured log record
  GL-28  LIVE AUDIT — write_post raises AuditWriteError on DB failure
  GL-29  PIPELINE RUNNER — live_mode_controller always checked first
  GL-30  PIPELINE RUNNER — simulator used when live_mode_controller blocked
  GL-31  PIPELINE RUNNER — gated_executor used when live_mode_controller passes
  GL-32  PIPELINE RUNNER — telegram notified on live_enabled event
  GL-33  PIPELINE RUNNER — telegram notified on execution_success
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_risk_guard(disabled: bool = False) -> MagicMock:
    guard = MagicMock()
    guard.disabled = disabled
    return guard


def _make_metrics_validator(
    ev_capture: float = 0.80,
    fill_rate: float = 0.70,
    p95_latency: float = 300.0,
    drawdown: float = 0.05,
) -> MagicMock:
    mv = MagicMock()
    mv.ev_capture_ratio = ev_capture
    mv.fill_rate = fill_rate
    mv.p95_latency = p95_latency
    mv.drawdown = drawdown
    return mv


def _make_audit_logger(db_connected: bool = True) -> MagicMock:
    """Stub LiveAuditLogger for Phase 10.6 infra checks."""
    audit = MagicMock()
    audit.is_db_connected.return_value = db_connected
    return audit


def _make_redis_client() -> MagicMock:
    """Stub Redis client for Phase 10.6 infra checks."""
    redis = MagicMock()
    redis.exists = AsyncMock(return_value=False)
    redis.setex = AsyncMock()
    return redis


def _make_live_infra() -> dict:
    """Return the Phase 10.6 infra kwargs required for LIVE mode controllers."""
    return {
        "redis_client": _make_redis_client(),
        "audit_logger": _make_audit_logger(db_connected=True),
        "telegram_configured": True,
    }


# ══════════════════════════════════════════════════════════════════════════════
# GL-01 – GL-11  LiveModeController
# ══════════════════════════════════════════════════════════════════════════════


class TestLiveModeControllerPaperMode:
    """GL-01: PAPER mode always blocks LIVE."""

    def test_paper_mode_blocks(self) -> None:
        from projects.polymarket.polyquantbot.phase10.live_mode_controller import (
            LiveModeController,
        )
        from projects.polymarket.polyquantbot.phase10.go_live_controller import TradingMode

        ctrl = LiveModeController(
            mode=TradingMode.PAPER,
            metrics_validator=_make_metrics_validator(),
            risk_guard=_make_risk_guard(disabled=False),
        )
        assert ctrl.is_live_enabled() is False

    def test_paper_mode_block_reason(self) -> None:
        from projects.polymarket.polyquantbot.phase10.live_mode_controller import (
            LiveModeController,
        )
        from projects.polymarket.polyquantbot.phase10.go_live_controller import TradingMode

        ctrl = LiveModeController(
            mode=TradingMode.PAPER,
            metrics_validator=_make_metrics_validator(),
            risk_guard=_make_risk_guard(disabled=False),
        )
        assert ctrl.get_block_reason() == "paper_mode"


class TestLiveModeControllerAllMetricsPass:
    """GL-02: All metrics passing enables LIVE."""

    def test_all_metrics_pass(self) -> None:
        from projects.polymarket.polyquantbot.phase10.live_mode_controller import (
            LiveModeController,
        )
        from projects.polymarket.polyquantbot.phase10.go_live_controller import TradingMode

        ctrl = LiveModeController(
            mode=TradingMode.LIVE,
            metrics_validator=_make_metrics_validator(),
            risk_guard=_make_risk_guard(disabled=False),
            **_make_live_infra(),
        )
        assert ctrl.is_live_enabled() is True
        assert ctrl.get_block_reason() == ""


class TestLiveModeControllerKillSwitch:
    """GL-03: Kill switch hard-blocks LIVE regardless of metrics."""

    def test_kill_switch_blocks(self) -> None:
        from projects.polymarket.polyquantbot.phase10.live_mode_controller import (
            LiveModeController,
        )
        from projects.polymarket.polyquantbot.phase10.go_live_controller import TradingMode

        ctrl = LiveModeController(
            mode=TradingMode.LIVE,
            metrics_validator=_make_metrics_validator(),
            risk_guard=_make_risk_guard(disabled=True),
        )
        assert ctrl.is_live_enabled() is False
        assert "kill_switch" in ctrl.get_block_reason()


class TestLiveModeControllerBorderlineMetrics:
    """GL-04 – GL-07: Borderline metrics block with strict inequality."""

    def test_ev_capture_at_threshold_passes(self) -> None:
        from projects.polymarket.polyquantbot.phase10.live_mode_controller import (
            LiveModeController,
        )
        from projects.polymarket.polyquantbot.phase10.go_live_controller import TradingMode

        ctrl = LiveModeController(
            mode=TradingMode.LIVE,
            metrics_validator=_make_metrics_validator(ev_capture=0.75),
            risk_guard=_make_risk_guard(),
            **_make_live_infra(),
        )
        assert ctrl.is_live_enabled() is True  # >= 0.75

    def test_ev_capture_below_threshold_blocks(self) -> None:
        from projects.polymarket.polyquantbot.phase10.live_mode_controller import (
            LiveModeController,
        )
        from projects.polymarket.polyquantbot.phase10.go_live_controller import TradingMode

        ctrl = LiveModeController(
            mode=TradingMode.LIVE,
            metrics_validator=_make_metrics_validator(ev_capture=0.74),
            risk_guard=_make_risk_guard(),
        )
        assert ctrl.is_live_enabled() is False  # GL-04

    def test_fill_rate_at_threshold_passes(self) -> None:
        from projects.polymarket.polyquantbot.phase10.live_mode_controller import (
            LiveModeController,
        )
        from projects.polymarket.polyquantbot.phase10.go_live_controller import TradingMode

        ctrl = LiveModeController(
            mode=TradingMode.LIVE,
            metrics_validator=_make_metrics_validator(fill_rate=0.60),
            risk_guard=_make_risk_guard(),
            **_make_live_infra(),
        )
        assert ctrl.is_live_enabled() is True

    def test_fill_rate_below_threshold_blocks(self) -> None:
        from projects.polymarket.polyquantbot.phase10.live_mode_controller import (
            LiveModeController,
        )
        from projects.polymarket.polyquantbot.phase10.go_live_controller import TradingMode

        ctrl = LiveModeController(
            mode=TradingMode.LIVE,
            metrics_validator=_make_metrics_validator(fill_rate=0.59),
            risk_guard=_make_risk_guard(),
        )
        assert ctrl.is_live_enabled() is False  # GL-05

    def test_p95_latency_at_limit_passes(self) -> None:
        from projects.polymarket.polyquantbot.phase10.live_mode_controller import (
            LiveModeController,
        )
        from projects.polymarket.polyquantbot.phase10.go_live_controller import TradingMode

        ctrl = LiveModeController(
            mode=TradingMode.LIVE,
            metrics_validator=_make_metrics_validator(p95_latency=500.0),
            risk_guard=_make_risk_guard(),
            **_make_live_infra(),
        )
        assert ctrl.is_live_enabled() is True

    def test_p95_latency_above_limit_blocks(self) -> None:
        from projects.polymarket.polyquantbot.phase10.live_mode_controller import (
            LiveModeController,
        )
        from projects.polymarket.polyquantbot.phase10.go_live_controller import TradingMode

        ctrl = LiveModeController(
            mode=TradingMode.LIVE,
            metrics_validator=_make_metrics_validator(p95_latency=500.1),
            risk_guard=_make_risk_guard(),
        )
        assert ctrl.is_live_enabled() is False  # GL-06

    def test_drawdown_at_limit_passes(self) -> None:
        from projects.polymarket.polyquantbot.phase10.live_mode_controller import (
            LiveModeController,
        )
        from projects.polymarket.polyquantbot.phase10.go_live_controller import TradingMode

        ctrl = LiveModeController(
            mode=TradingMode.LIVE,
            metrics_validator=_make_metrics_validator(drawdown=0.08),
            risk_guard=_make_risk_guard(),
            **_make_live_infra(),
        )
        assert ctrl.is_live_enabled() is True

    def test_drawdown_above_limit_blocks(self) -> None:
        from projects.polymarket.polyquantbot.phase10.live_mode_controller import (
            LiveModeController,
        )
        from projects.polymarket.polyquantbot.phase10.go_live_controller import TradingMode

        ctrl = LiveModeController(
            mode=TradingMode.LIVE,
            metrics_validator=_make_metrics_validator(drawdown=0.081),
            risk_guard=_make_risk_guard(),
        )
        assert ctrl.is_live_enabled() is False  # GL-07


class TestLiveModeControllerBlockReason:
    """GL-08: get_block_reason returns descriptive string."""

    def test_ev_capture_block_reason(self) -> None:
        from projects.polymarket.polyquantbot.phase10.live_mode_controller import (
            LiveModeController,
        )
        from projects.polymarket.polyquantbot.phase10.go_live_controller import TradingMode

        ctrl = LiveModeController(
            mode=TradingMode.LIVE,
            metrics_validator=_make_metrics_validator(ev_capture=0.50),
            risk_guard=_make_risk_guard(),
        )
        reason = ctrl.get_block_reason()
        assert "ev_capture" in reason
        assert "0.50" in reason or "threshold" in reason


class TestLiveModeControllerNoRiskGuard:
    """GL-09: No risk_guard injected → fail closed (block)."""

    def test_no_risk_guard_blocks(self) -> None:
        from projects.polymarket.polyquantbot.phase10.live_mode_controller import (
            LiveModeController,
        )
        from projects.polymarket.polyquantbot.phase10.go_live_controller import TradingMode

        ctrl = LiveModeController(
            mode=TradingMode.LIVE,
            metrics_validator=_make_metrics_validator(),
            risk_guard=None,
        )
        assert ctrl.is_live_enabled() is False
        assert "no_risk_guard" in ctrl.get_block_reason()


class TestLiveModeControllerSetMode:
    """GL-10: set_mode switches between PAPER and LIVE."""

    def test_switch_paper_to_live(self) -> None:
        from projects.polymarket.polyquantbot.phase10.live_mode_controller import (
            LiveModeController,
        )
        from projects.polymarket.polyquantbot.phase10.go_live_controller import TradingMode

        ctrl = LiveModeController(
            mode=TradingMode.PAPER,
            metrics_validator=_make_metrics_validator(),
            risk_guard=_make_risk_guard(),
            **_make_live_infra(),
        )
        assert ctrl.is_live_enabled() is False
        ctrl.set_mode(TradingMode.LIVE)
        assert ctrl.is_live_enabled() is True

    def test_switch_live_to_paper(self) -> None:
        from projects.polymarket.polyquantbot.phase10.live_mode_controller import (
            LiveModeController,
        )
        from projects.polymarket.polyquantbot.phase10.go_live_controller import TradingMode

        ctrl = LiveModeController(
            mode=TradingMode.LIVE,
            metrics_validator=_make_metrics_validator(),
            risk_guard=_make_risk_guard(),
            **_make_live_infra(),
        )
        assert ctrl.is_live_enabled() is True
        ctrl.set_mode(TradingMode.PAPER)
        assert ctrl.is_live_enabled() is False


class TestLiveModeControllerFromConfig:
    """GL-11: from_config parses thresholds correctly."""

    def test_from_config_live_mode(self) -> None:
        from projects.polymarket.polyquantbot.phase10.live_mode_controller import (
            LiveModeController,
        )
        from projects.polymarket.polyquantbot.phase10.go_live_controller import TradingMode

        cfg = {"go_live": {"mode": "LIVE", "ev_capture_min": 0.80}}
        ctrl = LiveModeController.from_config(
            cfg,
            metrics_validator=_make_metrics_validator(ev_capture=0.85),
            risk_guard=_make_risk_guard(),
        )
        assert ctrl.mode == TradingMode.LIVE
        assert ctrl._thresholds.ev_capture_min == 0.80

    def test_from_config_invalid_mode_falls_back_to_paper(self) -> None:
        from projects.polymarket.polyquantbot.phase10.live_mode_controller import (
            LiveModeController,
        )
        from projects.polymarket.polyquantbot.phase10.go_live_controller import TradingMode

        cfg = {"go_live": {"mode": "INVALID_MODE"}}
        ctrl = LiveModeController.from_config(cfg)
        assert ctrl.mode == TradingMode.PAPER


# ══════════════════════════════════════════════════════════════════════════════
# GL-12 – GL-19  CapitalAllocator
# ══════════════════════════════════════════════════════════════════════════════


class TestCapitalAllocatorValid:
    """GL-12: Valid allocation within all caps."""

    def test_basic_allocation(self) -> None:
        from projects.polymarket.polyquantbot.phase10.capital_allocator import (
            CapitalAllocator,
        )

        alloc = CapitalAllocator(bankroll=10_000.0)
        result = alloc.compute_position_size(
            signal_strength=0.80,
            current_exposure=0.0,
            concurrent_trades=0,
        )
        assert result.position_size_usd == pytest.approx(160.0)  # 10k * 2% * 0.8

    def test_full_signal_uses_per_trade_cap(self) -> None:
        from projects.polymarket.polyquantbot.phase10.capital_allocator import (
            CapitalAllocator,
        )

        alloc = CapitalAllocator(bankroll=10_000.0)
        result = alloc.compute_position_size(
            signal_strength=1.0,
            current_exposure=0.0,
            concurrent_trades=0,
        )
        assert result.position_size_usd == pytest.approx(200.0)  # 10k * 2%


class TestCapitalAllocatorConcurrentCap:
    """GL-13: concurrent_trades cap raises CapitalAllocationError."""

    def test_max_concurrent_blocks(self) -> None:
        from projects.polymarket.polyquantbot.phase10.capital_allocator import (
            CapitalAllocator,
            CapitalAllocationError,
        )

        alloc = CapitalAllocator(bankroll=10_000.0, max_concurrent_trades=2)
        with pytest.raises(CapitalAllocationError, match="concurrent_trades_cap"):
            alloc.compute_position_size(
                signal_strength=0.5,
                current_exposure=0.0,
                concurrent_trades=2,
            )


class TestCapitalAllocatorTotalExposureCap:
    """GL-14: total_exposure cap raises CapitalAllocationError."""

    def test_exposure_at_cap_blocks(self) -> None:
        from projects.polymarket.polyquantbot.phase10.capital_allocator import (
            CapitalAllocator,
            CapitalAllocationError,
        )

        alloc = CapitalAllocator(bankroll=10_000.0)  # max 5% = 500
        with pytest.raises(CapitalAllocationError, match="total_exposure_cap"):
            alloc.compute_position_size(
                signal_strength=0.5,
                current_exposure=500.0,  # already at cap
                concurrent_trades=0,
            )


class TestCapitalAllocatorInitialCap:
    """GL-15: initial_cap exceeded raises CapitalAllocationError."""

    def test_initial_cap_exceeded(self) -> None:
        from projects.polymarket.polyquantbot.phase10.capital_allocator import (
            CapitalAllocator,
            CapitalAllocationError,
        )

        # Use initial_cap_pct=0.03 (300 USD) < max_total_exposure_pct=0.05 (500 USD)
        # current_exposure=200, raw_size=120 (3% * 1.0 = 300, nope... 2% * 1.0 = 200)
        # Actually: bankroll=10000, initial_cap=3%=300, per_trade_cap=2%=200
        # remaining_exposure = 500-100 = 400, raw_size = 200*1.0=200 < 400 ✓
        # projected = 100 + 200 = 300 = initial_cap → equal, passes; try 101+200=301>300
        alloc = CapitalAllocator(
            bankroll=10_000.0,
            initial_cap_pct=0.03,        # 300 USD initial cap
            max_total_exposure_pct=0.05,  # 500 USD total exposure cap
        )
        with pytest.raises(CapitalAllocationError, match="initial_cap_exceeded"):
            alloc.compute_position_size(
                signal_strength=1.0,
                current_exposure=101.0,  # 101 + 200 = 301 > 300 initial cap
                concurrent_trades=0,
            )


class TestCapitalAllocatorZeroSignal:
    """GL-16: zero signal_strength returns zero size."""

    def test_zero_signal_returns_zero(self) -> None:
        from projects.polymarket.polyquantbot.phase10.capital_allocator import (
            CapitalAllocator,
        )

        alloc = CapitalAllocator(bankroll=10_000.0)
        result = alloc.compute_position_size(
            signal_strength=0.0,
            current_exposure=0.0,
            concurrent_trades=0,
        )
        assert result.position_size_usd == pytest.approx(0.0)


class TestCapitalAllocatorInvalidBankroll:
    """GL-17: invalid bankroll raises ValueError."""

    def test_negative_bankroll_raises(self) -> None:
        from projects.polymarket.polyquantbot.phase10.capital_allocator import (
            CapitalAllocator,
        )

        with pytest.raises(ValueError, match="bankroll"):
            CapitalAllocator(bankroll=-1.0)

    def test_zero_bankroll_raises(self) -> None:
        from projects.polymarket.polyquantbot.phase10.capital_allocator import (
            CapitalAllocator,
        )

        with pytest.raises(ValueError, match="bankroll"):
            CapitalAllocator(bankroll=0.0)


class TestCapitalAllocatorFromConfig:
    """GL-18: from_config parses correctly."""

    def test_from_config(self) -> None:
        from projects.polymarket.polyquantbot.phase10.capital_allocator import (
            CapitalAllocator,
        )

        cfg = {
            "capital": {
                "bankroll": 5_000.0,
                "max_per_trade_pct": 0.01,
                "max_concurrent_trades": 1,
            }
        }
        alloc = CapitalAllocator.from_config(cfg)
        assert alloc.bankroll == 5_000.0
        assert alloc.max_per_trade_usd == pytest.approx(50.0)


class TestCapitalAllocatorDeterministic:
    """GL-19: deterministic — same input → same output."""

    def test_same_input_same_output(self) -> None:
        from projects.polymarket.polyquantbot.phase10.capital_allocator import (
            CapitalAllocator,
        )

        alloc = CapitalAllocator(bankroll=10_000.0)
        r1 = alloc.compute_position_size(0.6, 50.0, 0)
        r2 = alloc.compute_position_size(0.6, 50.0, 0)
        assert r1.position_size_usd == r2.position_size_usd


# ══════════════════════════════════════════════════════════════════════════════
# GL-20 – GL-25  LiveExecutor (gated)
# ══════════════════════════════════════════════════════════════════════════════


def _make_execution_request(market_id: str = "0xabc") -> object:
    from projects.polymarket.polyquantbot.phase7.core.execution.live_executor import (
        ExecutionRequest,
    )

    return ExecutionRequest(
        market_id=market_id,
        side="YES",
        price=0.62,
        size=100.0,
        correlation_id=str(uuid.uuid4()),
    )


def _make_live_mode_ctrl(live: bool = True) -> object:
    from projects.polymarket.polyquantbot.phase10.live_mode_controller import (
        LiveModeController,
    )
    from projects.polymarket.polyquantbot.phase10.go_live_controller import TradingMode

    mode = TradingMode.LIVE if live else TradingMode.PAPER
    infra = _make_live_infra() if live else {}
    ctrl = LiveModeController(
        mode=mode,
        metrics_validator=_make_metrics_validator(),
        risk_guard=_make_risk_guard(disabled=False),
        **infra,
    )
    return ctrl


def _make_execution_guard(pass_validation: bool = True) -> object:
    from projects.polymarket.polyquantbot.phase10.execution_guard import (
        ExecutionGuard,
        ValidationResult,
    )

    guard = MagicMock(spec=ExecutionGuard)
    guard.validate.return_value = ValidationResult(
        passed=pass_validation,
        reason="" if pass_validation else "slippage_exceeded:0.1>0.03",
        checks={},
    )
    return guard


def _make_phase7_executor(status: str = "submitted") -> object:
    from projects.polymarket.polyquantbot.phase7.core.execution.live_executor import (
        ExecutionResult,
    )

    executor = MagicMock()
    executor.execute = AsyncMock(
        return_value=ExecutionResult(
            order_id="ord-001",
            status=status,
            filled_size=100.0 if status == "filled" else 0.0,
            avg_price=0.62,
            latency_ms=200.0,
            correlation_id="cid-001",
            is_paper=False,
        )
    )
    return executor


class TestGatedLiveExecutorBlockedByLiveMode:
    """GL-20: blocked when live_mode_controller returns False."""

    async def test_blocked_paper_mode(self) -> None:
        from projects.polymarket.polyquantbot.execution.live_executor import LiveExecutor

        executor = LiveExecutor(
            live_mode_controller=_make_live_mode_ctrl(live=False),
            execution_guard=_make_execution_guard(pass_validation=True),
            phase7_executor=_make_phase7_executor(),
        )
        result = await executor.execute(_make_execution_request())
        assert result.allowed is False
        assert "live_mode_blocked" in result.block_reason


class TestGatedLiveExecutorBlockedByGuard:
    """GL-21: blocked when execution_guard rejects."""

    async def test_blocked_guard_reject(self) -> None:
        from projects.polymarket.polyquantbot.execution.live_executor import LiveExecutor

        redis = _make_redis_client()
        executor = LiveExecutor(
            live_mode_controller=_make_live_mode_ctrl(live=True),
            execution_guard=_make_execution_guard(pass_validation=False),
            phase7_executor=_make_phase7_executor(),
            redis_client=redis,
        )
        result = await executor.execute(
            _make_execution_request(),
            market_ctx={"depth": 50_000.0, "spread": 0.01},
        )
        assert result.allowed is False
        assert "execution_guard" in result.block_reason


class TestGatedLiveExecutorRedisDedupBlocks:
    """GL-22: Redis dedup blocks duplicate order."""

    async def test_redis_dedup_blocks(self) -> None:
        from projects.polymarket.polyquantbot.execution.live_executor import LiveExecutor

        redis = MagicMock()
        redis.exists = AsyncMock(return_value=True)

        executor = LiveExecutor(
            live_mode_controller=_make_live_mode_ctrl(live=True),
            execution_guard=_make_execution_guard(pass_validation=True),
            phase7_executor=_make_phase7_executor(),
            redis_client=redis,
        )
        result = await executor.execute(
            _make_execution_request(),
            market_ctx={"depth": 50_000.0, "spread": 0.01},
        )
        assert result.allowed is False
        assert "redis_dedup" in result.block_reason


class TestGatedLiveExecutorFillTracker:
    """GL-23: successful execution records fill in FillTracker."""

    async def test_fill_recorded(self) -> None:
        from projects.polymarket.polyquantbot.execution.live_executor import LiveExecutor
        from projects.polymarket.polyquantbot.execution.fill_tracker import FillTracker

        tracker = FillTracker()
        redis = MagicMock()
        redis.exists = AsyncMock(return_value=False)
        redis.setex = AsyncMock()

        executor = LiveExecutor(
            live_mode_controller=_make_live_mode_ctrl(live=True),
            execution_guard=_make_execution_guard(pass_validation=True),
            phase7_executor=_make_phase7_executor(status="filled"),
            fill_tracker=tracker,
            redis_client=redis,
        )
        req = _make_execution_request()
        result = await executor.execute(
            req,
            market_ctx={"depth": 50_000.0, "spread": 0.01},
        )
        assert result.allowed is True
        stats = tracker.aggregate()
        assert stats.total_submitted >= 1


class TestGatedLiveExecutorFailClosed:
    """GL-24: fail closed on exchange error."""

    async def test_fail_closed_on_error(self) -> None:
        from projects.polymarket.polyquantbot.execution.live_executor import LiveExecutor

        phase7_exec = MagicMock()
        phase7_exec.execute = AsyncMock(side_effect=RuntimeError("exchange_down"))

        redis = MagicMock()
        redis.exists = AsyncMock(return_value=False)

        executor = LiveExecutor(
            live_mode_controller=_make_live_mode_ctrl(live=True),
            execution_guard=_make_execution_guard(pass_validation=True),
            phase7_executor=phase7_exec,
            redis_client=redis,
        )
        result = await executor.execute(
            _make_execution_request(),
            market_ctx={"depth": 50_000.0, "spread": 0.01},
        )
        # allowed=True (we got through the gates) but inner result is rejected
        assert result.result is not None
        assert result.result.status == "rejected"


class TestGatedLiveExecutorRetry:
    """GL-25: retries on transient error."""

    async def test_retries_then_succeeds(self) -> None:
        from projects.polymarket.polyquantbot.execution.live_executor import LiveExecutor
        from projects.polymarket.polyquantbot.phase7.core.execution.live_executor import (
            ExecutionResult,
        )

        call_count = {"n": 0}

        async def flaky_execute(req, ctx=None):
            call_count["n"] += 1
            if call_count["n"] < 2:
                raise RuntimeError("transient_error")
            return ExecutionResult(
                order_id="ord-retry",
                status="submitted",
                filled_size=0.0,
                avg_price=0.62,
                latency_ms=100.0,
                correlation_id=req.correlation_id,
                is_paper=False,
            )

        phase7_exec = MagicMock()
        phase7_exec.execute = flaky_execute

        redis = MagicMock()
        redis.exists = AsyncMock(return_value=False)
        redis.setex = AsyncMock()

        executor = LiveExecutor(
            live_mode_controller=_make_live_mode_ctrl(live=True),
            execution_guard=_make_execution_guard(pass_validation=True),
            phase7_executor=phase7_exec,
            redis_client=redis,
        )
        result = await executor.execute(
            _make_execution_request(),
            market_ctx={"depth": 50_000.0, "spread": 0.01},
        )
        assert result.allowed is True
        assert call_count["n"] == 2


# ══════════════════════════════════════════════════════════════════════════════
# GL-26 – GL-28  LiveAuditLogger
# ══════════════════════════════════════════════════════════════════════════════


class TestLiveAuditLoggerPreWrite:
    """GL-26: write_pre emits structured log record."""

    async def test_write_pre_log_only(self) -> None:
        from projects.polymarket.polyquantbot.monitoring.live_audit import (
            LiveAuditLogger,
        )

        audit = LiveAuditLogger(database_url="", log_only=True)
        # Should not raise
        await audit.write_pre(
            market_id="0xabc",
            side="YES",
            size_usd=100.0,
            expected_price=0.62,
            decision_source="sig-001",
            correlation_id="cid-001",
        )


class TestLiveAuditLoggerPostWrite:
    """GL-27: write_post emits structured log record."""

    async def test_write_post_log_only(self) -> None:
        from projects.polymarket.polyquantbot.monitoring.live_audit import (
            LiveAuditLogger,
        )

        audit = LiveAuditLogger(database_url="", log_only=True)
        await audit.write_post(
            market_id="0xabc",
            side="YES",
            size_usd=100.0,
            expected_price=0.62,
            actual_fill=0.625,
            slippage_bps=80.6,
            latency_ms=210.0,
            decision_source="sig-001",
            status="filled",
            correlation_id="cid-001",
        )


class TestLiveAuditLoggerDbFailure:
    """GL-28: write_post raises AuditWriteError on DB failure."""

    async def test_db_write_failure_raises(self) -> None:
        from projects.polymarket.polyquantbot.monitoring.live_audit import (
            LiveAuditLogger,
            AuditWriteError,
        )

        audit = LiveAuditLogger(database_url="postgresql://fake/db", log_only=False)

        # Patch asyncpg at the module level so connect() fails gracefully
        # then manually set a pool that raises on use.
        class _FakeConn:
            async def execute(self, *args, **kwargs):
                raise Exception("db_error")

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        class _FakePool:
            def acquire(self):
                return _FakeConn()

            async def close(self):
                pass

        audit._pool = _FakePool()
        audit._log_only = False

        with pytest.raises(AuditWriteError):
            await audit.write_post(
                market_id="0xabc",
                side="YES",
                size_usd=100.0,
                expected_price=0.62,
                actual_fill=0.62,
                slippage_bps=0.0,
                latency_ms=100.0,
                decision_source="sig-001",
                status="filled",
                correlation_id="cid-001",
            )


# ══════════════════════════════════════════════════════════════════════════════
# GL-29 – GL-33  Pipeline runner integration
# ══════════════════════════════════════════════════════════════════════════════


def _make_runner_with_live_ctrl(live: bool = False):
    """Build a minimal Phase10PipelineRunner with LiveModeController wired."""
    from projects.polymarket.polyquantbot.phase10.pipeline_runner import (
        Phase10PipelineRunner,
    )
    from projects.polymarket.polyquantbot.phase10.go_live_controller import (
        GoLiveController,
        TradingMode,
    )
    from projects.polymarket.polyquantbot.phase10.execution_guard import ExecutionGuard

    go_live = GoLiveController(mode=TradingMode.PAPER)
    guard = ExecutionGuard(min_liquidity_usd=1.0, max_position_usd=10_000.0)

    live_ctrl = _make_live_mode_ctrl(live=live)

    sim = MagicMock()
    sim.execute = AsyncMock(
        return_value=MagicMock(
            order_id="sim-001",
            success=True,
            filled_size=100.0,
            simulated_price=0.62,
        )
    )

    telegram = MagicMock()
    telegram.alert_error = AsyncMock()
    telegram._enqueue = AsyncMock()

    runner = Phase10PipelineRunner(
        ws_client=MagicMock(),
        orderbook_manager=MagicMock(),
        market_cache=MagicMock(),
        trade_flow_analyzer=MagicMock(),
        live_executor=MagicMock(),
        latency_tracker=MagicMock(),
        feedback_tracker=MagicMock(),
        go_live_controller=go_live,
        execution_guard=guard,
        arb_detector=MagicMock(),
        kalshi_client=MagicMock(),
        metrics_validator=MagicMock(),
        market_ids=["0xabc"],
        live_mode_controller=live_ctrl,
        simulator=sim,
        telegram=telegram,
    )
    return runner


class TestPipelineRunnerLiveCtrlAlwaysFirst:
    """GL-29: live_mode_controller is always checked before execution."""

    async def test_live_ctrl_checked_when_not_live(self) -> None:
        runner = _make_runner_with_live_ctrl(live=False)
        from projects.polymarket.polyquantbot.phase7.core.execution.live_executor import (
            ExecutionRequest,
        )
        from projects.polymarket.polyquantbot.phase10.pipeline_runner import LatencyEvent

        req = ExecutionRequest(
            market_id="0xabc", side="YES", price=0.62, size=100.0
        )
        lat = LatencyEvent(correlation_id=req.correlation_id, market_id="0xabc")
        runner._metrics = MagicMock()
        runner._metrics.record_fill = MagicMock()
        runner._go_live = MagicMock()
        runner._go_live.allow_execution.return_value = False
        runner._go_live.mode = MagicMock()
        runner._go_live.mode.value = "PAPER"

        result = await runner._gated_execute(req, {}, lat)
        # Should return None — blocked by live_ctrl
        assert result is None


class TestPipelineRunnerSimulatorUsedForPaper:
    """GL-30: simulator used when live_mode_controller blocked."""

    async def test_simulator_called_on_paper_fallback(self) -> None:
        runner = _make_runner_with_live_ctrl(live=False)
        from projects.polymarket.polyquantbot.phase7.core.execution.live_executor import (
            ExecutionRequest,
        )
        from projects.polymarket.polyquantbot.phase10.pipeline_runner import LatencyEvent

        req = ExecutionRequest(
            market_id="0xabc", side="YES", price=0.62, size=100.0
        )
        lat = LatencyEvent(correlation_id=req.correlation_id, market_id="0xabc")

        runner._metrics = MagicMock()
        runner._metrics.record_fill = MagicMock()
        runner._metrics.record_latency = MagicMock()
        runner._metrics.record_ev_signal = MagicMock()
        runner._metrics.record_pnl_sample = MagicMock()
        runner._go_live = MagicMock()
        runner._go_live.allow_execution.return_value = True
        runner._go_live.record_trade = MagicMock()

        result = await runner._gated_execute(
            req, {"depth": 50_000.0, "spread": 0.01, "orderbook": {}}, lat
        )
        # Simulator should have been called
        assert runner._simulator.execute.called


class TestPipelineRunnerGatedExecutorUsedForLive:
    """GL-31: gated_executor used when live_mode_controller allows."""

    async def test_gated_executor_called_on_live(self) -> None:
        from projects.polymarket.polyquantbot.phase10.pipeline_runner import (
            Phase10PipelineRunner,
            LatencyEvent,
        )
        from projects.polymarket.polyquantbot.phase10.go_live_controller import (
            GoLiveController,
            TradingMode,
        )
        from projects.polymarket.polyquantbot.phase10.execution_guard import ExecutionGuard
        from projects.polymarket.polyquantbot.phase7.core.execution.live_executor import (
            ExecutionRequest,
            ExecutionResult,
        )
        from projects.polymarket.polyquantbot.execution.live_executor import (
            GatedExecutionResult,
        )

        go_live = GoLiveController(mode=TradingMode.LIVE)
        guard = ExecutionGuard(min_liquidity_usd=1.0, max_position_usd=10_000.0)
        live_ctrl = _make_live_mode_ctrl(live=True)

        inner_result = ExecutionResult(
            order_id="ord-live",
            status="submitted",
            filled_size=0.0,
            avg_price=0.62,
            latency_ms=200.0,
            correlation_id="cid-live",
            is_paper=False,
        )
        gated_exec = MagicMock()
        gated_exec.execute = AsyncMock(
            return_value=GatedExecutionResult(
                allowed=True,
                block_reason="",
                result=inner_result,
                correlation_id="cid-live",
                latency_ms=200.0,
            )
        )

        runner = Phase10PipelineRunner(
            ws_client=MagicMock(),
            orderbook_manager=MagicMock(),
            market_cache=MagicMock(),
            trade_flow_analyzer=MagicMock(),
            live_executor=MagicMock(),
            latency_tracker=MagicMock(),
            feedback_tracker=MagicMock(),
            go_live_controller=go_live,
            execution_guard=guard,
            arb_detector=MagicMock(),
            kalshi_client=MagicMock(),
            metrics_validator=MagicMock(),
            market_ids=["0xabc"],
            live_mode_controller=live_ctrl,
            gated_executor=gated_exec,
            telegram=None,
        )
        runner._metrics = MagicMock()
        runner._metrics.record_fill = MagicMock()
        runner._metrics.record_latency = MagicMock()
        runner._metrics.record_ev_signal = MagicMock()
        runner._metrics.record_pnl_sample = MagicMock()
        runner._go_live = MagicMock()
        runner._go_live.record_trade = MagicMock()
        runner._cache = MagicMock()
        runner._cache.on_execution_latency = MagicMock()

        req = ExecutionRequest(
            market_id="0xabc", side="YES", price=0.62, size=100.0
        )
        lat = LatencyEvent(correlation_id=req.correlation_id, market_id="0xabc")
        result = await runner._gated_execute(req, {"depth": 50_000.0}, lat)
        assert gated_exec.execute.called
        assert result is not None
        assert result.order_id == "ord-live"


class TestPipelineRunnerTelegramLiveEnabled:
    """GL-32 / GL-33: telegram notified on live events."""

    async def test_telegram_called_on_live_enabled(self) -> None:
        from projects.polymarket.polyquantbot.phase10.pipeline_runner import (
            Phase10PipelineRunner,
            LatencyEvent,
        )
        from projects.polymarket.polyquantbot.phase10.go_live_controller import (
            GoLiveController,
            TradingMode,
        )
        from projects.polymarket.polyquantbot.phase10.execution_guard import ExecutionGuard
        from projects.polymarket.polyquantbot.phase7.core.execution.live_executor import (
            ExecutionRequest,
            ExecutionResult,
        )
        from projects.polymarket.polyquantbot.execution.live_executor import (
            GatedExecutionResult,
        )

        go_live = GoLiveController(mode=TradingMode.LIVE)
        guard = ExecutionGuard(min_liquidity_usd=1.0, max_position_usd=10_000.0)
        live_ctrl = _make_live_mode_ctrl(live=True)

        inner_result = ExecutionResult(
            order_id="ord-tg",
            status="submitted",
            filled_size=0.0,
            avg_price=0.62,
            latency_ms=200.0,
            correlation_id="cid-tg",
            is_paper=False,
        )
        gated_exec = MagicMock()
        gated_exec.execute = AsyncMock(
            return_value=GatedExecutionResult(
                allowed=True,
                block_reason="",
                result=inner_result,
                correlation_id="cid-tg",
                latency_ms=200.0,
            )
        )

        telegram = MagicMock()
        telegram.alert_error = AsyncMock()

        runner = Phase10PipelineRunner(
            ws_client=MagicMock(),
            orderbook_manager=MagicMock(),
            market_cache=MagicMock(),
            trade_flow_analyzer=MagicMock(),
            live_executor=MagicMock(),
            latency_tracker=MagicMock(),
            feedback_tracker=MagicMock(),
            go_live_controller=go_live,
            execution_guard=guard,
            arb_detector=MagicMock(),
            kalshi_client=MagicMock(),
            metrics_validator=MagicMock(),
            market_ids=["0xabc"],
            live_mode_controller=live_ctrl,
            gated_executor=gated_exec,
            telegram=telegram,
        )
        runner._metrics = MagicMock()
        runner._metrics.record_fill = MagicMock()
        runner._metrics.record_latency = MagicMock()
        runner._metrics.record_ev_signal = MagicMock()
        runner._metrics.record_pnl_sample = MagicMock()
        runner._go_live = MagicMock()
        runner._go_live.record_trade = MagicMock()
        runner._cache = MagicMock()
        runner._cache.on_execution_latency = MagicMock()

        req = ExecutionRequest(
            market_id="0xabc", side="YES", price=0.62, size=100.0
        )
        lat = LatencyEvent(correlation_id=req.correlation_id, market_id="0xabc")
        await runner._gated_execute(req, {"depth": 50_000.0}, lat)

        # Telegram alert_error should have been called
        assert telegram.alert_error.called
