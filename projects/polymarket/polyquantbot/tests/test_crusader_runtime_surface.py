from __future__ import annotations

import asyncio
import pytest

pytest.importorskip(
    "fastapi",
    reason="Phase 8.9 runtime-surface contract checks require FastAPI; skipped suites are not runtime proof.",
)
from fastapi.testclient import TestClient

from projects.polymarket.polyquantbot.server.core.runtime import (
    ApiSettings,
    validate_api_environment,
)
from projects.polymarket.polyquantbot.server.api.routes import _dependency_failure_category
from projects.polymarket.polyquantbot.server.main import create_app

_TEST_DB_DSN = "postgresql://test-user:test-pass@localhost:5432/test_crusader"


@pytest.mark.parametrize(
    ("route", "required_keys"),
    [
        ("/health", {"service", "runtime", "status"}),
        ("/ready", {"status", "validation_errors", "readiness"}),
        ("/beta/status", {"paper_only_execution_boundary", "execution_guard", "managed_beta_state", "exit_criteria"}),
        ("/beta/admin", {"paper_only_execution_boundary", "admin_summary", "managed_beta_state", "exit_criteria"}),
    ],
)
def test_runtime_surface_contract_keys_are_present(monkeypatch, route: str, required_keys: set[str]) -> None:
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    app = create_app()
    with TestClient(app) as client:
        response = client.get(route)
    assert response.status_code == 200
    payload = response.json()
    assert required_keys.issubset(set(payload.keys()))


def test_api_settings_uses_fly_port(monkeypatch) -> None:
    monkeypatch.setenv("PORT", "9090")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    settings = ApiSettings.from_env()
    assert settings.port == 9090


def test_api_settings_rejects_non_strict_startup_mode(monkeypatch) -> None:
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    monkeypatch.setenv("CRUSADER_STARTUP_MODE", "warn")
    try:
        ApiSettings.from_env()
    except RuntimeError as exc:
        assert "CRUSADER_STARTUP_MODE" in str(exc)
    else:
        raise AssertionError("ApiSettings.from_env() should reject non-strict startup mode.")


def test_validate_api_environment_accepts_paper_defaults(monkeypatch) -> None:
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    settings = ApiSettings.from_env()
    assert validate_api_environment(settings) == []


def test_health_route_reports_crusaderbot_service(monkeypatch) -> None:
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["service"] == "CrusaderBot"
    assert payload["runtime"] == "server.main"
    assert payload["status"] == "ok"


def test_ready_route_reports_ready_after_startup(monkeypatch) -> None:
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/ready")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["validation_errors"] == []


def test_ready_route_reports_readiness_dimensions(monkeypatch) -> None:
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/ready")
    payload = response.json()
    readiness = payload["readiness"]

    assert "scope" in readiness
    assert "worker_runtime" in readiness
    assert "telegram_runtime" in readiness
    assert "db_runtime" in readiness
    assert "worker_prerequisites" in readiness
    assert "falcon_config_state" in readiness
    assert "dependency_gates" in readiness
    assert "control_plane" in readiness
    assert "monitoring_outputs" in readiness
    assert readiness["control_plane"]["paper_only_execution_boundary"] is True
    assert readiness["monitoring_outputs"]["operator_trace_contract"] == (
        "startup_shutdown_dependency_monitoring_minimum_v1"
    )
    assert isinstance(readiness["monitoring_outputs"]["failure_present"], bool)
    assert readiness["monitoring_outputs"]["last_dependency_failure_category"] in {
        "none",
        "runtime_error",
        "timeout",
        "healthcheck_failed",
        "connection_failed",
    }
    assert "last_dependency_failure_error" not in readiness["monitoring_outputs"]


@pytest.mark.parametrize(
    ("raw_error", "expected"),
    [
        ("", "none"),
        ("telegram_shutdown_timeout", "timeout"),
        ("Database healthcheck failed after startup connect path.", "healthcheck_failed"),
        ("db_connect_refused", "connection_failed"),
        ("unexpected_runtime_boom", "runtime_error"),
    ],
)
def test_dependency_failure_category_is_sanitized(raw_error: str, expected: str) -> None:
    assert _dependency_failure_category(raw_error) == expected


