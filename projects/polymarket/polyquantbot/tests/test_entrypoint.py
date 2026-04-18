"""Tests for CrusaderBot entrypoint resolution and import sanity."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parents[4]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))


class TestServerModuleImport:
    def test_server_main_importable(self) -> None:
        mod = importlib.import_module("projects.polymarket.polyquantbot.server.main")
        assert mod is not None

    def test_server_main_has_app(self) -> None:
        from projects.polymarket.polyquantbot.server.main import app

        assert app is not None

    def test_server_main_app_is_fastapi(self) -> None:
        from fastapi import FastAPI
        from projects.polymarket.polyquantbot.server.main import app

        assert isinstance(app, FastAPI)

    def test_health_router_importable(self) -> None:
        from projects.polymarket.polyquantbot.server.api.health import router

        assert router is not None


class TestClientModuleImport:
    def test_client_telegram_bot_importable(self) -> None:
        mod = importlib.import_module(
            "projects.polymarket.polyquantbot.client.telegram.bot"
        )
        assert mod is not None

    def test_client_telegram_bot_has_start_fn(self) -> None:
        from projects.polymarket.polyquantbot.client.telegram.bot import (
            start_telegram_client,
        )

        assert callable(start_telegram_client)

    def test_client_telegram_bot_has_stop_fn(self) -> None:
        from projects.polymarket.polyquantbot.client.telegram.bot import (
            stop_telegram_client,
        )

        assert callable(stop_telegram_client)


class TestScriptsImport:
    def test_run_api_importable(self) -> None:
        mod = importlib.import_module(
            "projects.polymarket.polyquantbot.scripts.run_api"
        )
        assert hasattr(mod, "_validate_env")

    def test_run_bot_importable(self) -> None:
        mod = importlib.import_module(
            "projects.polymarket.polyquantbot.scripts.run_bot"
        )
        assert mod is not None

    def test_run_worker_importable(self) -> None:
        mod = importlib.import_module(
            "projects.polymarket.polyquantbot.scripts.run_worker"
        )
        assert hasattr(mod, "_validate_env")


class TestStructuralLayout:
    """Verify the required blueprint directories exist."""

    _base = Path(__file__).resolve().parents[1]

    @pytest.mark.parametrize(
        "rel_path",
        [
            "server/__init__.py",
            "server/main.py",
            "server/api/__init__.py",
            "server/api/health.py",
            "server/services/__init__.py",
            "server/utils/__init__.py",
            "client/__init__.py",
            "client/telegram/__init__.py",
            "client/telegram/bot.py",
            "scripts/run_api.py",
            "scripts/run_bot.py",
            "scripts/run_worker.py",
            "configs/env.example",
            "fly.toml",
            "Dockerfile",
        ],
    )
    def test_file_exists(self, rel_path: str) -> None:
        assert (self._base / rel_path).exists(), f"Missing: {rel_path}"
