"""Phase 14 — Live Deployment Stage 1 Test Suite.

Validates the LiveDeploymentStage1 controller and the new
format_live_stage1_activated() Telegram formatter.

LS-01  CONFIG — apply_live_config succeeds with ENABLE_LIVE_TRADING=true + LIVE mode
LS-02  CONFIG — apply_live_config raises LiveModeGuardError without ENABLE_LIVE_TRADING
LS-03  CONFIG — apply_live_config sets config_applied=True on success
LS-04  CONFIG — apply_live_config overrides Stage 1 limits (2%/5%/2/5%)
LS-05  DRY VALIDATE — dry_validate returns passed=True in LIVE mode with valid config
LS-06  DRY VALIDATE — execution_path_live=True after LIVE mode config applied
LS-07  DRY VALIDATE — order_creation_ok=True (ExecutionRequest can be constructed)
LS-08  DRY VALIDATE — go_live_allowed=True after stub metrics loaded
LS-09  DRY VALIDATE — dry_validate returns passed=False when mode is not LIVE
LS-10  ENABLE EXECUTION — enable_execution raises RuntimeError if config not applied
LS-11  ENABLE EXECUTION — enable_execution sets execution_enabled=True
LS-12  ENABLE EXECUTION — enable_execution is idempotent (safe to call twice)
LS-13  MONITOR TRADE — normal trade produces anomaly=False record
LS-14  MONITOR TRADE — rejected status triggers anomaly=True
LS-15  MONITOR TRADE — slippage > 5% triggers anomaly=True
LS-16  MONITOR TRADE — unexpected allocation triggers anomaly=True
LS-17  FAIL-SAFE — anomaly trade triggers fail_safe_triggered=True
LS-18  FAIL-SAFE — fail-safe halts system_state
LS-19  FAIL-SAFE — fail-safe sends Telegram kill alert
LS-20  FAIL-SAFE — fail-safe is idempotent (second anomaly does not re-call halt)
LS-21  STATUS — status() returns all expected keys
LS-22  STATUS — safety_watch_active=False after 10 trades monitored
LS-23  ACTIVATION ALERT — send_activation_alert calls telegram _enqueue
LS-24  ACTIVATION ALERT — format_live_stage1_activated starts with '🚀'
LS-25  ACTIVATION ALERT — format_live_stage1_activated contains LIVE TRADING ACTIVATED
LS-26  ACTIVATION ALERT — format_live_stage1_activated includes bankroll and limits
LS-27  ACTIVATION ALERT — format_live_stage1_activated includes active strategies
LS-28  TRADE RECORD — to_dict returns all expected keys
LS-29  DRY VALIDATE — to_dict returns all expected keys
LS-30  CONFIG — GoLiveController allow_execution=True after apply_live_config
"""
from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import dataclass
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_system_state() -> MagicMock:
    ss = MagicMock()
    ss.halt = AsyncMock()
    return ss


def _make_telegram() -> MagicMock:
    tg = MagicMock()
    tg._enqueue = AsyncMock()
    tg.alert_error = AsyncMock()
    return tg


