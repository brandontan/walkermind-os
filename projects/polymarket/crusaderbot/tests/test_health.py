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

from projects.polymarket.crusaderbot import config as crusaderbot_config
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
    # ``run_health_checks`` returns the dependency-layer payload; the demo
    # readiness fields (``uptime_seconds``, ``version``, ``mode``,
    # ``timestamp``) are layered on at the route level — see
    # ``test_health_route_demo_readiness_fields`` for that contract.
    assert set(result.keys()) == {"status", "service", "checks", "ready"}


def test_record_health_result_no_alert_below_threshold():
    """First failure must NOT page — threshold is 2 consecutive failures."""

    sent: list[Any] = []

    async def _fake_send(chat_id, text, parse_mode=None):
        sent.append((chat_id, text))
        return True

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
        return True

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


def test_health_log_does_not_leak_exception_url(caplog):
    """The ERROR log emitted by ``_with_timeout`` must NOT contain the
    raw exception URL: httpx errors include the full request URL and
    Alchemy embeds the API key in the URL path. The endpoint payload is
    sanitised already; the application log stream must be too.
    """
    SECRET_PATH = "v2/ALCHEMY_KEY_DO_NOT_LEAK"
    SECRET_URL = f"https://polygon-mainnet.g.alchemy.com/{SECRET_PATH}"

    async def _leaks() -> bool:
        raise RuntimeError(
            f"Client error '401 Unauthorized' for url '{SECRET_URL}'"
        )

    with caplog.at_level("ERROR", logger="projects.polymarket.crusaderbot.monitoring.health"):
        with patch.object(monitoring_health, "check_alchemy_rpc", new=_leaks):
            _run(monitoring_health.run_health_checks())
    log_text = "\n".join(rec.getMessage() for rec in caplog.records)
    assert SECRET_URL not in log_text, f"raw URL leaked into logs: {log_text!r}"
    assert SECRET_PATH not in log_text, f"URL path leaked into logs: {log_text!r}"
    assert "ALCHEMY_KEY_DO_NOT_LEAK" not in log_text
    # The scrubbed substitution must still surface enough detail to diagnose:
    # exception class name + a redacted URL marker.
    assert "RuntimeError" in log_text
    assert "<redacted>" in log_text


