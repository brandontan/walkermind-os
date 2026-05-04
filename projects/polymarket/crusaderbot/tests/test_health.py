"""Smoke tests for the /health endpoint and the monitoring layer.

Mocks every external dependency (DB, Telegram, HTTP RPC, TCP socket) so
the test suite stays hermetic and fast. Exercises the four documented
verdict branches: ok / degraded / down / mixed-failure.
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from projects.polymarket.crusaderbot.monitoring import alerts as monitoring_alerts
from projects.polymarket.crusaderbot.monitoring import health as monitoring_health


def _patch_check(name: str, *, ok: bool, exc: Exception | None = None):
    """Return a context manager that replaces a single check coroutine."""
    target = f"projects.polymarket.crusaderbot.monitoring.health.{name}"

    async def _fake() -> bool:
        if exc is not None:
            raise exc
        return ok

    return patch(target, new=_fake)


def _all_checks_ok():
    return [
        _patch_check("check_database", ok=True),
        _patch_check("check_telegram", ok=True),
        _patch_check("check_alchemy_rpc", ok=True),
        _patch_check("check_alchemy_ws", ok=True),
    ]


@pytest.fixture(autouse=True)
def _reset_alert_state():
    monitoring_alerts.reset_state()
    yield
    monitoring_alerts.reset_state()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


def test_run_health_checks_all_ok_status_ok():
    patches = _all_checks_ok()
    for p in patches:
        p.start()
    try:
        result = _run(monitoring_health.run_health_checks())
    finally:
        for p in patches:
            p.stop()
    assert result["status"] == "ok"
    assert result["ready"] is True
    assert result["service"] == "CrusaderBot"
    assert set(result["checks"].keys()) == {
        "database", "telegram", "alchemy_rpc", "alchemy_ws",
    }
    assert all(v == "ok" for v in result["checks"].values())


def test_run_health_checks_db_down_returns_status_down_and_not_ready():
    patches = [
        _patch_check("check_database", ok=False, exc=RuntimeError("pg refused")),
        _patch_check("check_telegram", ok=True),
        _patch_check("check_alchemy_rpc", ok=True),
        _patch_check("check_alchemy_ws", ok=True),
    ]
    for p in patches:
        p.start()
    try:
        result = _run(monitoring_health.run_health_checks())
    finally:
        for p in patches:
            p.stop()
    assert result["status"] == "down"
    assert result["ready"] is False
    assert result["checks"]["database"].startswith("error:")
    assert result["checks"]["telegram"] == "ok"


def test_run_health_checks_non_db_failure_is_degraded_but_ready():
    patches = [
        _patch_check("check_database", ok=True),
        _patch_check("check_telegram", ok=True),
        _patch_check("check_alchemy_rpc", ok=False, exc=RuntimeError("alchemy 503")),
        _patch_check("check_alchemy_ws", ok=True),
    ]
    for p in patches:
        p.start()
    try:
        result = _run(monitoring_health.run_health_checks())
    finally:
        for p in patches:
            p.stop()
    assert result["status"] == "degraded"
    assert result["ready"] is True
    assert result["checks"]["database"] == "ok"
    assert result["checks"]["alchemy_rpc"].startswith("error:")


def test_check_does_not_hang_past_timeout():
    """A check that sleeps forever must be aborted at CHECK_TIMEOUT_SECONDS."""

    async def _hangs() -> bool:
        await asyncio.sleep(60)
        return True  # unreachable

    with patch.object(
        monitoring_health, "check_alchemy_ws", new=_hangs,
    ), patch.object(monitoring_health, "CHECK_TIMEOUT_SECONDS", 0.1):
        # Re-patch the helpers that capture CHECK_TIMEOUT_SECONDS at runtime.
        result = _run(monitoring_health.run_health_checks())
    assert result["checks"]["alchemy_ws"].startswith("error:")
    # Must still return a verdict — endpoint never hangs.
    assert result["status"] in {"degraded", "down"}


def test_health_response_shape_keys_are_stable():
    patches = _all_checks_ok()
    for p in patches:
        p.start()
    try:
        result = _run(monitoring_health.run_health_checks())
    finally:
        for p in patches:
            p.stop()
    assert set(result.keys()) == {"status", "service", "checks", "ready"}


def test_record_health_result_no_alert_below_threshold():
    """First failure must NOT page — threshold is 2 consecutive failures."""

    sent: list[Any] = []

    async def _fake_send(chat_id, text, parse_mode=None):
        sent.append((chat_id, text))

    fake_settings = MagicMock(OPERATOR_CHAT_ID=12345)
    with patch(
        "projects.polymarket.crusaderbot.monitoring.alerts.notifications.send",
        new=_fake_send,
    ), patch(
        "projects.polymarket.crusaderbot.monitoring.alerts.get_settings",
        return_value=fake_settings,
    ):
        _run(monitoring_alerts.record_health_result({
            "status": "down",
            "checks": {"database": "error: down", "telegram": "ok"},
        }))
    assert sent == []


def test_record_health_result_alerts_after_threshold_then_cools_down():
    sent: list[Any] = []

    async def _fake_send(chat_id, text, parse_mode=None):
        sent.append((chat_id, text))

    fake_settings = MagicMock(OPERATOR_CHAT_ID=12345)
    bad = {
        "status": "down",
        "checks": {"database": "error: down", "telegram": "ok"},
    }
    with patch(
        "projects.polymarket.crusaderbot.monitoring.alerts.notifications.send",
        new=_fake_send,
    ), patch(
        "projects.polymarket.crusaderbot.monitoring.alerts.get_settings",
        return_value=fake_settings,
    ):
        # First failure: counter -> 1, no alert yet.
        _run(monitoring_alerts.record_health_result(bad))
        assert len(sent) == 0
        # Second consecutive failure: counter -> 2, alert dispatched.
        _run(monitoring_alerts.record_health_result(bad))
        assert len(sent) == 1
        # Third failure inside the cooldown window: suppressed.
        _run(monitoring_alerts.record_health_result(bad))
        assert len(sent) == 1


def test_record_health_result_per_check_reset_while_degraded():
    """A check that recovers must NOT page on its next isolated failure even
    if the overall verdict stayed ``degraded`` the whole time because some
    OTHER dependency is still down.

    Sequence (simulates Codex's reported false-page scenario):
      1. tg down, rpc ok        -> tg counter=1
      2. tg down, rpc down      -> tg=2 (alerts), rpc=1 -- cooldown engaged
      3. tg down, rpc ok        -> tg=3, rpc must reset to 0
      4. tg down, rpc down      -> tg=4 (cooldown), rpc=1 -- must NOT page
    """
    sent: list[Any] = []

    async def _fake_send(chat_id, text, parse_mode=None):
        sent.append((chat_id, text))

    fake_settings = MagicMock(OPERATOR_CHAT_ID=12345)
    tg_only = {
        "status": "degraded",
        "checks": {"telegram": "error: down", "alchemy_rpc": "ok"},
    }
    both = {
        "status": "degraded",
        "checks": {"telegram": "error: down", "alchemy_rpc": "error: down"},
    }
    with patch(
        "projects.polymarket.crusaderbot.monitoring.alerts.notifications.send",
        new=_fake_send,
    ), patch(
        "projects.polymarket.crusaderbot.monitoring.alerts.get_settings",
        return_value=fake_settings,
    ):
        _run(monitoring_alerts.record_health_result(tg_only))   # tg=1
        _run(monitoring_alerts.record_health_result(both))      # tg=2 (paged), rpc=1
        first_alerts = len(sent)
        assert first_alerts >= 1  # tg breach paged
        _run(monitoring_alerts.record_health_result(tg_only))   # rpc resets to 0
        _run(monitoring_alerts.record_health_result(both))      # rpc=1, NOT 2
    # No NEW alert triggered solely by rpc — only the original tg breach.
    rpc_alerts = [a for _, a in sent if "alchemy_rpc" in a]
    assert rpc_alerts == [], f"unexpected rpc alert: {rpc_alerts!r}"


def test_record_health_result_resets_on_recovery():
    sent: list[Any] = []

    async def _fake_send(chat_id, text, parse_mode=None):
        sent.append((chat_id, text))

    fake_settings = MagicMock(OPERATOR_CHAT_ID=12345)
    bad = {
        "status": "down",
        "checks": {"database": "error: down", "telegram": "ok"},
    }
    good = {"status": "ok", "checks": {"database": "ok", "telegram": "ok"}}

    with patch(
        "projects.polymarket.crusaderbot.monitoring.alerts.notifications.send",
        new=_fake_send,
    ), patch(
        "projects.polymarket.crusaderbot.monitoring.alerts.get_settings",
        return_value=fake_settings,
    ):
        _run(monitoring_alerts.record_health_result(bad))
        _run(monitoring_alerts.record_health_result(good))
        # After recovery the next single failure should NOT alert again.
        _run(monitoring_alerts.record_health_result(bad))
    assert sent == []
