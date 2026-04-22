from __future__ import annotations

import asyncio
import sys
import types

import pytest

from projects.polymarket.polyquantbot.infra.db import DatabaseClient
from projects.polymarket.polyquantbot.infra.db.runtime_config import load_database_runtime_config


def test_load_database_runtime_config_prefers_database_url(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@db.example.com:5432/crusader")
    monkeypatch.setenv("DB_DSN", "postgresql://legacy:pass@legacy.example.com:5432/legacy")

    cfg = load_database_runtime_config()

    assert cfg.source == "DATABASE_URL"
    assert cfg.host == "db.example.com"
    assert "sslmode=require" in cfg.dsn


def test_load_database_runtime_config_uses_legacy_fallback(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DB_DSN", "postgresql://user:pass@localhost:5432/crusader")

    cfg = load_database_runtime_config()

    assert cfg.source == "DB_DSN_COMPAT"
    assert cfg.host == "localhost"
    assert cfg.dsn == "postgresql://user:pass@localhost:5432/crusader"


def test_load_database_runtime_config_rejects_non_require_sslmode_for_remote_host(monkeypatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://user:pass@db.example.com:5432/crusader?sslmode=disable",
    )
    monkeypatch.delenv("DB_DSN", raising=False)

    with pytest.raises(ValueError, match="sslmode=require"):
        load_database_runtime_config()


def test_database_client_connect_with_retry_calls_connect_and_ensure_schema(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/crusader")
    calls = {"connect": 0, "ensure_schema": 0}

    async def _connect_ok(self) -> None:
        calls["connect"] += 1

    async def _ensure_schema_ok(self) -> None:
        calls["ensure_schema"] += 1

    monkeypatch.setattr(DatabaseClient, "connect", _connect_ok)
    monkeypatch.setattr(DatabaseClient, "ensure_schema", _ensure_schema_ok)

    client = DatabaseClient()
    asyncio.run(client.connect_with_retry(max_attempts=1))

    assert calls == {"connect": 1, "ensure_schema": 1}


def test_server_main_uses_database_client_with_retry_and_healthcheck_methods() -> None:
    pytest.importorskip("fastapi")
    if "uvicorn" not in sys.modules:
        sys.modules["uvicorn"] = types.ModuleType("uvicorn")
    from projects.polymarket.polyquantbot.server import main as server_main

    assert server_main.DatabaseClient is DatabaseClient
    assert hasattr(DatabaseClient, "connect_with_retry")
    assert hasattr(DatabaseClient, "healthcheck")
