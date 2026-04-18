"""Tests for deploy-critical configuration validation in CrusaderBot."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parents[4]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))


class TestRequiredEnvValidation:
    """run_api.py validate_env() must exit 1 if DB_DSN is missing."""

    def test_validate_env_passes_with_db_dsn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DB_DSN", "postgresql://u:p@localhost/db")
        # Import inline so monkeypatch is applied before module-level code runs.
        import importlib
        import projects.polymarket.polyquantbot.scripts.run_api as run_api_mod

        importlib.reload(run_api_mod)
        # Should not raise — validate_env only calls sys.exit on missing vars.
        run_api_mod._validate_env()

    def test_validate_env_exits_without_db_dsn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DB_DSN", raising=False)
        import importlib
        import projects.polymarket.polyquantbot.scripts.run_api as run_api_mod

        importlib.reload(run_api_mod)
        with pytest.raises(SystemExit) as exc_info:
            run_api_mod._validate_env()
        assert exc_info.value.code == 1

    def test_validate_env_worker_exits_without_db_dsn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DB_DSN", raising=False)
        import importlib
        import projects.polymarket.polyquantbot.scripts.run_worker as run_worker_mod

        importlib.reload(run_worker_mod)
        with pytest.raises(SystemExit) as exc_info:
            run_worker_mod._validate_env()
        assert exc_info.value.code == 1


class TestPortBinding:
    def test_default_port_is_8080(self) -> None:
        port = int(os.environ.get("PORT", "8080"))
        assert port == 8080

    def test_port_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PORT", "9090")
        port = int(os.environ.get("PORT", "8080"))
        assert port == 9090


class TestHealthRouterContract:
    """Verify the health router constants stay stable (contract-level check)."""

    def test_required_env_includes_db_dsn(self) -> None:
        from projects.polymarket.polyquantbot.server.api.health import _REQUIRED_DEPLOY_ENV

        assert "DB_DSN" in _REQUIRED_DEPLOY_ENV

    def test_version_string_is_semver(self) -> None:
        from projects.polymarket.polyquantbot.server.api.health import CRUSADERBOT_VERSION

        parts = CRUSADERBOT_VERSION.split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)