def test_beta_admin_route_exists_and_preserves_paper_boundary(monkeypatch) -> None:
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/beta/admin")
    assert response.status_code == 200
    payload = response.json()
    assert payload["paper_only_execution_boundary"] is True
    assert payload["admin_summary"]["live_execution_privileges_enabled"] is False


def test_ready_route_reports_readiness_semantics(monkeypatch) -> None:
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    monkeypatch.setenv("FALCON_ENABLED", "false")
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/ready")
    assert response.status_code == 200
    payload = response.json()
    readiness = payload["readiness"]

    assert readiness["scope"]["runtime_assertion"] == "local_runtime_only"
    assert readiness["scope"]["external_dependencies_probed"] is True
    assert readiness["scope"]["worker_state_visibility"] == "in_process_state_snapshot"
    assert readiness["worker_runtime"]["last_iteration_visible"] is False
    assert readiness["worker_prerequisites"]["paper_mode_enforced"] is True
    assert readiness["worker_prerequisites"]["execution_ready_for_paper_entries"] is False
    assert readiness["falcon_config_state"]["enabled"] is False
    assert readiness["falcon_config_state"]["config_valid_for_enabled_mode"] is True
    assert readiness["control_plane"]["live_mode_execution_allowed"] is False


def test_startup_success_path_sets_db_runtime_ready(monkeypatch) -> None:
    class _HealthyDBClient:
        async def connect_with_retry(self, max_attempts: int = 4, base_backoff_s: float = 1.0) -> None:
            return None

        async def healthcheck(self) -> bool:
            return True

        async def close(self) -> None:
            return None

    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    monkeypatch.setenv("CRUSADER_DB_RUNTIME_ENABLED", "true")
    monkeypatch.setenv("CRUSADER_DB_RUNTIME_REQUIRED", "true")
    monkeypatch.setenv("DB_DSN", _TEST_DB_DSN)
    monkeypatch.setattr("projects.polymarket.polyquantbot.server.main.DatabaseClient", _HealthyDBClient)
    app = create_app()

    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    readiness = response.json()["readiness"]
    assert readiness["db_runtime"]["enabled"] is True
    assert readiness["db_runtime"]["required"] is True
    assert readiness["db_runtime"]["connected"] is True
    assert readiness["db_runtime"]["healthcheck_ok"] is True


def test_startup_failure_before_yield_closes_db_client(monkeypatch) -> None:
    class _DBClient:
        close_called = False

        async def connect_with_retry(self, max_attempts: int = 4, base_backoff_s: float = 1.0) -> None:
            return None

        async def healthcheck(self) -> bool:
            return True

        async def close(self) -> None:
            _DBClient.close_called = True

    async def _boom(state) -> None:  # noqa: ANN001
        raise RuntimeError("telegram_startup_failed")

    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    monkeypatch.setenv("CRUSADER_DB_RUNTIME_ENABLED", "true")
    monkeypatch.setenv("CRUSADER_DB_RUNTIME_REQUIRED", "true")
    monkeypatch.setenv("DB_DSN", _TEST_DB_DSN)
    monkeypatch.setattr("projects.polymarket.polyquantbot.server.main.DatabaseClient", _DBClient)
    monkeypatch.setattr("projects.polymarket.polyquantbot.server.main._start_telegram_runtime", _boom)
    app = create_app()

    with pytest.raises(RuntimeError, match="telegram_startup_failed"):
        with TestClient(app):
            pass

    assert _DBClient.close_called is True
    assert app.state.crusader_runtime.ready is False
    assert app.state.crusader_runtime.db_client is None


