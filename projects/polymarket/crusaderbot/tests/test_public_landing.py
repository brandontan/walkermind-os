from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from projects.polymarket.crusaderbot import main as app_main
from projects.polymarket.crusaderbot.api import admin as api_admin
from projects.polymarket.crusaderbot.api import health as api_health
from projects.polymarket.crusaderbot.api import ops as api_ops


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(api_health.router)
    app.include_router(api_admin.router)
    app.include_router(api_ops.router)
    app.add_api_route("/", app_main.root, methods=["GET"])
    return app


def test_public_landing_page_contract(monkeypatch):
    async def _fake_health(_response):
        return {
            "status": "ok",
            "uptime_seconds": 120,
            "version": "test",
            "mode": "paper",
            "timestamp": "2026-05-14T12:00:00Z",
            "service": "CrusaderBot",
            "checks": {
                "database": "ok",
                "telegram": "ok",
            },
            "ready": True,
        }

    monkeypatch.setattr(app_main.api_health, "health", _fake_health)

    client = TestClient(_build_app())
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")

    body = r.text
    for token in [
        "CrusaderBot",
        "PAPER ONLY",
        "Fly.io",
        "Health",
        "Server Status",
        "Activation Guards",
        "ENABLE_LIVE_TRADING",
        "EXECUTION_PATH_VALIDATED",
        "CAPITAL_MODE_CONFIRMED",
        "RISK_CONTROLS_VALIDATED",
        "Not financial advice",
        "/health",
    ]:
        assert token in body


def test_health_contract_remains_machine_readable(monkeypatch):
    async def _fake_checks():
        return {
            "status": "ok",
            "service": "CrusaderBot",
            "checks": {
                "database": "ok",
                "telegram": "ok",
                "alchemy_rpc": "ok",
                "alchemy_ws": "ok",
            },
            "ready": True,
        }

    monkeypatch.setattr(api_health, "run_health_checks", _fake_checks)
    monkeypatch.setattr(api_health, "_resolve_version", lambda: "test")
    monkeypatch.setattr(api_health, "_resolve_mode", lambda: "paper")

    client = TestClient(_build_app())
    r = client.get("/health")
    assert r.status_code == 200
    assert "application/json" in r.headers.get("content-type", "")

    data = r.json()
    assert set(data.keys()) == {
        "status",
        "uptime_seconds",
        "version",
        "mode",
        "timestamp",
        "service",
        "checks",
        "ready",
    }
