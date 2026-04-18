from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from projects.polymarket.polyquantbot.server.core.runtime import ApiSettings
from projects.polymarket.polyquantbot.server.main import create_app


def test_api_settings_uses_fly_port(monkeypatch) -> None:
    monkeypatch.setenv("PORT", "9090")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    settings = ApiSettings.from_env()
    assert settings.port == 9090


def test_api_settings_accepts_default_strict_startup_mode(monkeypatch) -> None:
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    monkeypatch.delenv("CRUSADER_STARTUP_MODE", raising=False)
    settings = ApiSettings.from_env()
    assert settings.startup_mode == "strict"


def test_api_settings_rejects_warn_startup_mode(monkeypatch) -> None:
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    monkeypatch.setenv("CRUSADER_STARTUP_MODE", "warn")
    with pytest.raises(RuntimeError, match="CRUSADER_STARTUP_MODE must be 'strict'."):
        ApiSettings.from_env()


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


def test_ready_route_returns_ready_when_startup_validation_passes(monkeypatch) -> None:
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_runtime_docs_match_fly_health_check_contract() -> None:
    project_root = Path("projects/polymarket/polyquantbot")
    docs_text = (project_root / "docs/crusader_runtime_surface.md").read_text(encoding="utf-8")
    fly_text = (project_root / "fly.toml").read_text(encoding="utf-8")

    assert "Fly health checks currently target `GET /health` only." in docs_text
    assert "is not currently configured as a Fly check path." in docs_text
    assert 'path = "/health"' in fly_text