def test_settings_accepts_alias_only_polygon_rpc_url(monkeypatch):
    """Alias-only deployments (only ALCHEMY_POLYGON_RPC_URL set, no legacy
    POLYGON_RPC_URL) must construct ``Settings`` without raising. The
    legacy field is auto-populated from the alias by a model-validator,
    keeping the contract used by other modules (``settings.POLYGON_RPC_URL``)
    consistent with ``validate_required_env``'s either-or group.
    """
    # Bust the lru_cache so this test sees the new env.
    crusaderbot_config.get_settings.cache_clear()

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("OPERATOR_CHAT_ID", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("WALLET_HD_SEED", "seed")
    monkeypatch.setenv("WALLET_ENCRYPTION_KEY", "k")
    monkeypatch.delenv("POLYGON_RPC_URL", raising=False)
    monkeypatch.setenv("ALCHEMY_POLYGON_RPC_URL", "https://alchemy.example/v2/key")
    monkeypatch.setenv("ALCHEMY_POLYGON_WS_URL", "wss://alchemy.example/v2/key")

    settings = crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert settings.POLYGON_RPC_URL == "https://alchemy.example/v2/key"
    assert settings.ALCHEMY_POLYGON_RPC_URL == "https://alchemy.example/v2/key"

    crusaderbot_config.get_settings.cache_clear()


def test_health_payload_does_not_leak_exception_message():
    """Public /health payload must NOT include raw exception text.

    httpx errors include the full request URL, and Alchemy embeds the API
    key in the URL path — so leaking ``str(exc)`` would dump credentials
    to anyone hitting the unauthenticated endpoint. The payload should
    surface only the exception class name.
    """
    SECRET_URL = "https://polygon.alchemy.com/v2/SUPER_SECRET_API_KEY_42"

    async def _leaks() -> bool:
        # Mimic httpx.HTTPStatusError whose __str__ embeds the full URL.
        raise RuntimeError(
            f"Client error '401 Unauthorized' for url '{SECRET_URL}'"
        )

    with patch.object(monitoring_health, "check_alchemy_rpc", new=_leaks):
        result = _run(monitoring_health.run_health_checks())
    rpc_reason = result["checks"]["alchemy_rpc"]
    assert rpc_reason == "error: RuntimeError"
    # Defence-in-depth: scan the entire payload for any leak surface.
    payload_str = repr(result)
    assert SECRET_URL not in payload_str
    assert "SUPER_SECRET_API_KEY_42" not in payload_str
    assert "401 Unauthorized" not in payload_str


def test_schedule_alert_does_not_block_on_slow_send():
    """Lifespan boot path uses schedule_alert for startup pages so a slow
    Telegram cannot stall app.startup past Fly's 10s grace_period.
    """

    async def _slow_send(chat_id, text, parse_mode=None):
        await asyncio.sleep(2.0)  # would stall boot if awaited
        return True

    fake_settings = MagicMock(OPERATOR_CHAT_ID=12345)

    async def _scenario():
        with patch(
            "projects.polymarket.crusaderbot.monitoring.alerts.notifications.send",
            new=_slow_send,
        ), patch(
            "projects.polymarket.crusaderbot.monitoring.alerts.get_settings",
            return_value=fake_settings,
        ):
            t0 = asyncio.get_event_loop().time()
            task = monitoring_alerts.schedule_alert(
                monitoring_alerts.alert_startup(restart_detected=True),
            )
            elapsed = asyncio.get_event_loop().time() - t0
            assert task is not None
            assert elapsed < 0.05, f"schedule_alert blocked for {elapsed:.3f}s"
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    _run(_scenario())


def test_schedule_alert_returns_none_without_running_loop():
    """Outside an event loop the helper must no-op and not raise the
    ``coroutine was never awaited`` warning.
    """

    async def _never_awaited(chat_id, text, parse_mode=None):
        return True

    # Build a coro on a settings stub that has OPERATOR_CHAT_ID; the helper
    # should close it without scheduling because there's no running loop.
    fake_settings = MagicMock(OPERATOR_CHAT_ID=12345)
    with patch(
        "projects.polymarket.crusaderbot.monitoring.alerts.notifications.send",
        new=_never_awaited,
    ), patch(
        "projects.polymarket.crusaderbot.monitoring.alerts.get_settings",
        return_value=fake_settings,
    ):
        task = monitoring_alerts.schedule_alert(
            monitoring_alerts.alert_startup(restart_detected=True),
        )
    assert task is None


def test_schedule_health_record_returns_none_without_running_loop():
    """Outside an async context the helper must no-op without raising."""
    task = monitoring_alerts.schedule_health_record(
        {"status": "ok", "checks": {"database": "ok"}}
    )
    assert task is None


def test_schedule_health_record_does_not_block_on_alert_delivery():
    """The route helper must return immediately even when the alert path
    sleeps — proving /health latency is decoupled from Telegram I/O.
    """

    async def _slow_send(chat_id, text, parse_mode=None):
        await asyncio.sleep(2.0)  # would blow Fly's 5s budget if awaited

    fake_settings = MagicMock(OPERATOR_CHAT_ID=12345)
    bad = {
        "status": "down",
        "checks": {"database": "error: down", "telegram": "ok"},
    }

    async def _scenario():
        with patch(
            "projects.polymarket.crusaderbot.monitoring.alerts.notifications.send",
            new=_slow_send,
        ), patch(
            "projects.polymarket.crusaderbot.monitoring.alerts.get_settings",
            return_value=fake_settings,
        ):
            # First failure -> threshold not yet hit, no alert.
            await monitoring_alerts.record_health_result(bad)
            # Second failure -> alert would trigger; schedule must return fast.
            t0 = asyncio.get_event_loop().time()
            task = monitoring_alerts.schedule_health_record(bad)
            elapsed = asyncio.get_event_loop().time() - t0
            assert task is not None
            assert elapsed < 0.05, f"schedule blocked for {elapsed:.3f}s"
            # Cancel to avoid leaving a pending task across test boundaries.
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    _run(_scenario())


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
        return True

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


def test_alert_missing_env_aggregates_all_keys_in_one_alert():
    """The lifespan boot path used to call alert_dependency_unreachable
    once per missing key, but the cooldown key was always
    ("startup_dep_fail", "env") — so only the first key paged. The
    aggregated alert sends ONE message containing every missing key,
    and a different missing-set on a later boot produces a NEW alert
    because the cooldown key is derived from the sorted set.
    """
    sent: list[Any] = []

    async def _fake_send(chat_id, text, parse_mode=None):
        sent.append(text)
        return True

    fake_settings = MagicMock(OPERATOR_CHAT_ID=12345)
    with patch(
        "projects.polymarket.crusaderbot.monitoring.alerts.notifications.send",
        new=_fake_send,
    ), patch(
        "projects.polymarket.crusaderbot.monitoring.alerts.get_settings",
        return_value=fake_settings,
    ):
        _run(monitoring_alerts.alert_missing_env(["FOO", "BAR", "BAZ"]))
        assert len(sent) == 1, "must emit a single aggregated alert"
        body = sent[0]
        assert "FOO" in body and "BAR" in body and "BAZ" in body, (
            f"every missing key must appear in the aggregated body: {body!r}"
        )
        # Same set inside the cooldown window: suppressed.
        _run(monitoring_alerts.alert_missing_env(["FOO", "BAR", "BAZ"]))
        assert len(sent) == 1
        # Different set on a later boot: pages immediately because the
        # cooldown key is derived from the sorted missing-set.
        _run(monitoring_alerts.alert_missing_env(["QUX"]))
        assert len(sent) == 2
        assert "QUX" in sent[1]


def test_alert_missing_env_noop_for_empty_list():
    """No alert should fire when the missing list is empty."""
    sent: list[Any] = []

    async def _fake_send(chat_id, text, parse_mode=None):
        sent.append(text)
        return True

    fake_settings = MagicMock(OPERATOR_CHAT_ID=12345)
    with patch(
        "projects.polymarket.crusaderbot.monitoring.alerts.notifications.send",
        new=_fake_send,
    ), patch(
        "projects.polymarket.crusaderbot.monitoring.alerts.get_settings",
        return_value=fake_settings,
    ):
        _run(monitoring_alerts.alert_missing_env([]))
    assert sent == []


def test_dispatch_does_not_arm_cooldown_on_send_failure():
    """A permanent Telegram failure must NOT arm the cooldown — otherwise
    the operator is silenced for 5 minutes during the very outage they
    most need to know about.
    """
    sent: list[Any] = []

    async def _failing_send(chat_id, text, parse_mode=None):
        sent.append((chat_id, text))
        return False  # mimics notifications.send post-retry permanent failure

    fake_settings = MagicMock(OPERATOR_CHAT_ID=12345)
    bad = {
        "status": "down",
        "checks": {"database": "error: down", "telegram": "ok"},
    }
    with patch(
        "projects.polymarket.crusaderbot.monitoring.alerts.notifications.send",
        new=_failing_send,
    ), patch(
        "projects.polymarket.crusaderbot.monitoring.alerts.get_settings",
        return_value=fake_settings,
    ):
        # Cross the threshold to trigger an alert dispatch.
        _run(monitoring_alerts.record_health_result(bad))
        _run(monitoring_alerts.record_health_result(bad))
        first_send_attempts = len(sent)
        assert first_send_attempts == 1, "first dispatch should be attempted"
        # Next probe at the same threshold MUST attempt to send again because
        # the cooldown was not armed by the failed send.
        _run(monitoring_alerts.record_health_result(bad))
    assert len(sent) == 2, (
        "cooldown was armed despite send failure — operator would be "
        "silenced during an active outage"
    )


def test_dispatch_arms_cooldown_only_on_successful_send():
    """When delivery succeeds, the cooldown DOES suppress repeats."""
    sent: list[Any] = []

    async def _ok_send(chat_id, text, parse_mode=None):
        sent.append((chat_id, text))
        return True

    fake_settings = MagicMock(OPERATOR_CHAT_ID=12345)
    bad = {
        "status": "down",
        "checks": {"database": "error: down", "telegram": "ok"},
    }
    with patch(
        "projects.polymarket.crusaderbot.monitoring.alerts.notifications.send",
        new=_ok_send,
    ), patch(
        "projects.polymarket.crusaderbot.monitoring.alerts.get_settings",
        return_value=fake_settings,
    ):
        _run(monitoring_alerts.record_health_result(bad))
        _run(monitoring_alerts.record_health_result(bad))
        assert len(sent) == 1
        _run(monitoring_alerts.record_health_result(bad))
        assert len(sent) == 1, "successful send should arm the cooldown"


def _clear_all_required_env(monkeypatch):
    for key in crusaderbot_config.REQUIRED_ENV_VARS:
        monkeypatch.delenv(key, raising=False)
    for group in crusaderbot_config.REQUIRED_ENV_VAR_GROUPS:
        for key in group:
            monkeypatch.delenv(key, raising=False)


def test_validate_required_env_reads_dotenv_file(tmp_path, monkeypatch):
    """``validate_required_env`` must merge ``.env`` with ``os.environ`` —
    otherwise local/staging deployments running on a ``.env`` file get
    false-positive missing alerts at boot.
    """
    env_path = tmp_path / ".env"
    env_path.write_text(
        "TELEGRAM_BOT_TOKEN=tok\n"
        "DATABASE_URL=postgresql://x\n"
        "ALCHEMY_POLYGON_RPC_URL=https://rpc\n"
        "ALCHEMY_POLYGON_WS_URL=wss://ws\n"
        "OPERATOR_CHAT_ID=42\n"
        "WALLET_HD_SEED=seed\n"
        "WALLET_ENCRYPTION_KEY=k\n"
    )
    _clear_all_required_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    missing = crusaderbot_config.validate_required_env()
    assert missing == [], f"expected zero missing, got {missing!r}"


def test_validate_required_env_accepts_legacy_polygon_rpc_url(tmp_path, monkeypatch):
    """A deployment that supplies only the legacy ``POLYGON_RPC_URL`` (no
    Alchemy alias) is healthy because ``check_alchemy_rpc`` falls back to
    it. Validation must NOT page in that case.
    """
    env_path = tmp_path / ".env"
    env_path.write_text(
        "TELEGRAM_BOT_TOKEN=tok\n"
        "DATABASE_URL=postgresql://x\n"
        "POLYGON_RPC_URL=https://rpc-legacy\n"
        "ALCHEMY_POLYGON_WS_URL=wss://ws\n"
        "OPERATOR_CHAT_ID=42\n"
        "WALLET_HD_SEED=seed\n"
        "WALLET_ENCRYPTION_KEY=k\n"
    )
    _clear_all_required_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    missing = crusaderbot_config.validate_required_env()
    assert missing == [], f"legacy RPC url should satisfy the group: {missing!r}"


def test_validate_required_env_reports_rpc_group_when_no_alias_set(tmp_path, monkeypatch):
    """When NEITHER alias in the RPC group is set, validation must report
    the group exactly once with both candidate names so the operator sees
    a single actionable line rather than two duplicate alerts.
    """
    _clear_all_required_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("ALCHEMY_POLYGON_WS_URL", "wss://ws")
    monkeypatch.setenv("OPERATOR_CHAT_ID", "1")
    monkeypatch.setenv("WALLET_HD_SEED", "seed")
    monkeypatch.setenv("WALLET_ENCRYPTION_KEY", "k")
    missing = crusaderbot_config.validate_required_env()
    assert missing == ["ALCHEMY_POLYGON_RPC_URL or POLYGON_RPC_URL"]


def test_validate_required_env_includes_wallet_hd_seed():
    """REQUIRED_ENV_VARS must list every Settings-required str field so the
    preflight matches Settings's actual contract — a missing WALLET_HD_SEED
    used to pass preflight then crash at get_settings()."""
    assert "WALLET_HD_SEED" in crusaderbot_config.REQUIRED_ENV_VARS


def test_validate_required_env_lists_missing_keys_only(monkeypatch, tmp_path):
    """When neither ``os.environ`` nor ``.env`` has the value, the key
    appears in the missing list — but the actual value never does.
    """
    _clear_all_required_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "secret-token-value")
    missing = crusaderbot_config.validate_required_env()
    assert "TELEGRAM_BOT_TOKEN" not in missing
    assert "DATABASE_URL" in missing
    # Defence in depth: the value must NEVER appear in the returned list.
    assert all("secret-token-value" not in entry for entry in missing)


