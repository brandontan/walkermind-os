"""Phase 11 — Live Deployment System Test Suite.

Validates the full Phase 11 LIVE deployment infrastructure:

  LD-01  LIVE CONFIG — from_env defaults to PAPER mode
  LD-02  LIVE CONFIG — from_env reads TRADING_MODE=LIVE
  LD-03  LIVE CONFIG — validate raises LiveModeGuardError without ENABLE_LIVE_TRADING
  LD-04  LIVE CONFIG — validate passes with ENABLE_LIVE_TRADING=true in LIVE mode
  LD-05  LIVE CONFIG — validate raises ValueError for out-of-bounds max_position
  LD-06  LIVE CONFIG — validate raises ValueError for non-negative daily_loss_limit
  LD-07  LIVE CONFIG — validate raises ValueError for out-of-bounds drawdown_limit
  LD-08  LIVE CONFIG — validate raises ValueError for non-positive edge_threshold
  LD-09  LIVE CONFIG — to_dict returns all expected keys
  LD-10  LIVE CONFIG — PAPER mode passes validate without ENABLE_LIVE_TRADING flag
  LD-11  LIVE TRADE LOGGER — log_trade emits structured log event
  LD-12  LIVE TRADE LOGGER — log_trade increments trade_count
  LD-13  LIVE TRADE LOGGER — log_trade appends to JSONL file when configured
  LD-14  LIVE TRADE LOGGER — to_dict returns canonical schema (no extra keys)
  LD-15  LIVE TRADE LOGGER — from_env reads LIVE_TRADE_LOG_FILE env var
  LD-16  LIVE TRADE LOGGER — close logs total trade count
  LD-17  LIVE TRADE LOGGER — file write error raises OSError (no silent failure)
  LD-18  STARTUP LIVE CHECKS — PAPER mode skips validation and returns immediately
  LD-19  STARTUP LIVE CHECKS — LIVE mode with passing validator returns without error
  LD-20  STARTUP LIVE CHECKS — LIVE mode with failing validator raises StartupValidationError
  LD-21  STARTUP LIVE CHECKS — StartupValidationError message contains failure reason
  LD-22  STARTUP LIVE CHECKS — Telegram alert_error called on validation failure
  LD-23  MESSAGE FORMATTER — format_live_mode_activated returns non-empty string
  LD-24  MESSAGE FORMATTER — format_live_mode_activated includes LIVE MODE ACTIVATED
  LD-25  MESSAGE FORMATTER — format_real_trade_executed returns non-empty string
  LD-26  MESSAGE FORMATTER — format_real_trade_executed includes REAL TRADE EXECUTED
  LD-27  MESSAGE FORMATTER — format_real_trade_executed shows market, side, price, size
  LD-28  LIVE EXECUTOR — live trade logger called on filled LIVE execution
  LD-29  LIVE EXECUTOR — live trade logger NOT called on PAPER execution
  LD-30  LIVE EXECUTOR — live trade logger NOT called on rejected order
  LD-31  LIVE EXECUTOR — telegram alert called on filled LIVE execution
  LD-32  LIVE EXECUTOR — live trade logger errors do not block execution result
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch, call

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
    audit = MagicMock()
    audit.is_db_connected.return_value = db_connected
    return audit


def _make_redis() -> MagicMock:
    redis = MagicMock()
    redis.exists = AsyncMock(return_value=False)
    redis.setex = AsyncMock(return_value=True)
    return redis


# ─────────────────────────────────────────────────────────────────────────────
# LD-01–LD-10: LiveConfig
# ─────────────────────────────────────────────────────────────────────────────


class TestLiveConfig:
    """LiveConfig construction and validation."""

    def test_ld01_from_env_defaults_to_paper(self, monkeypatch):
        """LD-01 from_env defaults to PAPER mode when TRADING_MODE unset."""
        monkeypatch.delenv("TRADING_MODE", raising=False)
        monkeypatch.delenv("ENABLE_LIVE_TRADING", raising=False)
        from projects.polymarket.polyquantbot.config.live_config import LiveConfig
        cfg = LiveConfig.from_env()
        from projects.polymarket.polyquantbot.phase10.go_live_controller import TradingMode
        assert cfg.trading_mode is TradingMode.PAPER

    def test_ld02_from_env_reads_live_mode(self, monkeypatch):
        """LD-02 from_env reads TRADING_MODE=LIVE."""
        monkeypatch.setenv("TRADING_MODE", "LIVE")
        monkeypatch.setenv("ENABLE_LIVE_TRADING", "true")
        from projects.polymarket.polyquantbot.config.live_config import LiveConfig
        cfg = LiveConfig.from_env()
        from projects.polymarket.polyquantbot.phase10.go_live_controller import TradingMode
        assert cfg.trading_mode is TradingMode.LIVE
        assert cfg.enable_live_trading is True

    def test_ld03_validate_raises_guard_error_without_flag(self, monkeypatch):
        """LD-03 validate raises LiveModeGuardError when LIVE without opt-in flag."""
        monkeypatch.setenv("TRADING_MODE", "LIVE")
        monkeypatch.delenv("ENABLE_LIVE_TRADING", raising=False)
        from projects.polymarket.polyquantbot.config.live_config import LiveConfig, LiveModeGuardError
        cfg = LiveConfig.from_env()
        with pytest.raises(LiveModeGuardError):
            cfg.validate()

    def test_ld04_validate_passes_with_explicit_flag(self, monkeypatch):
        """LD-04 validate passes with ENABLE_LIVE_TRADING=true."""
        monkeypatch.setenv("TRADING_MODE", "LIVE")
        monkeypatch.setenv("ENABLE_LIVE_TRADING", "true")
        from projects.polymarket.polyquantbot.config.live_config import LiveConfig
        cfg = LiveConfig.from_env()
        cfg.validate()  # Should not raise

    def test_ld05_validate_raises_for_max_position_out_of_bounds(self):
        """LD-05 validate raises ValueError for max_position > 0.10."""
        from projects.polymarket.polyquantbot.config.live_config import LiveConfig
        from projects.polymarket.polyquantbot.phase10.go_live_controller import TradingMode
        cfg = LiveConfig(
            trading_mode=TradingMode.LIVE,
            enable_live_trading=True,
            signal_debug_mode=False,
            edge_threshold=0.05,
            max_position_fraction=0.50,  # too high
            max_concurrent_trades=2,
            daily_loss_limit=-2000.0,
            drawdown_limit=0.08,
            min_liquidity_usd=10000.0,
        )
        with pytest.raises(ValueError, match="max_position_fraction"):
            cfg.validate()

    def test_ld06_validate_raises_for_non_negative_daily_loss(self):
        """LD-06 validate raises ValueError when daily_loss_limit >= 0."""
        from projects.polymarket.polyquantbot.config.live_config import LiveConfig
        from projects.polymarket.polyquantbot.phase10.go_live_controller import TradingMode
        cfg = LiveConfig(
            trading_mode=TradingMode.LIVE,
            enable_live_trading=True,
            signal_debug_mode=False,
            edge_threshold=0.05,
            max_position_fraction=0.02,
            max_concurrent_trades=2,
            daily_loss_limit=0.0,  # invalid — must be negative
            drawdown_limit=0.08,
            min_liquidity_usd=10000.0,
        )
        with pytest.raises(ValueError, match="daily_loss_limit"):
            cfg.validate()

    def test_ld07_validate_raises_for_drawdown_out_of_bounds(self):
        """LD-07 validate raises ValueError for drawdown_limit > 0.20."""
        from projects.polymarket.polyquantbot.config.live_config import LiveConfig
        from projects.polymarket.polyquantbot.phase10.go_live_controller import TradingMode
        cfg = LiveConfig(
            trading_mode=TradingMode.LIVE,
            enable_live_trading=True,
            signal_debug_mode=False,
            edge_threshold=0.05,
            max_position_fraction=0.02,
            max_concurrent_trades=2,
            daily_loss_limit=-2000.0,
            drawdown_limit=0.50,  # too high
            min_liquidity_usd=10000.0,
        )
        with pytest.raises(ValueError, match="drawdown_limit"):
            cfg.validate()

    def test_ld08_validate_raises_for_zero_edge_threshold(self):
        """LD-08 validate raises ValueError for edge_threshold <= 0."""
        from projects.polymarket.polyquantbot.config.live_config import LiveConfig
        from projects.polymarket.polyquantbot.phase10.go_live_controller import TradingMode
        cfg = LiveConfig(
            trading_mode=TradingMode.LIVE,
            enable_live_trading=True,
            signal_debug_mode=False,
            edge_threshold=0.0,  # invalid
            max_position_fraction=0.02,
            max_concurrent_trades=2,
            daily_loss_limit=-2000.0,
            drawdown_limit=0.08,
            min_liquidity_usd=10000.0,
        )
        with pytest.raises(ValueError, match="edge_threshold"):
            cfg.validate()

    def test_ld09_to_dict_returns_all_keys(self, monkeypatch):
        """LD-09 to_dict returns all expected configuration keys."""
        monkeypatch.delenv("TRADING_MODE", raising=False)
        monkeypatch.delenv("ENABLE_LIVE_TRADING", raising=False)
        from projects.polymarket.polyquantbot.config.live_config import LiveConfig
        cfg = LiveConfig.from_env()
        d = cfg.to_dict()
        expected_keys = {
            "trading_mode", "enable_live_trading", "signal_debug_mode",
            "edge_threshold", "max_position_fraction", "max_concurrent_trades",
            "daily_loss_limit", "drawdown_limit", "min_liquidity_usd",
        }
        assert expected_keys == set(d.keys())

    def test_ld10_paper_mode_validate_no_flag_required(self, monkeypatch):
        """LD-10 PAPER mode validate passes without ENABLE_LIVE_TRADING."""
        monkeypatch.setenv("TRADING_MODE", "PAPER")
        monkeypatch.delenv("ENABLE_LIVE_TRADING", raising=False)
        from projects.polymarket.polyquantbot.config.live_config import LiveConfig
        cfg = LiveConfig.from_env()
        cfg.validate()  # Should not raise in PAPER mode


# ─────────────────────────────────────────────────────────────────────────────
# LD-11–LD-17: LiveTradeLogger
# ─────────────────────────────────────────────────────────────────────────────


class TestLiveTradeLogger:
    """LiveTradeLogger logging and file I/O."""

    @pytest.mark.asyncio
    async def test_ld11_log_trade_emits_structured_log(self, caplog):
        """LD-11 log_trade emits a structured log event."""
        from projects.polymarket.polyquantbot.monitoring.live_trade_logger import LiveTradeLogger
        logger = LiveTradeLogger(log_file=None)
        event = await logger.log_trade(
            market="0xabc123",
            side="YES",
            price=0.62,
            size_usd=50.0,
            correlation_id="cid-001",
        )
        assert event.type == "REAL_TRADE"
        assert event.market == "0xabc123"
        assert event.side == "YES"
        assert event.price == 0.62
        assert event.size_usd == 50.0

    @pytest.mark.asyncio
    async def test_ld12_log_trade_increments_trade_count(self):
        """LD-12 log_trade increments trade_count."""
        from projects.polymarket.polyquantbot.monitoring.live_trade_logger import LiveTradeLogger
        logger = LiveTradeLogger(log_file=None)
        assert logger.trade_count == 0
        await logger.log_trade(market="0x1", side="YES", price=0.5, size_usd=10.0)
        await logger.log_trade(market="0x2", side="NO", price=0.4, size_usd=20.0)
        assert logger.trade_count == 2

    @pytest.mark.asyncio
    async def test_ld13_log_trade_appends_to_jsonl_file(self, tmp_path):
        """LD-13 log_trade appends valid JSON lines to the JSONL file."""
        from projects.polymarket.polyquantbot.monitoring.live_trade_logger import LiveTradeLogger
        log_file = str(tmp_path / "trades.jsonl")
        logger = LiveTradeLogger(log_file=log_file)
        await logger.log_trade(market="0xabc", side="YES", price=0.60, size_usd=100.0)
        await logger.log_trade(market="0xdef", side="NO", price=0.40, size_usd=200.0)

        lines = open(log_file).readlines()
        assert len(lines) == 2

        first = json.loads(lines[0])
        assert first["type"] == "REAL_TRADE"
        assert first["market"] == "0xabc"
        assert first["side"] == "YES"
        assert "price" in first
        assert "size_usd" in first
        assert "timestamp" in first

    @pytest.mark.asyncio
    async def test_ld14_to_dict_returns_canonical_schema(self):
        """LD-14 LiveTradeEvent.to_dict returns only the canonical 6-key schema."""
        from projects.polymarket.polyquantbot.monitoring.live_trade_logger import LiveTradeLogger
        logger = LiveTradeLogger(log_file=None)
        event = await logger.log_trade(
            market="0xabc", side="YES", price=0.60, size_usd=50.0, correlation_id="cid-x"
        )
        d = event.to_dict()
        assert set(d.keys()) == {"type", "market", "side", "price", "size_usd", "timestamp"}
        # correlation_id must NOT be in canonical dict
        assert "correlation_id" not in d

    @pytest.mark.asyncio
    async def test_ld15_from_env_reads_log_file_env(self, monkeypatch, tmp_path):
        """LD-15 from_env reads LIVE_TRADE_LOG_FILE env var."""
        log_file = str(tmp_path / "env_trades.jsonl")
        monkeypatch.setenv("LIVE_TRADE_LOG_FILE", log_file)
        from projects.polymarket.polyquantbot.monitoring.live_trade_logger import LiveTradeLogger
        logger = LiveTradeLogger.from_env()
        assert logger._log_file == log_file

    @pytest.mark.asyncio
    async def test_ld16_close_logs_total_count(self):
        """LD-16 close logs total_trades_logged without raising."""
        from projects.polymarket.polyquantbot.monitoring.live_trade_logger import LiveTradeLogger
        logger = LiveTradeLogger(log_file=None)
        await logger.log_trade(market="0x1", side="YES", price=0.5, size_usd=10.0)
        await logger.close()  # Should not raise

    @pytest.mark.asyncio
    async def test_ld17_file_write_error_raises(self, monkeypatch):
        """LD-17 file write failure raises OSError (no silent failure)."""
        from projects.polymarket.polyquantbot.monitoring.live_trade_logger import LiveTradeLogger, _write_line

        logger = LiveTradeLogger(log_file="/some/path/trades.jsonl")

        def _bad_write(path: str, line: str) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(
            "projects.polymarket.polyquantbot.monitoring.live_trade_logger._write_line",
            _bad_write,
        )

        with pytest.raises(OSError):
            await logger.log_trade(market="0x1", side="YES", price=0.5, size_usd=10.0)


# ─────────────────────────────────────────────────────────────────────────────
# LD-18–LD-22: Startup Live Checks
# ─────────────────────────────────────────────────────────────────────────────


class TestStartupLiveChecks:
    """run_prelive_validation startup gate."""

    @pytest.mark.asyncio
    async def test_ld18_paper_mode_skips_validation(self):
        """LD-18 PAPER mode returns immediately without running checks."""
        from projects.polymarket.polyquantbot.core.startup_live_checks import run_prelive_validation
        from projects.polymarket.polyquantbot.phase10.go_live_controller import TradingMode
        # No metrics_validator or infrastructure — should still pass in PAPER
        await run_prelive_validation(mode=TradingMode.PAPER)  # Must not raise

    @pytest.mark.asyncio
    async def test_ld19_live_mode_passes_with_all_checks_ok(self):
        """LD-19 LIVE mode passes when all PreLive checks pass."""
        from projects.polymarket.polyquantbot.core.startup_live_checks import run_prelive_validation
        from projects.polymarket.polyquantbot.phase10.go_live_controller import TradingMode

        metrics = _make_metrics_validator(ev_capture=0.80, fill_rate=0.70,
                                          p95_latency=300.0, drawdown=0.05)
        risk_guard = _make_risk_guard(disabled=False)
        redis = _make_redis()
        audit = _make_audit_logger(db_connected=True)

        await run_prelive_validation(
            mode=TradingMode.LIVE,
            metrics_validator=metrics,
            risk_guard=risk_guard,
            redis_client=redis,
            audit_logger=audit,
            telegram_configured=True,
        )  # Must not raise

    @pytest.mark.asyncio
    async def test_ld20_live_mode_raises_on_failing_check(self):
        """LD-20 LIVE mode raises StartupValidationError on any check failure."""
        from projects.polymarket.polyquantbot.core.startup_live_checks import (
            run_prelive_validation, StartupValidationError
        )
        from projects.polymarket.polyquantbot.phase10.go_live_controller import TradingMode

        metrics = _make_metrics_validator(ev_capture=0.50)  # too low
        risk_guard = _make_risk_guard(disabled=False)
        redis = _make_redis()
        audit = _make_audit_logger(db_connected=True)

        with pytest.raises(StartupValidationError):
            await run_prelive_validation(
                mode=TradingMode.LIVE,
                metrics_validator=metrics,
                risk_guard=risk_guard,
                redis_client=redis,
                audit_logger=audit,
                telegram_configured=True,
            )

    @pytest.mark.asyncio
    async def test_ld21_error_message_contains_reason(self):
        """LD-21 StartupValidationError message contains the failure reason."""
        from projects.polymarket.polyquantbot.core.startup_live_checks import (
            run_prelive_validation, StartupValidationError
        )
        from projects.polymarket.polyquantbot.phase10.go_live_controller import TradingMode

        # No redis → check failure
        metrics = _make_metrics_validator()
        risk_guard = _make_risk_guard(disabled=False)
        audit = _make_audit_logger(db_connected=True)

        with pytest.raises(StartupValidationError) as exc_info:
            await run_prelive_validation(
                mode=TradingMode.LIVE,
                metrics_validator=metrics,
                risk_guard=risk_guard,
                redis_client=None,  # missing → fail
                audit_logger=audit,
                telegram_configured=True,
            )

        assert "redis" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_ld22_telegram_alert_error_called_on_failure(self):
        """LD-22 Telegram alert_error called when validation fails."""
        from projects.polymarket.polyquantbot.core.startup_live_checks import (
            run_prelive_validation, StartupValidationError
        )
        from projects.polymarket.polyquantbot.phase10.go_live_controller import TradingMode

        metrics = _make_metrics_validator(ev_capture=0.10)  # will fail
        risk_guard = _make_risk_guard(disabled=False)
        redis = _make_redis()
        audit = _make_audit_logger(db_connected=True)

        tg = MagicMock()
        tg.alert_error = AsyncMock()

        with pytest.raises(StartupValidationError):
            await run_prelive_validation(
                mode=TradingMode.LIVE,
                metrics_validator=metrics,
                risk_guard=risk_guard,
                redis_client=redis,
                audit_logger=audit,
                telegram_configured=True,
                telegram=tg,
            )

        tg.alert_error.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# LD-23–LD-27: Message Formatter
# ─────────────────────────────────────────────────────────────────────────────


class TestMessageFormatter:
    """New Phase 11 message formatters."""

    def test_ld23_format_live_mode_activated_returns_string(self):
        """LD-23 format_live_mode_activated returns a non-empty string."""
        from projects.polymarket.polyquantbot.telegram.message_formatter import format_live_mode_activated
        msg = format_live_mode_activated()
        assert isinstance(msg, str)
        assert len(msg) > 0

    def test_ld24_format_live_mode_activated_includes_header(self):
        """LD-24 format_live_mode_activated includes 'LIVE MODE ACTIVATED'."""
        from projects.polymarket.polyquantbot.telegram.message_formatter import format_live_mode_activated
        msg = format_live_mode_activated(checks={"redis_connected": True, "db_connected": True})
        assert "LIVE MODE ACTIVATED" in msg

    def test_ld25_format_real_trade_executed_returns_string(self):
        """LD-25 format_real_trade_executed returns a non-empty string."""
        from projects.polymarket.polyquantbot.telegram.message_formatter import format_real_trade_executed
        msg = format_real_trade_executed(
            market="0xabc123",
            side="YES",
            price=0.62,
            size_usd=50.0,
            timestamp=int(time.time() * 1000),
        )
        assert isinstance(msg, str)
        assert len(msg) > 0

    def test_ld26_format_real_trade_executed_includes_header(self):
        """LD-26 format_real_trade_executed includes 'REAL TRADE EXECUTED'."""
        from projects.polymarket.polyquantbot.telegram.message_formatter import format_real_trade_executed
        msg = format_real_trade_executed(
            market="0xabc123",
            side="YES",
            price=0.62,
            size_usd=50.0,
            timestamp=int(time.time() * 1000),
        )
        assert "REAL TRADE EXECUTED" in msg

    def test_ld27_format_real_trade_executed_includes_trade_details(self):
        """LD-27 format_real_trade_executed shows market, side, price, size."""
        from projects.polymarket.polyquantbot.telegram.message_formatter import format_real_trade_executed
        msg = format_real_trade_executed(
            market="0xabc123def",
            side="NO",
            price=0.38,
            size_usd=75.0,
            timestamp=int(time.time() * 1000),
            correlation_id="cid-test",
        )
        assert "NO" in msg
        assert "0.3800" in msg or "0.38" in msg
        assert "75" in msg


# ─────────────────────────────────────────────────────────────────────────────
# LD-28–LD-32: LiveExecutor Phase 11 integration
# ─────────────────────────────────────────────────────────────────────────────


def _make_execution_request(
    market_id: str = "0xabc",
    side: str = "YES",
    price: float = 0.62,
    size: float = 50.0,
) -> object:
    """Build a minimal ExecutionRequest-like object for tests."""
    from projects.polymarket.polyquantbot.phase7.core.execution.live_executor import ExecutionRequest
    cid = str(uuid.uuid4())
    return ExecutionRequest(
        market_id=market_id,
        side=side,
        price=price,
        size=size,
        correlation_id=cid,
    )


def _make_execution_result(
    status: str = "filled",
    avg_price: float = 0.62,
    filled_size: float = 50.0,
    correlation_id: str = "cid-001",
) -> object:
    from projects.polymarket.polyquantbot.phase7.core.execution.live_executor import ExecutionResult
    return ExecutionResult(
        order_id=correlation_id,
        status=status,
        filled_size=filled_size,
        avg_price=avg_price,
        latency_ms=50.0,
        correlation_id=correlation_id,
        error=None,
        is_paper=False,
    )


def _make_live_mode_controller(is_live: bool = True) -> MagicMock:
    from projects.polymarket.polyquantbot.phase10.go_live_controller import TradingMode
    ctrl = MagicMock()
    ctrl.is_live_enabled.return_value = is_live
    ctrl.get_block_reason.return_value = "" if is_live else "paper_mode"
    ctrl.mode = TradingMode.LIVE if is_live else TradingMode.PAPER
    return ctrl


def _make_execution_guard(passed: bool = True) -> MagicMock:
    guard = MagicMock()
    result = MagicMock()
    result.passed = passed
    result.reason = "" if passed else "min_liquidity_not_met"
    guard.validate.return_value = result
    return guard


class TestLiveExecutorPhase11:
    """LiveExecutor Phase 11: live trade logger and Telegram integration."""

    @pytest.mark.asyncio
    async def test_ld28_live_trade_logger_called_on_filled_live_order(self):
        """LD-28 live_trade_logger.log_trade called on filled LIVE execution."""
        from projects.polymarket.polyquantbot.execution.live_executor import LiveExecutor

        inner_executor = MagicMock()
        inner_executor.execute = AsyncMock(
            return_value=_make_execution_result(status="filled")
        )
        live_trade_logger = MagicMock()
        live_trade_logger.log_trade = AsyncMock()

        redis = _make_redis()
        executor = LiveExecutor(
            live_mode_controller=_make_live_mode_controller(is_live=True),
            execution_guard=_make_execution_guard(passed=True),
            phase7_executor=inner_executor,
            redis_client=redis,
            live_trade_logger=live_trade_logger,
        )

        req = _make_execution_request()
        result = await executor.execute(req, market_ctx={"depth": 20000.0, "spread": 0.02})

        assert result.allowed is True
        live_trade_logger.log_trade.assert_called_once()
        call_kwargs = live_trade_logger.log_trade.call_args.kwargs
        assert call_kwargs["market"] == req.market_id
        assert call_kwargs["side"] == req.side

    @pytest.mark.asyncio
    async def test_ld29_live_trade_logger_not_called_in_paper_mode(self):
        """LD-29 live_trade_logger NOT called when mode is PAPER."""
        from projects.polymarket.polyquantbot.execution.live_executor import LiveExecutor

        inner_executor = MagicMock()
        inner_executor.execute = AsyncMock(
            return_value=_make_execution_result(status="filled")
        )
        live_trade_logger = MagicMock()
        live_trade_logger.log_trade = AsyncMock()

        # PAPER mode controller — no Redis needed
        executor = LiveExecutor(
            live_mode_controller=_make_live_mode_controller(is_live=False),
            execution_guard=_make_execution_guard(passed=True),
            phase7_executor=inner_executor,
            redis_client=None,  # allowed in PAPER mode
            live_trade_logger=live_trade_logger,
        )

        req = _make_execution_request()
        # PAPER mode → blocked by live_mode_controller gate
        result = await executor.execute(req)

        assert result.allowed is False
        live_trade_logger.log_trade.assert_not_called()

    @pytest.mark.asyncio
    async def test_ld30_live_trade_logger_not_called_on_rejected_order(self):
        """LD-30 live_trade_logger NOT called when order is rejected."""
        from projects.polymarket.polyquantbot.execution.live_executor import LiveExecutor

        inner_executor = MagicMock()
        inner_executor.execute = AsyncMock(
            return_value=_make_execution_result(status="rejected", filled_size=0.0, avg_price=0.0)
        )
        live_trade_logger = MagicMock()
        live_trade_logger.log_trade = AsyncMock()

        redis = _make_redis()
        executor = LiveExecutor(
            live_mode_controller=_make_live_mode_controller(is_live=True),
            execution_guard=_make_execution_guard(passed=True),
            phase7_executor=inner_executor,
            redis_client=redis,
            live_trade_logger=live_trade_logger,
        )

        req = _make_execution_request()
        result = await executor.execute(req, market_ctx={"depth": 20000.0, "spread": 0.02})

        assert result.allowed is True
        live_trade_logger.log_trade.assert_not_called()

    @pytest.mark.asyncio
    async def test_ld31_telegram_alert_called_on_filled_live_order(self):
        """LD-31 Telegram alert_open called after filled LIVE execution."""
        from projects.polymarket.polyquantbot.execution.live_executor import LiveExecutor

        inner_executor = MagicMock()
        inner_executor.execute = AsyncMock(
            return_value=_make_execution_result(status="filled")
        )
        telegram = MagicMock()
        telegram.alert_open = AsyncMock()

        redis = _make_redis()
        executor = LiveExecutor(
            live_mode_controller=_make_live_mode_controller(is_live=True),
            execution_guard=_make_execution_guard(passed=True),
            phase7_executor=inner_executor,
            redis_client=redis,
            telegram=telegram,
        )

        req = _make_execution_request()
        result = await executor.execute(req, market_ctx={"depth": 20000.0, "spread": 0.02})

        assert result.allowed is True
        telegram.alert_open.assert_called_once()

    @pytest.mark.asyncio
    async def test_ld32_live_trade_logger_error_does_not_block_result(self):
        """LD-32 live_trade_logger errors do not block execution result."""
        from projects.polymarket.polyquantbot.execution.live_executor import LiveExecutor

        inner_executor = MagicMock()
        inner_executor.execute = AsyncMock(
            return_value=_make_execution_result(status="filled")
        )
        live_trade_logger = MagicMock()
        # Simulate a logger error
        live_trade_logger.log_trade = AsyncMock(side_effect=RuntimeError("logger_down"))

        redis = _make_redis()
        executor = LiveExecutor(
            live_mode_controller=_make_live_mode_controller(is_live=True),
            execution_guard=_make_execution_guard(passed=True),
            phase7_executor=inner_executor,
            redis_client=redis,
            live_trade_logger=live_trade_logger,
        )

        req = _make_execution_request()
        result = await executor.execute(req, market_ctx={"depth": 20000.0, "spread": 0.02})

        # Execution must succeed despite logger failure
        assert result.allowed is True
        assert result.result is not None
        assert result.result.status == "filled"