def test_bounded_retry_timeout_alignment_preserves_retry_path(monkeypatch) -> None:
    class _SlowFailingDBClient:
        seen_max_attempts = 0

        async def connect_with_retry(self, max_attempts: int = 4, base_backoff_s: float = 1.0) -> None:
            _SlowFailingDBClient.seen_max_attempts = max_attempts
            await asyncio.sleep(0.01)
            raise RuntimeError("db_unavailable")

        async def healthcheck(self) -> bool:
            return False

        async def close(self) -> None:
            return None

    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    monkeypatch.setenv("CRUSADER_DB_RUNTIME_ENABLED", "true")
    monkeypatch.setenv("CRUSADER_DB_RUNTIME_REQUIRED", "false")
    monkeypatch.setenv("DB_DSN", _TEST_DB_DSN)
    monkeypatch.setenv("CRUSADER_DB_CONNECT_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("CRUSADER_DB_CONNECT_BASE_BACKOFF_S", "0.01")
    monkeypatch.setenv("CRUSADER_DB_CONNECT_TIMEOUT_S", "0.02")
    monkeypatch.setattr("projects.polymarket.polyquantbot.server.main.DatabaseClient", _SlowFailingDBClient)
    app = create_app()

    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    readiness = response.json()["readiness"]["db_runtime"]
    assert _SlowFailingDBClient.seen_max_attempts == 3
    assert readiness["connect_timeout_s"] > 0.02


def test_ready_status_after_db_unavailable_when_required(monkeypatch) -> None:
    class _UnhealthyDBClient:
        async def connect_with_retry(self, max_attempts: int = 4, base_backoff_s: float = 1.0) -> None:
            return None

        async def healthcheck(self) -> bool:
            return False

        async def close(self) -> None:
            return None

    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    monkeypatch.setenv("CRUSADER_DB_RUNTIME_ENABLED", "true")
    monkeypatch.setenv("CRUSADER_DB_RUNTIME_REQUIRED", "true")
    monkeypatch.setenv("DB_DSN", _TEST_DB_DSN)
    monkeypatch.setattr("projects.polymarket.polyquantbot.server.main.DatabaseClient", _UnhealthyDBClient)
    app = create_app()

    with pytest.raises(RuntimeError, match="Database healthcheck failed"):
        with TestClient(app):
            pass


def test_ready_status_after_db_unavailable_when_not_required(monkeypatch) -> None:
    class _UnavailableDBClient:
        async def connect_with_retry(self, max_attempts: int = 4, base_backoff_s: float = 1.0) -> None:
            raise RuntimeError("db_unavailable")

        async def healthcheck(self) -> bool:
            return False

        async def close(self) -> None:
            return None

    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    monkeypatch.setenv("CRUSADER_DB_RUNTIME_ENABLED", "true")
    monkeypatch.setenv("CRUSADER_DB_RUNTIME_REQUIRED", "false")
    monkeypatch.setenv("DB_DSN", _TEST_DB_DSN)
    monkeypatch.setattr("projects.polymarket.polyquantbot.server.main.DatabaseClient", _UnavailableDBClient)
    app = create_app()

    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    readiness = response.json()["readiness"]["db_runtime"]
    assert readiness["relevant"] is True
    assert readiness["connected"] is False
    assert readiness["healthcheck_ok"] is False
    assert readiness["last_error"] != ""


def test_ready_route_not_ready_when_telegram_required_without_token(monkeypatch) -> None:
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    monkeypatch.setenv("CRUSADER_TELEGRAM_RUNTIME_REQUIRED", "true")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    app = create_app()
    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN is required"):
        with TestClient(app):
            pass


def test_ready_route_falcon_enabled_without_key_is_not_valid(monkeypatch) -> None:
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    monkeypatch.setenv("FALCON_ENABLED", "true")
    monkeypatch.delenv("FALCON_API_KEY", raising=False)
    app = create_app()
    with pytest.raises(
        RuntimeError,
        match="FALCON_API_KEY is required when FALCON_ENABLED=true",
    ):
        with TestClient(app):
            pass