def test_record_health_result_resets_on_recovery():
    sent: list[Any] = []

    async def _fake_send(chat_id, text, parse_mode=None):
        sent.append((chat_id, text))
        return True

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


# ---------------------------------------------------------------------------
# R12 demo-readiness — /health route shape + activation-guard mode resolution
# ---------------------------------------------------------------------------


def _build_test_app():
    """Mount only the health and admin routers on a fresh FastAPI app.

    Avoids triggering the production lifespan (DB pool, Telegram bot,
    scheduler) which would require live infra credentials. The route
    handlers themselves are pure I/O against ``run_health_checks`` and the
    admin token, so a minimal app is sufficient for shape testing.
    """
    from fastapi import FastAPI
    from projects.polymarket.crusaderbot.api import admin as api_admin
    from projects.polymarket.crusaderbot.api import health as api_health

    app = FastAPI()
    app.include_router(api_health.router)
    app.include_router(api_admin.router)
    return app


def _stub_run_health_checks_ok(monkeypatch):
    """Patch ``run_health_checks`` to return an all-ok result."""
    async def _fake():
        return {
            "status": "ok",
            "service": "CrusaderBot",
            "checks": {"database": "ok", "telegram": "ok",
                       "alchemy_rpc": "ok", "alchemy_ws": "ok"},
            "ready": True,
        }
    monkeypatch.setattr(
        "projects.polymarket.crusaderbot.api.health.run_health_checks",
        _fake,
    )


