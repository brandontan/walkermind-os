"""SENTINEL — Phase 10.7 Pre-Live Gate Test Suite.

Validates:
  PG-01  MessageFormatter — format_status produces non-empty string
  PG-02  MessageFormatter — format_metrics produces non-empty string
  PG-03  MessageFormatter — format_prelive_check PASS format
  PG-04  MessageFormatter — format_prelive_check FAIL format includes reason
  PG-05  MessageFormatter — format_error includes context and error text
  PG-06  MessageFormatter — format_kill_alert includes reason
  PG-07  MessageFormatter — format_command_response success=True
  PG-08  MessageFormatter — format_command_response success=False
  PG-09  MessageFormatter — format_state_change includes both states
  PG-10  MessageFormatter — format_checkpoint includes elapsed_h
  PG-11  PreLiveValidator — all checks pass returns PASS
  PG-12  PreLiveValidator — ev_capture below threshold returns FAIL
  PG-13  PreLiveValidator — fill_rate below threshold returns FAIL
  PG-14  PreLiveValidator — latency exceeded returns FAIL
  PG-15  PreLiveValidator — drawdown exceeded returns FAIL
  PG-16  PreLiveValidator — kill switch active returns FAIL
  PG-17  PreLiveValidator — redis missing returns FAIL
  PG-18  PreLiveValidator — db not connected returns FAIL
  PG-19  PreLiveValidator — telegram not configured returns FAIL
  PG-20  PreLiveValidator — no risk_guard returns FAIL (fail closed)
  PG-21  PreLiveValidator — result.to_dict() is JSON-serialisable
  PG-22  StartupChecks — PAPER mode + no Redis → warning, no raise
  PG-23  StartupChecks — LIVE mode + no Redis → CriticalExecutionError
  PG-24  StartupChecks — PAPER mode + no DB → warning, no raise
  PG-25  StartupChecks — LIVE mode + no DB → CriticalAuditError
  PG-26  StartupChecks — LIVE mode + Redis + DB connected → no raise
  PG-27  Pipeline — SystemStateManager RUNNING → execution proceeds
  PG-28  Pipeline — SystemStateManager PAUSED → execution blocked
  PG-29  Pipeline — SystemStateManager HALTED → execution blocked
  PG-30  CommandHandler — /prelive_check with no validator → error response
  PG-31  CommandHandler — /prelive_check with PASS validator → success response
  PG-32  CommandHandler — /prelive_check with FAIL validator → fail response
  PG-33  TelegramWebhookServer — invalid JSON returns 400
  PG-34  TelegramWebhookServer — valid update routed to CommandRouter
  PG-35  TelegramWebhookServer — secret token mismatch returns 403
  PG-36  TelegramWebhookServer — rate limiting blocks excess requests
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from projects.polymarket.polyquantbot.telegram.message_formatter import (
    format_checkpoint,
    format_command_response,
    format_error,
    format_kill_alert,
    format_metrics,
    format_prelive_check,
    format_state_change,
    format_status,
)
from projects.polymarket.polyquantbot.core.prelive_validator import (
    PreLiveResult,
    PreLiveValidator,
)
from projects.polymarket.polyquantbot.monitoring.startup_checks import (
    enforce_db_for_live,
    enforce_redis_for_live,
    run_startup_checks,
)
from projects.polymarket.polyquantbot.core.exceptions import (
    CriticalAuditError,
    CriticalExecutionError,
)
from projects.polymarket.polyquantbot.core.system_state import (
    SystemState,
    SystemStateManager,
)


# ── Stubs ─────────────────────────────────────────────────────────────────────


class _StubMetrics:
    """Stub metrics validator with configurable values."""

    def __init__(
        self,
        ev_capture_ratio: float = 0.80,
        fill_rate: float = 0.70,
        p95_latency: float = 300.0,
        drawdown: float = 0.04,
    ) -> None:
        self.ev_capture_ratio = ev_capture_ratio
        self.fill_rate = fill_rate
        self.p95_latency = p95_latency
        self.drawdown = drawdown


class _StubRiskGuard:
    """Stub RiskGuard with configurable kill-switch state."""

    def __init__(self, disabled: bool = False) -> None:
        self.disabled = disabled


class _StubAuditLogger:
    """Stub audit logger with configurable DB connection state."""

    def __init__(self, connected: bool = True) -> None:
        self._connected = connected

    def is_db_connected(self) -> bool:
        return self._connected


class _StubRedis:
    """Stub Redis client (presence indicates connection)."""
    pass


# ── PG-01 – PG-10: MessageFormatter ──────────────────────────────────────────


class TestPG01FormatStatus:
    """format_status() returns non-empty, Markdown-compatible string."""

    def test_running_state(self) -> None:
        msg = format_status("RUNNING", "initialized", 1.0, 0.05)
        assert "RUNNING" in msg
        assert "Risk multiplier" in msg
        assert len(msg) > 10

    def test_halted_state_includes_emoji(self) -> None:
        msg = format_status("HALTED", "kill_command", 0.5, 0.03)
        assert "HALTED" in msg
        assert "🛑" in msg

    def test_with_mode(self) -> None:
        msg = format_status("PAUSED", "operator", 0.8, 0.02, mode="LIVE")
        assert "LIVE" in msg


class TestPG02FormatMetrics:
    """format_metrics() returns non-empty string from dict."""

    def test_empty_dict(self) -> None:
        msg = format_metrics({})
        assert "No metrics" in msg

    def test_with_data(self) -> None:
        msg = format_metrics({"fill_rate": 0.72, "latency": 220.5})
        assert "fill_rate" in msg
        assert "0.7200" in msg

    def test_custom_title(self) -> None:
        msg = format_metrics({"x": 1}, title="CUSTOM")
        assert "CUSTOM" in msg


class TestPG03FormatPreliveCheckPass:
    """format_prelive_check() PASS format shows checkmarks."""

    def test_pass_status(self) -> None:
        result = {
            "status": "PASS",
            "checks": {"ev_capture": True, "fill_rate": True},
            "reason": "",
        }
        msg = format_prelive_check(result)
        assert "PASS" in msg
        assert "✅" in msg

    def test_no_reason_on_pass(self) -> None:
        result = {"status": "PASS", "checks": {}, "reason": ""}
        msg = format_prelive_check(result)
        assert "Reason" not in msg


class TestPG04FormatPreliveCheckFail:
    """format_prelive_check() FAIL format includes reason and failure marker."""

    def test_fail_status(self) -> None:
        result = {
            "status": "FAIL",
            "checks": {"ev_capture": False, "fill_rate": True},
            "reason": "ev_capture below threshold",
        }
        msg = format_prelive_check(result)
        assert "FAIL" in msg
        assert "❌" in msg

    def test_reason_included(self) -> None:
        result = {
            "status": "FAIL",
            "checks": {},
            "reason": "redis not connected",
        }
        msg = format_prelive_check(result)
        assert "redis not connected" in msg


class TestPG05FormatError:
    """format_error() includes context, error text, and severity."""

    def test_critical_severity(self) -> None:
        msg = format_error("pipeline", "timeout occurred", "CRITICAL")
        assert "CRITICAL" in msg
        assert "pipeline" in msg
        assert "timeout occurred" in msg
        assert "🚨" in msg

    def test_warning_severity(self) -> None:
        msg = format_error("metrics", "bad data", "WARNING")
        assert "WARNING" in msg
        assert "⚠️" in msg

    def test_with_correlation_id(self) -> None:
        msg = format_error("test", "err", correlation_id="abc-123")
        assert "abc-123" in msg


class TestPG06FormatKillAlert:
    """format_kill_alert() includes reason."""

    def test_reason_in_message(self) -> None:
        msg = format_kill_alert("daily_loss_limit_breached")
        assert "daily_loss_limit_breached" in msg
        assert "🚨" in msg
        assert "KILL" in msg

    def test_with_correlation_id(self) -> None:
        msg = format_kill_alert("test_reason", correlation_id="cid-xyz")
        assert "cid-xyz" in msg


class TestPG07FormatCommandResponseSuccess:
    """format_command_response() success=True produces positive message."""

    def test_success_flag(self) -> None:
        msg = format_command_response("status", True, "All good")
        assert "✅" in msg
        assert "status" in msg
        assert "All good" in msg


class TestPG08FormatCommandResponseFailure:
    """format_command_response() success=False produces negative message."""

    def test_failure_flag(self) -> None:
        msg = format_command_response("pause", False, "Already halted")
        assert "❌" in msg
        assert "pause" in msg
        assert "Already halted" in msg


class TestPG09FormatStateChange:
    """format_state_change() includes both states and reason."""

    def test_includes_both_states(self) -> None:
        msg = format_state_change("RUNNING", "PAUSED", "operator_command")
        assert "RUNNING" in msg
        assert "PAUSED" in msg
        assert "operator_command" in msg
        assert "⏸️" in msg


class TestPG10FormatCheckpoint:
    """format_checkpoint() includes elapsed_h and metrics."""

    def test_elapsed_hours(self) -> None:
        msg = format_checkpoint(6.0, {}, label="6h")
        assert "6.0h" in msg
        assert "6h" in msg

    def test_with_metrics(self) -> None:
        msg = format_checkpoint(12.0, {"fill_rate": 0.72}, label="12h")
        assert "fill_rate" in msg
        assert "0.7200" in msg


# ── PG-11 – PG-21: PreLiveValidator ──────────────────────────────────────────


def _make_validator(**kwargs: Any) -> PreLiveValidator:
    """Build a PreLiveValidator with all required stubs passing by default."""
    defaults = {
        "metrics_validator": _StubMetrics(),
        "risk_guard": _StubRiskGuard(disabled=False),
        "redis_client": _StubRedis(),
        "audit_logger": _StubAuditLogger(connected=True),
        "telegram_configured": True,
    }
    defaults.update(kwargs)
    return PreLiveValidator(**defaults)


class TestPG11AllChecksPass:
    """All conditions met → status PASS."""

    def test_pass_result(self) -> None:
        v = _make_validator()
        result = v.run()
        assert result.status == "PASS"
        assert result.reason == ""
        assert all(result.checks.values())


class TestPG12EVCaptureFail:
    """EV capture below threshold → FAIL."""

    def test_ev_fail(self) -> None:
        v = _make_validator(metrics_validator=_StubMetrics(ev_capture_ratio=0.50))
        result = v.run()
        assert result.status == "FAIL"
        assert "ev_capture" in result.reason
        assert result.checks.get("ev_capture") is False


class TestPG13FillRateFail:
    """Fill rate below threshold → FAIL."""

    def test_fill_fail(self) -> None:
        v = _make_validator(metrics_validator=_StubMetrics(fill_rate=0.40))
        result = v.run()
        assert result.status == "FAIL"
        assert "fill_rate" in result.reason


class TestPG14LatencyFail:
    """Latency exceeds threshold → FAIL."""

    def test_latency_fail(self) -> None:
        v = _make_validator(metrics_validator=_StubMetrics(p95_latency=600.0))
        result = v.run()
        assert result.status == "FAIL"
        assert "latency" in result.reason.lower()


class TestPG15DrawdownFail:
    """Drawdown exceeds threshold → FAIL."""

    def test_drawdown_fail(self) -> None:
        v = _make_validator(metrics_validator=_StubMetrics(drawdown=0.10))
        result = v.run()
        assert result.status == "FAIL"
        assert "drawdown" in result.reason


class TestPG16KillSwitchFail:
    """Kill switch active → FAIL."""

    def test_kill_switch_fail(self) -> None:
        v = _make_validator(risk_guard=_StubRiskGuard(disabled=True))
        result = v.run()
        assert result.status == "FAIL"
        assert "kill_switch" in result.reason


class TestPG17RedisFail:
    """Redis not connected → FAIL."""

    def test_redis_fail(self) -> None:
        v = _make_validator(redis_client=None)
        result = v.run()
        assert result.status == "FAIL"
        assert "redis" in result.reason
        assert result.checks.get("redis_connected") is False


class TestPG18DBFail:
    """DB not connected → FAIL."""

    def test_db_fail(self) -> None:
        v = _make_validator(audit_logger=_StubAuditLogger(connected=False))
        result = v.run()
        assert result.status == "FAIL"
        assert "postgresql" in result.reason.lower() or "db" in result.reason.lower()


class TestPG19TelegramFail:
    """Telegram not configured → FAIL."""

    def test_telegram_fail(self) -> None:
        v = _make_validator(telegram_configured=False)
        result = v.run()
        assert result.status == "FAIL"
        assert "telegram" in result.reason


class TestPG20NoRiskGuardFailClosed:
    """No risk guard → FAIL (fail closed)."""

    def test_no_risk_guard(self) -> None:
        v = _make_validator(risk_guard=None)
        result = v.run()
        assert result.status == "FAIL"


class TestPG21ResultToDict:
    """PreLiveResult.to_dict() returns JSON-serialisable dict."""

    def test_to_dict_structure(self) -> None:
        import json

        v = _make_validator()
        result = v.run()
        d = result.to_dict()
        assert isinstance(d, dict)
        assert "status" in d
        assert "checks" in d
        assert "reason" in d
        assert "timestamp" in d
        # Must be JSON-serialisable
        json.dumps(d)


# ── PG-22 – PG-26: StartupChecks ─────────────────────────────────────────────


class TestPG22RedisPaperNoRaise:
    """PAPER mode + no Redis → warning, no raise."""

    def test_paper_no_redis(self) -> None:
        # Should not raise
        enforce_redis_for_live(mode="PAPER", redis_client=None)


class TestPG23RedisLiveRaises:
    """LIVE mode + no Redis → CriticalExecutionError."""

    def test_live_no_redis(self) -> None:
        with pytest.raises(CriticalExecutionError):
            enforce_redis_for_live(mode="LIVE", redis_client=None)


class TestPG24DBPaperNoRaise:
    """PAPER mode + no DB → warning, no raise."""

    def test_paper_no_db(self) -> None:
        enforce_db_for_live(mode="PAPER", audit_logger=None)


class TestPG25DBLiveRaises:
    """LIVE mode + DB not connected → CriticalAuditError."""

    def test_live_no_db(self) -> None:
        with pytest.raises(CriticalAuditError):
            enforce_db_for_live(
                mode="LIVE",
                audit_logger=_StubAuditLogger(connected=False),
            )

    def test_live_no_audit_logger(self) -> None:
        with pytest.raises(CriticalAuditError):
            enforce_db_for_live(mode="LIVE", audit_logger=None)


class TestPG26LiveBothConnectedNoRaise:
    """LIVE mode + Redis + DB → no exception."""

    def test_live_all_connected(self) -> None:
        run_startup_checks(
            mode="LIVE",
            redis_client=_StubRedis(),
            audit_logger=_StubAuditLogger(connected=True),
        )


# ── PG-27 – PG-29: Pipeline SystemStateManager gate ──────────────────────────


class TestPG27SystemStateRunning:
    """SystemStateManager RUNNING → execution proceeds (not None)."""

    async def test_running_allows_execution(self) -> None:
        manager = SystemStateManager(initial_state=SystemState.RUNNING)
        assert manager.is_execution_allowed() is True


class TestPG28SystemStatePaused:
    """SystemStateManager PAUSED → execution blocked."""

    async def test_paused_blocks_execution(self) -> None:
        manager = SystemStateManager(initial_state=SystemState.RUNNING)
        await manager.pause("test")
        assert manager.is_execution_allowed() is False


class TestPG29SystemStateHalted:
    """SystemStateManager HALTED → execution blocked."""

    async def test_halted_blocks_execution(self) -> None:
        manager = SystemStateManager(initial_state=SystemState.RUNNING)
        await manager.halt("test")
        assert manager.is_execution_allowed() is False


# ── PG-30 – PG-32: CommandHandler /prelive_check ─────────────────────────────


class _StubPreLiveValidator:
    """Stub PreLiveValidator with configurable result."""

    def __init__(self, status: str = "PASS", reason: str = "") -> None:
        self._status = status
        self._reason = reason

    def run(self) -> Any:
        return PreLiveResult(
            status=self._status,
            checks={"ev_capture": self._status == "PASS"},
            reason=self._reason,
        )


class TestPG30PreliveCheckNoValidator:
    """/prelive_check with no validator → error response."""

    async def test_no_validator(self) -> None:
        from projects.polymarket.polyquantbot.telegram.command_handler import CommandHandler
        from projects.polymarket.polyquantbot.core.system_state import SystemStateManager
        from projects.polymarket.polyquantbot.config.runtime_config import ConfigManager

        state = SystemStateManager()
        config = ConfigManager()
        handler = CommandHandler(state_manager=state, config_manager=config)
        result = await handler.handle("prelive_check")
        assert result.success is False
        assert "PreLiveValidator" in result.message or "not configured" in result.message


class TestPG31PreliveCheckPass:
    """/prelive_check with PASS validator → success response."""

    async def test_pass_result(self) -> None:
        from projects.polymarket.polyquantbot.telegram.command_handler import CommandHandler
        from projects.polymarket.polyquantbot.core.system_state import SystemStateManager
        from projects.polymarket.polyquantbot.config.runtime_config import ConfigManager

        state = SystemStateManager()
        config = ConfigManager()
        handler = CommandHandler(
            state_manager=state,
            config_manager=config,
            prelive_validator=_StubPreLiveValidator(status="PASS"),
        )
        result = await handler.handle("prelive_check")
        assert result.success is True
        assert "PASS" in result.message


class TestPG32PreliveCheckFail:
    """/prelive_check with FAIL validator → fail response."""

    async def test_fail_result(self) -> None:
        from projects.polymarket.polyquantbot.telegram.command_handler import CommandHandler
        from projects.polymarket.polyquantbot.core.system_state import SystemStateManager
        from projects.polymarket.polyquantbot.config.runtime_config import ConfigManager

        state = SystemStateManager()
        config = ConfigManager()
        handler = CommandHandler(
            state_manager=state,
            config_manager=config,
            prelive_validator=_StubPreLiveValidator(status="FAIL", reason="redis missing"),
        )
        result = await handler.handle("prelive_check")
        assert result.success is False
        assert "FAIL" in result.message


# ── PG-33 – PG-36: TelegramWebhookServer ─────────────────────────────────────


class _StubCommandRouter:
    """Stub CommandRouter that records route_update calls."""

    def __init__(self, result_success: bool = True) -> None:
        self.calls: list[dict] = []
        self._result_success = result_success

    async def route_update(self, update: dict) -> Any:
        self.calls.append(update)

        class _Result:
            success = True

        r = _Result()
        r.success = self._result_success
        return r


class TestPG33WebhookInvalidJSON:
    """POST /telegram/webhook with invalid JSON returns 400."""

    async def test_invalid_json(self) -> None:
        from projects.polymarket.polyquantbot.api.telegram_webhook import TelegramWebhookServer

        router = _StubCommandRouter()
        server = TelegramWebhookServer(router=router)
        await server.start()

        try:
            import aiohttp

            async with aiohttp.ClientSession() as session:
                resp = await session.post(
                    f"http://127.0.0.1:{server._port}/telegram/webhook",
                    data=b"not json",
                    headers={"Content-Type": "application/json"},
                )
                assert resp.status == 400
        finally:
            await server.stop()


class TestPG34WebhookValidUpdateRouted:
    """POST /telegram/webhook with valid update routes to CommandRouter."""

    async def test_valid_update(self) -> None:
        import json
        import aiohttp
        from projects.polymarket.polyquantbot.api.telegram_webhook import TelegramWebhookServer

        router = _StubCommandRouter()
        server = TelegramWebhookServer(router=router, port=18081)
        await server.start()

        try:
            update = {
                "update_id": 123,
                "message": {
                    "from": {"id": 456},
                    "text": "/status",
                },
            }
            async with aiohttp.ClientSession() as session:
                resp = await session.post(
                    f"http://127.0.0.1:{server._port}/telegram/webhook",
                    json=update,
                )
                assert resp.status == 200
                assert len(router.calls) == 1
        finally:
            await server.stop()


class TestPG35WebhookSecretMismatch:
    """POST /telegram/webhook with wrong secret returns 403."""

    async def test_secret_mismatch(self) -> None:
        import aiohttp
        from projects.polymarket.polyquantbot.api.telegram_webhook import TelegramWebhookServer

        router = _StubCommandRouter()
        server = TelegramWebhookServer(router=router, port=18082, secret_token="correct-secret")
        await server.start()

        try:
            async with aiohttp.ClientSession() as session:
                resp = await session.post(
                    f"http://127.0.0.1:{server._port}/telegram/webhook",
                    json={"update_id": 1, "message": {}},
                    headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-secret"},
                )
                assert resp.status == 403
        finally:
            await server.stop()


class TestPG36WebhookRateLimiting:
    """Rate limiting blocks IPs sending more than 20 req/s."""

    async def test_rate_limit_blocks(self) -> None:
        import time
        from projects.polymarket.polyquantbot.api.telegram_webhook import (
            TelegramWebhookServer,
            _RATE_LIMIT_RPS,
        )
        import aiohttp

        router = _StubCommandRouter()
        server = TelegramWebhookServer(router=router, port=18083)
        await server.start()

        try:
            statuses = []
            async with aiohttp.ClientSession() as session:
                for i in range(_RATE_LIMIT_RPS + 5):
                    resp = await session.post(
                        f"http://127.0.0.1:{server._port}/telegram/webhook",
                        json={"update_id": i, "message": {"from": {"id": 1}, "text": f"/status{i}"}},
                    )
                    statuses.append(resp.status)
            # At least one request should be rate-limited (429)
            assert 429 in statuses
        finally:
            await server.stop()
