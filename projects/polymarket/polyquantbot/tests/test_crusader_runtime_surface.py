from __future__ import annotations

import pytest

pytest.importorskip(
    "fastapi",
    reason="Phase 8.9 runtime-surface contract checks require FastAPI; skipped suites are not runtime proof.",
)
from fastapi.testclient import TestClient

from projects.polymarket.polyquantbot.server.core.runtime import ApiSettings, validate_api_environment
from projects.polymarket.polyquantbot.server.main import create_app


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
    assert "worker_prerequisites" in readiness
    assert "falcon_config_state" in readiness
    assert "control_plane" in readiness
    assert readiness["control_plane"]["paper_only_execution_boundary"] is True


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
    assert readiness["scope"]["external_dependencies_probed"] is False
    assert readiness["scope"]["worker_state_visibility"] == "in_process_state_snapshot"
    assert readiness["worker_runtime"]["last_iteration_visible"] is False
    assert readiness["worker_prerequisites"]["paper_mode_enforced"] is True
    assert readiness["worker_prerequisites"]["execution_ready_for_paper_entries"] is False
    assert readiness["falcon_config_state"]["enabled"] is False
    assert readiness["falcon_config_state"]["config_valid_for_enabled_mode"] is True
    assert readiness["control_plane"]["live_mode_execution_allowed"] is False


def test_ready_route_not_ready_when_telegram_required_without_token(monkeypatch) -> None:
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    monkeypatch.setenv("CRUSADER_TELEGRAM_RUNTIME_REQUIRED", "true")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/ready")
    assert response.status_code == 503
    readiness = response.json()["readiness"]
    assert readiness["telegram_runtime"]["required"] is True
    assert readiness["telegram_runtime"]["enabled"] is False


def test_ready_route_falcon_enabled_without_key_is_not_valid(monkeypatch) -> None:
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    monkeypatch.setenv("FALCON_ENABLED", "true")
    monkeypatch.delenv("FALCON_API_KEY", raising=False)
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/ready")
    readiness = response.json()["readiness"]
    assert readiness["falcon_config_state"]["enabled"] is True
    assert readiness["falcon_config_state"]["api_key_configured"] is False
    assert readiness["falcon_config_state"]["enabled_without_api_key"] is True
    assert readiness["falcon_config_state"]["config_valid_for_enabled_mode"] is False