def test_health_route_demo_readiness_fields(monkeypatch):
    """``GET /health`` must return the brief-required keys alongside the
    deep-deps R12b shape: status, uptime_seconds, version, mode, timestamp.
    """
    from fastapi.testclient import TestClient

    _stub_run_health_checks_ok(monkeypatch)
    monkeypatch.setattr(
        "projects.polymarket.crusaderbot.api.health.get_settings",
        lambda: MagicMock(
            ENABLE_LIVE_TRADING=False,
            EXECUTION_PATH_VALIDATED=False,
            CAPITAL_MODE_CONFIRMED=False,
            APP_VERSION="abc1234",
        ),
    )
    # Avoid triggering Telegram alerts during the test.
    monkeypatch.setattr(
        "projects.polymarket.crusaderbot.api.health.monitoring_alerts.schedule_health_record",
        lambda result: None,
    )

    client = TestClient(_build_test_app())
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    for key in ("status", "uptime_seconds", "version", "mode", "timestamp",
                "service", "checks", "ready"):
        assert key in body, f"missing top-level key: {key}"
    assert body["status"] == "ok"
    assert body["mode"] == "paper"
    assert body["version"] == "abc1234"
    assert isinstance(body["uptime_seconds"], int) and body["uptime_seconds"] >= 0
    # Timestamp must be an ISO-8601 UTC string (Z suffix per the helper).
    assert body["timestamp"].endswith("Z")