def _make_metrics(
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


def _live_env() -> dict:
    return {
        "TRADING_MODE": "LIVE",
        "ENABLE_LIVE_TRADING": "true",
        "MAX_POSITION_FRACTION": "0.02",
        "MAX_CONCURRENT_TRADES": "2",
        "DAILY_LOSS_LIMIT": "-2000",
        "DRAWDOWN_LIMIT": "0.05",
        "MIN_LIQUIDITY_USD": "10000",
        "SIGNAL_EDGE_THRESHOLD": "0.05",
    }


# ─────────────────────────────────────────────────────────────────────────────
# LS-01 – LS-04: CONFIG
# ─────────────────────────────────────────────────────────────────────────────


class TestApplyLiveConfig:
    """LS-01 – LS-04: apply_live_config tests."""

    def test_ls01_apply_live_config_succeeds(self) -> None:
        """LS-01: apply_live_config succeeds with ENABLE_LIVE_TRADING=true."""
        from projects.polymarket.polyquantbot.core.live_deployment_stage1 import (
            LiveDeploymentStage1,
        )
        from projects.polymarket.polyquantbot.config.live_config import LiveConfig
        from projects.polymarket.polyquantbot.core.pipeline.go_live_controller import TradingMode

        with patch.dict(os.environ, _live_env(), clear=False):
            cfg = LiveConfig.from_env()
            stage1 = LiveDeploymentStage1(bankroll=10_000.0)
            stage1.apply_live_config(live_config=cfg)
            assert stage1.config_applied is True

    def test_ls02_apply_live_config_raises_guard_error(self) -> None:
        """LS-02: apply_live_config raises LiveModeGuardError without ENABLE_LIVE_TRADING."""
        from projects.polymarket.polyquantbot.core.live_deployment_stage1 import (
            LiveDeploymentStage1,
        )
        from projects.polymarket.polyquantbot.config.live_config import (
            LiveConfig,
            LiveModeGuardError,
        )

        env = {**_live_env(), "ENABLE_LIVE_TRADING": "false"}
        with patch.dict(os.environ, env, clear=False):
            cfg = LiveConfig.from_env()
            stage1 = LiveDeploymentStage1()
            with pytest.raises(LiveModeGuardError):
                stage1.apply_live_config(live_config=cfg)

    def test_ls03_apply_live_config_sets_config_applied(self) -> None:
        """LS-03: config_applied is False before and True after apply_live_config."""
        from projects.polymarket.polyquantbot.core.live_deployment_stage1 import (
            LiveDeploymentStage1,
        )
        from projects.polymarket.polyquantbot.config.live_config import LiveConfig

        with patch.dict(os.environ, _live_env(), clear=False):
            cfg = LiveConfig.from_env()
            stage1 = LiveDeploymentStage1()
            assert stage1.config_applied is False
            stage1.apply_live_config(live_config=cfg)
            assert stage1.config_applied is True

    def test_ls04_apply_live_config_stage1_limits(self) -> None:
        """LS-04: Stage 1 limits are applied (2%/5%/2/5%)."""
        from projects.polymarket.polyquantbot.core.live_deployment_stage1 import (
            LiveDeploymentStage1,
        )
        from projects.polymarket.polyquantbot.config.live_config import LiveConfig

        with patch.dict(os.environ, _live_env(), clear=False):
            cfg = LiveConfig.from_env()
            stage1 = LiveDeploymentStage1(
                bankroll=10_000.0,
                max_position_fraction=0.02,
                max_total_exposure=0.05,
                max_concurrent_trades=2,
                drawdown_limit=0.05,
            )
            stage1.apply_live_config(live_config=cfg)
            s = stage1.status()
            assert s["max_position_fraction"] == pytest.approx(0.02)
            assert s["max_total_exposure"] == pytest.approx(0.05)
            assert s["max_concurrent_trades"] == 2
            assert s["drawdown_limit"] == pytest.approx(0.05)


# ─────────────────────────────────────────────────────────────────────────────
# LS-05 – LS-09: DRY VALIDATE
# ─────────────────────────────────────────────────────────────────────────────


class TestDryValidate:
    """LS-05 – LS-09: dry_validate tests."""

    def _make_live_stage1(self) -> "LiveDeploymentStage1":
        from projects.polymarket.polyquantbot.core.live_deployment_stage1 import (
            LiveDeploymentStage1,
        )
        from projects.polymarket.polyquantbot.config.live_config import LiveConfig

        with patch.dict(os.environ, _live_env(), clear=False):
            cfg = LiveConfig.from_env()
        stage1 = LiveDeploymentStage1(bankroll=10_000.0)
        stage1.apply_live_config(live_config=cfg)
        return stage1

    def test_ls05_dry_validate_passed_true(self) -> None:
        """LS-05: dry_validate returns passed=True in LIVE mode with valid config."""
        with patch.dict(os.environ, _live_env(), clear=False):
            stage1 = self._make_live_stage1()
            result = stage1.dry_validate()
            assert result.passed is True

    def test_ls06_execution_path_live(self) -> None:
        """LS-06: execution_path_live=True after LIVE mode config applied."""
        with patch.dict(os.environ, _live_env(), clear=False):
            stage1 = self._make_live_stage1()
            result = stage1.dry_validate()
            assert result.execution_path_live is True

    def test_ls07_order_creation_ok(self) -> None:
        """LS-07: order_creation_ok=True (ExecutionRequest can be constructed)."""
        with patch.dict(os.environ, _live_env(), clear=False):
            stage1 = self._make_live_stage1()
            result = stage1.dry_validate()
            assert result.order_creation_ok is True

    def test_ls08_go_live_allowed_with_stub_metrics(self) -> None:
        """LS-08: go_live_allowed=True after stub metrics loaded."""
        with patch.dict(os.environ, _live_env(), clear=False):
            stage1 = self._make_live_stage1()
            result = stage1.dry_validate()
            assert result.go_live_allowed is True

    def test_ls09_dry_validate_not_live_when_paper_mode(self) -> None:
        """LS-09: dry_validate returns passed=False when controller mode is not LIVE."""
        from projects.polymarket.polyquantbot.core.live_deployment_stage1 import (
            LiveDeploymentStage1,
        )
        from projects.polymarket.polyquantbot.config.live_config import LiveConfig
        from projects.polymarket.polyquantbot.core.pipeline.go_live_controller import (
            GoLiveController,
            TradingMode,
        )

        env = {**_live_env(), "TRADING_MODE": "PAPER"}
        with patch.dict(os.environ, env, clear=False):
            cfg = LiveConfig.from_env()
        # Build a PAPER mode controller explicitly
        paper_ctrl = GoLiveController(mode=TradingMode.PAPER)
        stage1 = LiveDeploymentStage1()
        # Manually inject paper controller — bypass validate guard
        stage1._live_config = cfg
        stage1._go_live_controller = paper_ctrl
        stage1._config_applied = True
        result = stage1.dry_validate()
        assert result.execution_path_live is False
        assert result.passed is False


# ─────────────────────────────────────────────────────────────────────────────
# LS-10 – LS-12: ENABLE EXECUTION
# ─────────────────────────────────────────────────────────────────────────────


class TestEnableExecution:
    """LS-10 – LS-12: enable_execution tests."""

    def test_ls10_enable_execution_raises_without_config(self) -> None:
        """LS-10: enable_execution raises RuntimeError if config not applied."""
        from projects.polymarket.polyquantbot.core.live_deployment_stage1 import (
            LiveDeploymentStage1,
        )

        stage1 = LiveDeploymentStage1()
        with pytest.raises(RuntimeError, match="apply_live_config"):
            stage1.enable_execution()

    def test_ls11_enable_execution_sets_flag(self) -> None:
        """LS-11: enable_execution sets execution_enabled=True."""
        from projects.polymarket.polyquantbot.core.live_deployment_stage1 import (
            LiveDeploymentStage1,
        )
        from projects.polymarket.polyquantbot.config.live_config import LiveConfig

        with patch.dict(os.environ, _live_env(), clear=False):
            cfg = LiveConfig.from_env()
        stage1 = LiveDeploymentStage1()
        stage1.apply_live_config(live_config=cfg)
        assert stage1.execution_enabled is False
        stage1.enable_execution()
        assert stage1.execution_enabled is True

    def test_ls12_enable_execution_idempotent(self) -> None:
        """LS-12: enable_execution is idempotent (calling twice is safe)."""
        from projects.polymarket.polyquantbot.core.live_deployment_stage1 import (
            LiveDeploymentStage1,
        )
        from projects.polymarket.polyquantbot.config.live_config import LiveConfig

        with patch.dict(os.environ, _live_env(), clear=False):
            cfg = LiveConfig.from_env()
        stage1 = LiveDeploymentStage1()
        stage1.apply_live_config(live_config=cfg)
        stage1.enable_execution()
        stage1.enable_execution()  # second call
        assert stage1.execution_enabled is True


# ─────────────────────────────────────────────────────────────────────────────
# LS-13 – LS-16: MONITOR TRADE
# ─────────────────────────────────────────────────────────────────────────────


class TestMonitorTrade:
    """LS-13 – LS-16: monitor_trade tests."""

    async def test_ls13_normal_trade_no_anomaly(self) -> None:
        """LS-13: normal trade produces anomaly=False record."""
        from projects.polymarket.polyquantbot.core.live_deployment_stage1 import (
            LiveDeploymentStage1,
        )

        stage1 = LiveDeploymentStage1(bankroll=10_000.0)
        record = await stage1.monitor_trade(
            market_id="0xabc",
            side="YES",
            expected_price=0.60,
            fill_price=0.601,   # 0.1% slippage — well within threshold
            size_usd=180.0,     # 1.8% of 10k — within 2% cap
            status="filled",
        )
        assert record.anomaly is False
        assert record.anomaly_reason == ""

    async def test_ls14_rejected_triggers_anomaly(self) -> None:
        """LS-14: rejected status triggers anomaly=True."""
        from projects.polymarket.polyquantbot.core.live_deployment_stage1 import (
            LiveDeploymentStage1,
        )

        stage1 = LiveDeploymentStage1(bankroll=10_000.0)
        record = await stage1.monitor_trade(
            market_id="0xdef",
            side="NO",
            expected_price=0.40,
            fill_price=0.40,
            size_usd=100.0,
            status="rejected",
        )
        assert record.anomaly is True
        assert "execution_failure" in record.anomaly_reason

    async def test_ls15_high_slippage_triggers_anomaly(self) -> None:
        """LS-15: slippage > 5% triggers anomaly=True."""
        from projects.polymarket.polyquantbot.core.live_deployment_stage1 import (
            LiveDeploymentStage1,
        )

        stage1 = LiveDeploymentStage1(bankroll=10_000.0)
        record = await stage1.monitor_trade(
            market_id="0xghi",
            side="YES",
            expected_price=0.50,
            fill_price=0.56,    # 6% slippage
            size_usd=100.0,
            status="filled",
        )
        assert record.anomaly is True
        assert "slippage" in record.anomaly_reason

    async def test_ls16_unexpected_allocation_triggers_anomaly(self) -> None:
        """LS-16: unexpected allocation triggers anomaly=True."""
        from projects.polymarket.polyquantbot.core.live_deployment_stage1 import (
            LiveDeploymentStage1,
        )

        stage1 = LiveDeploymentStage1(
            bankroll=10_000.0,
            max_position_fraction=0.02,  # 2% = $200 max
        )
        record = await stage1.monitor_trade(
            market_id="0xjkl",
            side="YES",
            expected_price=0.70,
            fill_price=0.70,
            size_usd=300.0,   # 3% — exceeds 2% × 1.05 tolerance
            status="filled",
        )
        assert record.anomaly is True
        assert "allocation" in record.anomaly_reason


# ─────────────────────────────────────────────────────────────────────────────
# LS-17 – LS-20: FAIL-SAFE
# ─────────────────────────────────────────────────────────────────────────────


class TestFailSafe:
    """LS-17 – LS-20: fail-safe tests."""

    async def test_ls17_anomaly_triggers_fail_safe(self) -> None:
        """LS-17: anomaly trade sets fail_safe_triggered=True."""
        from projects.polymarket.polyquantbot.core.live_deployment_stage1 import (
            LiveDeploymentStage1,
        )

        stage1 = LiveDeploymentStage1()
        assert stage1.fail_safe_triggered is False
        await stage1.monitor_trade(
            market_id="0xm", side="YES",
            expected_price=0.5, fill_price=0.5,
            size_usd=10.0, status="rejected",
        )
        assert stage1.fail_safe_triggered is True

    async def test_ls18_fail_safe_halts_system_state(self) -> None:
        """LS-18: fail-safe calls system_state.halt()."""
        from projects.polymarket.polyquantbot.core.live_deployment_stage1 import (
            LiveDeploymentStage1,
        )

        ss = _make_system_state()
        stage1 = LiveDeploymentStage1(system_state=ss)
        await stage1.monitor_trade(
            market_id="0xn", side="NO",
            expected_price=0.4, fill_price=0.4,
            size_usd=10.0, status="rejected",
        )
        ss.halt.assert_awaited_once()

    async def test_ls19_fail_safe_sends_kill_alert(self) -> None:
        """LS-19: fail-safe sends Telegram kill alert."""
        from projects.polymarket.polyquantbot.core.live_deployment_stage1 import (
            LiveDeploymentStage1,
        )

        tg = _make_telegram()
        stage1 = LiveDeploymentStage1(telegram=tg)
        await stage1.monitor_trade(
            market_id="0xo", side="YES",
            expected_price=0.6, fill_price=0.6,
            size_usd=10.0, status="rejected",
        )
        # Either _enqueue or alert_error should have been called
        called = tg._enqueue.called or tg.alert_error.called
        assert called is True

    async def test_ls20_fail_safe_idempotent(self) -> None:
        """LS-20: fail-safe is idempotent — second anomaly does not re-call halt."""
        from projects.polymarket.polyquantbot.core.live_deployment_stage1 import (
            LiveDeploymentStage1,
        )

        ss = _make_system_state()
        stage1 = LiveDeploymentStage1(system_state=ss)
        # First anomaly
        await stage1.monitor_trade(
            market_id="0xp", side="YES",
            expected_price=0.5, fill_price=0.5,
            size_usd=10.0, status="rejected",
        )
        # Second anomaly — should not call halt again
        await stage1.monitor_trade(
            market_id="0xq", side="NO",
            expected_price=0.5, fill_price=0.5,
            size_usd=10.0, status="rejected",
        )
        assert ss.halt.await_count == 1


# ─────────────────────────────────────────────────────────────────────────────
# LS-21 – LS-22: STATUS
# ─────────────────────────────────────────────────────────────────────────────


class TestStatus:
    """LS-21 – LS-22: status() tests."""

    def test_ls21_status_returns_all_keys(self) -> None:
        """LS-21: status() returns all expected keys."""
        from projects.polymarket.polyquantbot.core.live_deployment_stage1 import (
            LiveDeploymentStage1,
        )

        stage1 = LiveDeploymentStage1()
        s = stage1.status()
        expected_keys = {
            "config_applied", "execution_enabled", "fail_safe_triggered",
            "trades_monitored", "anomalies_detected", "safety_watch_active",
            "max_position_fraction", "max_total_exposure", "max_concurrent_trades",
            "drawdown_limit", "bankroll", "active_strategies",
        }
        assert expected_keys.issubset(set(s.keys()))

    async def test_ls22_safety_watch_inactive_after_ten_trades(self) -> None:
        """LS-22: safety_watch_active=False after 10 trades monitored."""
        from projects.polymarket.polyquantbot.core.live_deployment_stage1 import (
            LiveDeploymentStage1,
        )

        stage1 = LiveDeploymentStage1(bankroll=10_000.0, safety_watch_trades=10)
        for i in range(10):
            await stage1.monitor_trade(
                market_id=f"0x{i:03d}", side="YES",
                expected_price=0.50, fill_price=0.501,
                size_usd=100.0, status="filled",
            )
        assert stage1.status()["safety_watch_active"] is False


# ─────────────────────────────────────────────────────────────────────────────
# LS-23: ACTIVATION ALERT
# ─────────────────────────────────────────────────────────────────────────────


class TestActivationAlert:
    """LS-23: send_activation_alert tests."""

    async def test_ls23_send_activation_alert_calls_telegram(self) -> None:
        """LS-23: send_activation_alert calls telegram _enqueue."""
        from projects.polymarket.polyquantbot.core.live_deployment_stage1 import (
            LiveDeploymentStage1,
        )

        tg = _make_telegram()
        stage1 = LiveDeploymentStage1(telegram=tg, active_strategies=["ev_momentum"])
        await stage1.send_activation_alert(correlation_id="test-session")
        assert tg._enqueue.called or tg.alert_error.called


# ─────────────────────────────────────────────────────────────────────────────
# LS-24 – LS-27: FORMAT LIVE STAGE1 ACTIVATED
# ─────────────────────────────────────────────────────────────────────────────


class TestFormatLiveStage1Activated:
    """LS-24 – LS-27: format_live_stage1_activated() tests."""

    def test_ls24_starts_with_rocket_emoji(self) -> None:
        """LS-24: format_live_stage1_activated starts with '🚀'."""
        from projects.polymarket.polyquantbot.telegram.message_formatter import (
            format_live_stage1_activated,
        )

        msg = format_live_stage1_activated(
            mode="LIVE",
            bankroll=10_000.0,
            max_position_pct=2.0,
            max_total_exposure_pct=5.0,
            max_concurrent_trades=2,
            drawdown_limit_pct=5.0,
            active_strategies=["ev_momentum"],
        )
        assert msg.startswith("🚀")

    def test_ls25_contains_stage1_activated(self) -> None:
        """LS-25: format_live_stage1_activated contains 'LIVE TRADING ACTIVATED'."""
        from projects.polymarket.polyquantbot.telegram.message_formatter import (
            format_live_stage1_activated,
        )

        msg = format_live_stage1_activated(
            mode="LIVE",
            bankroll=10_000.0,
            max_position_pct=2.0,
            max_total_exposure_pct=5.0,
            max_concurrent_trades=2,
            drawdown_limit_pct=5.0,
            active_strategies=[],
        )
        assert "LIVE TRADING ACTIVATED" in msg

    def test_ls26_includes_bankroll_and_limits(self) -> None:
        """LS-26: format_live_stage1_activated includes bankroll and stage limits."""
        from projects.polymarket.polyquantbot.telegram.message_formatter import (
            format_live_stage1_activated,
        )

        msg = format_live_stage1_activated(
            mode="LIVE",
            bankroll=12_500.0,
            max_position_pct=2.0,
            max_total_exposure_pct=5.0,
            max_concurrent_trades=2,
            drawdown_limit_pct=5.0,
            active_strategies=[],
        )
        assert "12500.00" in msg
        assert "2.0%" in msg
        assert "5.0%" in msg

    def test_ls27_includes_active_strategies(self) -> None:
        """LS-27: format_live_stage1_activated includes active strategy names."""
        from projects.polymarket.polyquantbot.telegram.message_formatter import (
            format_live_stage1_activated,
        )

        msg = format_live_stage1_activated(
            mode="LIVE",
            bankroll=10_000.0,
            max_position_pct=2.0,
            max_total_exposure_pct=5.0,
            max_concurrent_trades=2,
            drawdown_limit_pct=5.0,
            active_strategies=["ev_momentum", "mean_reversion"],
        )
        assert "ev_momentum" in msg
        assert "mean_reversion" in msg


# ─────────────────────────────────────────────────────────────────────────────
# LS-28 – LS-29: TO_DICT
# ─────────────────────────────────────────────────────────────────────────────


class TestToDicts:
    """LS-28 – LS-29: to_dict serialization tests."""

    async def test_ls28_trade_record_to_dict(self) -> None:
        """LS-28: Stage1TradeRecord.to_dict() returns all expected keys."""
        from projects.polymarket.polyquantbot.core.live_deployment_stage1 import (
            LiveDeploymentStage1,
        )

        stage1 = LiveDeploymentStage1(bankroll=10_000.0)
        record = await stage1.monitor_trade(
            market_id="0xabc",
            side="YES",
            expected_price=0.60,
            fill_price=0.602,
            size_usd=100.0,
            status="filled",
            correlation_id="cid-test",
        )
        d = record.to_dict()
        expected_keys = {
            "trade_number", "market_id", "side", "expected_price",
            "fill_price", "size_usd", "status", "slippage", "anomaly",
            "anomaly_reason", "correlation_id",
        }
        assert expected_keys.issubset(set(d.keys()))

    def test_ls29_dry_validation_result_to_dict(self) -> None:
        """LS-29: DryValidationResult.to_dict() returns all expected keys."""
        from projects.polymarket.polyquantbot.core.live_deployment_stage1 import (
            LiveDeploymentStage1,
        )
        from projects.polymarket.polyquantbot.config.live_config import LiveConfig

        with patch.dict(os.environ, _live_env(), clear=False):
            cfg = LiveConfig.from_env()
        stage1 = LiveDeploymentStage1()
        stage1.apply_live_config(live_config=cfg)
        result = stage1.dry_validate()
        d = result.to_dict()
        expected_keys = {
            "execution_path_live", "order_creation_ok", "config_validated",
            "go_live_allowed", "passed", "failure_reason",
        }
        assert expected_keys.issubset(set(d.keys()))


# ─────────────────────────────────────────────────────────────────────────────
# LS-30: GO-LIVE CONTROLLER
# ─────────────────────────────────────────────────────────────────────────────


class TestGoLiveControllerPostConfig:
    """LS-30: GoLiveController allow_execution after apply_live_config."""

    def test_ls30_go_live_controller_allows_execution(self) -> None:
        """LS-30: GoLiveController.allow_execution()=True after apply_live_config."""
        from projects.polymarket.polyquantbot.core.live_deployment_stage1 import (
            LiveDeploymentStage1,
        )
        from projects.polymarket.polyquantbot.config.live_config import LiveConfig

        with patch.dict(os.environ, _live_env(), clear=False):
            cfg = LiveConfig.from_env()
        stage1 = LiveDeploymentStage1(bankroll=10_000.0)
        stage1.apply_live_config(live_config=cfg)
        # Feed passing metrics
        stage1.dry_validate()  # populates go_live_controller with stub metrics
        assert stage1.go_live_controller is not None
        assert stage1.go_live_controller.allow_execution() is True
