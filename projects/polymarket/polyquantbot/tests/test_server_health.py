"""Tests for CrusaderBot FastAPI health and readiness endpoints."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Ensure repo root is on sys.path for absolute imports.
_repo_root = Path(__file__).resolve().parents[4]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))


@pytest.fixture()
def app_client(monkeypatch: pytest.MonkeyPatch):
    """Return a synchronous TestClient with DB_DSN set to avoid /ready 503."""
    monkeypatch.setenv("DB_DSN", "postgresql://test:test@localhost/test_crusaderbot")
    from fastapi.testclient import TestClient
    from projects.polymarket.polyquantbot.server.main import app

    with TestClient(app) as client:
        yield client


@pytest.fixture()
def app_client_no_db(monkeypatch: pytest.MonkeyPatch):
    """Return a TestClient WITHOUT DB_DSN to test /ready 503 path."""
    monkeypatch.delenv("DB_DSN", raising=False)
    from fastapi.testclient import TestClient
    from projects.polymarket.polyquantbot.server.main import app

    with TestClient(app) as client:
        yield client


class TestHealthEndpoint:
    def test_health_returns_200(self, app_client) -> None:
        resp = app_client.get("/health")
        assert resp.status_code == 200

    def test_health_body_app_name(self, app_client) -> None:
        body = app_client.get("/health").json()
        assert body["app"] == "CrusaderBot"

    def test_health_body_status_ok(self, app_client) -> None:
        body = app_client.get("/health").json()
        assert body["status"] == "ok"

    def test_health_body_has_version(self, app_client) -> None:
        body = app_client.get("/health").json()
        assert "version" in body

    def test_health_reachable_without_db(self, app_client_no_db) -> None:
        """Health must return 200 even when DB_DSN is absent (liveness != readiness)."""
        resp = app_client_no_db.get("/health")
        assert resp.status_code == 200


class TestReadyEndpoint:
    def test_ready_200_when_db_set(self, app_client) -> None:
        resp = app_client.get("/ready")
        assert resp.status_code == 200

    def test_ready_body_status_ready(self, app_client) -> None:
        body = app_client.get("/ready").json()
        assert body["status"] == "ready"

    def test_ready_body_app_name(self, app_client) -> None:
        body = app_client.get("/ready").json()
        assert body["app"] == "CrusaderBot"

    def test_ready_503_when_db_missing(self, app_client_no_db) -> None:
        resp = app_client_no_db.get("/ready")
        assert resp.status_code == 503

    def test_ready_503_body_lists_missing_env(self, app_client_no_db) -> None:
        body = app_client_no_db.get("/ready").json()
        assert body["status"] == "not_ready"
        assert "DB_DSN" in body["missing_env"]


class TestAppMetadata:
    def test_app_title_is_crusaderbot(self, app_client) -> None:
        resp = app_client.get("/openapi.json")
        assert resp.status_code == 200
        assert resp.json()["info"]["title"] == "CrusaderBot"