def test_health_mode_paper_when_any_guard_off(monkeypatch):
    """``mode`` reads activation guards: ``paper`` if any of
    EXECUTION_PATH_VALIDATED / CAPITAL_MODE_CONFIRMED / ENABLE_LIVE_TRADING
    is unset. Live mode requires ALL three explicitly True.
    """
    from fastapi.testclient import TestClient

    _stub_run_health_checks_ok(monkeypatch)
    monkeypatch.setattr(
        "projects.polymarket.crusaderbot.api.health.monitoring_alerts.schedule_health_record",
        lambda result: None,
    )
    client = TestClient(_build_test_app())

    cases = [
        # (ENABLE_LIVE, EXEC_VALIDATED, CAPITAL_CONFIRMED, expected mode)
        (False, False, False, "paper"),
        (True,  False, False, "paper"),
        (True,  True,  False, "paper"),
        (False, True,  True,  "paper"),
        (True,  True,  True,  "live"),
    ]
    for enable_live, exec_v, cap_v, expected in cases:
        monkeypatch.setattr(
            "projects.polymarket.crusaderbot.api.health.get_settings",
            lambda e=enable_live, x=exec_v, c=cap_v: MagicMock(
                ENABLE_LIVE_TRADING=e,
                EXECUTION_PATH_VALIDATED=x,
                CAPITAL_MODE_CONFIRMED=c,
                APP_VERSION="t",
            ),
        )
        r = client.get("/health")
        assert r.json()["mode"] == expected, (
            f"guards=({enable_live}, {exec_v}, {cap_v}) "
            f"expected mode={expected} got={r.json()['mode']}"
        )


