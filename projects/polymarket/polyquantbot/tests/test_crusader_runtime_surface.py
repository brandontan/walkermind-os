from __future__ import annotations

from fastapi.testclient import TestClient

from projects.polymarket.polyquantbot.server.core.runtime import ApiSettings, validate_api_environment
from projects.polymarket.polyquantbot.server.main import create_app


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

    assert "worker_runtime" in readiness
    assert "worker_prerequisites" in readiness
    assert "falcon_config_state" in readiness
    assert "control_plane" in readiness
    assert readiness["control_plane"]["paper_only_execution_boundary"] is True
