from __future__ import annotations

import os

from fastapi.testclient import TestClient

from projects.polymarket.polyquantbot.server.core.runtime import ApiSettings, validate_api_environment
from projects.polymarket.polyquantbot.server.main import create_app


def test_api_settings_uses_fly_port(monkeypatch) -> None:
    monkeypatch.setenv("PORT", "9090")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    settings = ApiSettings.from_env()
    assert settings.port == 9090


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