def test_health_version_falls_back_to_unknown(monkeypatch):
    """When neither ``APP_VERSION`` nor ``FLY_RELEASE_VERSION`` is set the
    version field reads ``"unknown"`` rather than the literal ``None`` so
    JSON consumers do not have to branch on type.
    """
    from fastapi.testclient import TestClient

    _stub_run_health_checks_ok(monkeypatch)
    monkeypatch.setattr(
        "projects.polymarket.crusaderbot.api.health.get_settings",
        lambda: MagicMock(
            ENABLE_LIVE_TRADING=False,
            EXECUTION_PATH_VALIDATED=False,
            CAPITAL_MODE_CONFIRMED=False,
            APP_VERSION=None,
        ),
    )
    monkeypatch.setattr(
        "projects.polymarket.crusaderbot.api.health.monitoring_alerts.schedule_health_record",
        lambda result: None,
    )
    monkeypatch.delenv("FLY_RELEASE_VERSION", raising=False)
    client = TestClient(_build_test_app())
    r = client.get("/health")
    assert r.json()["version"] == "unknown"


def test_health_version_falls_back_to_fly_release_version(monkeypatch):
    """Codex P2: when ``APP_VERSION`` is unset (e.g. a manual ``flyctl
    deploy`` that bypassed the CD workflow's git-SHA stamping, or a
    rollback to a previous image), the route must surface Fly's built-in
    ``FLY_RELEASE_VERSION`` so the rollback runbook's "/health .version
    matches expected" check still produces a meaningful, distinct value.
    The fallback is prefixed with ``fly-v`` so consumers can distinguish
    it from a git SHA at a glance.
    """
    from fastapi.testclient import TestClient

    _stub_run_health_checks_ok(monkeypatch)
    monkeypatch.setattr(
        "projects.polymarket.crusaderbot.api.health.get_settings",
        lambda: MagicMock(
            ENABLE_LIVE_TRADING=False,
            EXECUTION_PATH_VALIDATED=False,
            CAPITAL_MODE_CONFIRMED=False,
            APP_VERSION=None,
        ),
    )
    monkeypatch.setattr(
        "projects.polymarket.crusaderbot.api.health.monitoring_alerts.schedule_health_record",
        lambda result: None,
    )
    monkeypatch.setenv("FLY_RELEASE_VERSION", "62")
    client = TestClient(_build_test_app())
    r = client.get("/health")
    assert r.json()["version"] == "fly-v62"


