from __future__ import annotations

from projects.polymarket.polyquantbot.server.core.runtime import (
    ApiSettings,
    RuntimeState,
    startup_config_summary,
    validate_runtime_dependencies_from_env,
)


def test_runtime_dependency_validation_requires_db_dsn_when_db_enabled(monkeypatch) -> None:
    monkeypatch.setenv("CRUSADER_DB_RUNTIME_ENABLED", "true")
    monkeypatch.delenv("DB_DSN", raising=False)
    errors = validate_runtime_dependencies_from_env()
    assert any("DB_DSN is required when CRUSADER_DB_RUNTIME_ENABLED=true" in error for error in errors)


def test_runtime_dependency_validation_requires_falcon_api_key_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("FALCON_ENABLED", "true")
    monkeypatch.delenv("FALCON_API_KEY", raising=False)
    errors = validate_runtime_dependencies_from_env()
    assert any("FALCON_API_KEY is required when FALCON_ENABLED=true" in error for error in errors)


def test_startup_config_summary_redacts_secret_values(monkeypatch) -> None:
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    monkeypatch.setenv("DB_DSN", "postgresql://secret-user:secret-pass@db.example:5432/db")
    monkeypatch.setenv("FALCON_ENABLED", "true")
    monkeypatch.setenv("FALCON_API_KEY", "secret-key")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "secret-telegram-token")

    settings = ApiSettings.from_env()
    summary = startup_config_summary(settings)

    assert summary["db_dsn_configured"] is True
    assert summary["falcon_api_key_configured"] is True
    assert summary["telegram_token_configured"] is True
    assert "secret" not in str(summary)


def test_health_payload_truth_when_runtime_not_ready() -> None:
    state = RuntimeState()
    assert state.ready is False
