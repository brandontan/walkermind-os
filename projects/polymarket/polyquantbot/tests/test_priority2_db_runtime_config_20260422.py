from __future__ import annotations

import pytest

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