def test_health_version_app_version_takes_precedence_over_fly(monkeypatch):
    """When both env vars are set, ``APP_VERSION`` (the CD-stamped git
    short SHA) wins over ``FLY_RELEASE_VERSION``. Ordering matters
    because the rollback runbook expects a SHA when the CD path is
    healthy and the fly fallback only when it isn't.
    """
    from fastapi.testclient import TestClient

    _stub_run_health_checks_ok(monkeypatch)
    monkeypatch.setattr(
        "projects.polymarket.crusaderbot.api.health.get_settings",
        lambda: MagicMock(
            ENABLE_LIVE_TRADING=False,
            EXECUTION_PATH_VALIDATED=False,
            CAPITAL_MODE_CONFIRMED=False,
            APP_VERSION="abc1234",
        ),
    )
    monkeypatch.setattr(
        "projects.polymarket.crusaderbot.api.health.monitoring_alerts.schedule_health_record",
        lambda result: None,
    )
    monkeypatch.setenv("FLY_RELEASE_VERSION", "62")
    client = TestClient(_build_test_app())
    r = client.get("/health")
    assert r.json()["version"] == "abc1234"


# ---------------------------------------------------------------------------
# R12 demo-readiness — /admin/sentry-test admin gate + DSN-unset behaviour
# ---------------------------------------------------------------------------


def test_admin_sentry_test_requires_admin_token(monkeypatch):
    """Without ``ADMIN_API_TOKEN`` the endpoint is disabled (503); with the
    token set, requests missing or mis-supplying the bearer are rejected.
    """
    from fastapi.testclient import TestClient

    # Disabled when ADMIN_API_TOKEN unset.
    monkeypatch.setattr(
        "projects.polymarket.crusaderbot.api.admin.get_settings",
        lambda: MagicMock(ADMIN_API_TOKEN=None),
    )
    client = TestClient(_build_test_app())
    r = client.post("/admin/sentry-test")
    assert r.status_code == 503

    # Enabled — wrong token rejected, missing token rejected.
    monkeypatch.setattr(
        "projects.polymarket.crusaderbot.api.admin.get_settings",
        lambda: MagicMock(ADMIN_API_TOKEN="t-secret"),
    )
    r = client.post("/admin/sentry-test")
    assert r.status_code == 403
    r = client.post("/admin/sentry-test", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 403


def test_admin_sentry_test_reports_dsn_unset_when_not_initialised(monkeypatch):
    """When the SDK was never initialised the endpoint returns ``ok=False``
    with a runbook-actionable reason rather than 500ing.
    """
    from fastapi.testclient import TestClient
    from projects.polymarket.crusaderbot.monitoring import sentry as monitoring_sentry

    monitoring_sentry.reset_for_tests()
    monkeypatch.setattr(
        "projects.polymarket.crusaderbot.api.admin.get_settings",
        lambda: MagicMock(ADMIN_API_TOKEN="t"),
    )
    client = TestClient(_build_test_app())
    r = client.post(
        "/admin/sentry-test",
        headers={"Authorization": "Bearer t"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "ok": False,
        "reason": "sentry_not_initialised",
        "hint": "set SENTRY_DSN as a Fly.io secret and redeploy",
    }


def test_admin_sentry_test_returns_event_id_when_initialised(monkeypatch):
    """When Sentry is active the endpoint returns the captured event id."""
    from fastapi.testclient import TestClient
    from projects.polymarket.crusaderbot.monitoring import sentry as monitoring_sentry

    monkeypatch.setattr(
        "projects.polymarket.crusaderbot.api.admin.get_settings",
        lambda: MagicMock(ADMIN_API_TOKEN="t"),
    )
    monkeypatch.setattr(monitoring_sentry, "_initialised", True, raising=False)
    monkeypatch.setattr(
        monitoring_sentry,
        "capture_test_event",
        lambda message: "evt-fake-id-123",
    )
    try:
        client = TestClient(_build_test_app())
        r = client.post(
            "/admin/sentry-test",
            headers={"Authorization": "Bearer t"},
        )
        assert r.status_code == 200
        assert r.json() == {"ok": True, "event_id": "evt-fake-id-123"}
    finally:
        monitoring_sentry.reset_for_tests()


def test_init_sentry_noop_when_dsn_unset(monkeypatch):
    """``init_sentry`` must be a quiet no-op when ``SENTRY_DSN`` is unset
    so local / CI runs never ship synthetic events to the prod project.

    Reads from ``os.environ`` directly (not via ``Settings``) so a
    partially-configured environment cannot raise a pydantic
    ``ValidationError`` and break the no-op contract.
    """
    from projects.polymarket.crusaderbot.monitoring import sentry as monitoring_sentry

    monitoring_sentry.reset_for_tests()
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    assert monitoring_sentry.init_sentry() is False
    assert monitoring_sentry.is_initialised() is False


def test_init_sentry_noop_does_not_depend_on_required_app_env(monkeypatch):
    """Codex P2: ``init_sentry`` must NOT construct the full ``Settings``
    model — doing so would validate required app secrets like
    ``TELEGRAM_BOT_TOKEN`` / ``DATABASE_URL`` and raise
    ``pydantic.ValidationError`` in a partially-configured env, breaking
    the documented quiet-no-op contract. Sentry init must be entirely
    independent of the rest of app config so it can run *first* in the
    lifespan hook and capture any subsequent settings-validation
    failures.

    Strip every required app secret from the env, leave SENTRY_DSN
    unset, and assert that init_sentry returns False without raising.
    """
    from projects.polymarket.crusaderbot.monitoring import sentry as monitoring_sentry

    monitoring_sentry.reset_for_tests()
    for required in (
        "SENTRY_DSN", "TELEGRAM_BOT_TOKEN", "OPERATOR_CHAT_ID", "DATABASE_URL",
        "POLYGON_RPC_URL", "ALCHEMY_POLYGON_RPC_URL", "ALCHEMY_POLYGON_WS_URL",
        "WALLET_HD_SEED", "WALLET_ENCRYPTION_KEY",
    ):
        monkeypatch.delenv(required, raising=False)
    # Must NOT raise — and must be a quiet no-op return.
    assert monitoring_sentry.init_sentry() is False
    assert monitoring_sentry.is_initialised() is False


def test_settings_does_not_validate_sentry_traces_sample_rate(monkeypatch):
    """Codex P2 (round 2): a malformed ``SENTRY_TRACES_SAMPLE_RATE`` Fly env
    value (operator typo) must NOT break ``Settings()`` construction —
    otherwise an optional observability knob becomes a boot blocker that
    impacts every later ``get_settings()`` call (admin/health requests,
    health probes, scheduler jobs).

    Fix: ``SENTRY_TRACES_SAMPLE_RATE`` is removed from the ``Settings``
    model entirely; ``monitoring.sentry`` reads it directly from
    ``os.environ`` with tolerant float-parsing. This test asserts the
    decoupling holds.
    """
    crusaderbot_config.get_settings.cache_clear()
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("OPERATOR_CHAT_ID", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("WALLET_HD_SEED", "seed")
    monkeypatch.setenv("WALLET_ENCRYPTION_KEY", "k")
    monkeypatch.setenv("POLYGON_RPC_URL", "https://rpc")
    monkeypatch.setenv("ALCHEMY_POLYGON_WS_URL", "wss://ws")
    # Garbage value the operator might typo into Fly secrets:
    monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "not-a-float")

    # Must NOT raise pydantic.ValidationError.
    settings = crusaderbot_config.Settings()  # type: ignore[call-arg]
    # Field is intentionally absent from the model now.
    assert not hasattr(settings, "SENTRY_TRACES_SAMPLE_RATE")
    # Settings still functions normally for the rest of the surface.
    assert settings.TELEGRAM_BOT_TOKEN == "tok"

    crusaderbot_config.get_settings.cache_clear()


def test_init_sentry_traces_sample_rate_malformed_falls_back(monkeypatch):
    """A malformed ``SENTRY_TRACES_SAMPLE_RATE`` env value (non-numeric)
    must fall back to 0.0 rather than raising — env-reads cannot block
    boot. The call returns False because no DSN is set, but it must
    return without an exception even with the malformed value present.
    """
    from projects.polymarket.crusaderbot.monitoring import sentry as monitoring_sentry

    monitoring_sentry.reset_for_tests()
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "not-a-float")
    # _read_traces_sample_rate is only called when DSN is set, so this
    # asserts the no-op path doesn't reach into env parsing prematurely.
    # Direct unit check on the helper too:
    assert monitoring_sentry._read_traces_sample_rate() == 0.0
    assert monitoring_sentry.init_sentry() is False
