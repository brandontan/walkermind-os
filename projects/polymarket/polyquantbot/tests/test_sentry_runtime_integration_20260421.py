from __future__ import annotations

import sys
import types

import pytest

pytest.importorskip("uvicorn", reason="Sentry runtime integration tests require API runtime dependencies.")

from projects.polymarket.polyquantbot.server.core import sentry_runtime
from projects.polymarket.polyquantbot.server.main import create_app


def test_create_app_boots_when_sentry_dsn_is_unset(monkeypatch) -> None:
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    sentry_runtime._SENTRY_INITIALIZED = False

    app = create_app()

    assert app is not None
    assert sentry_runtime._SENTRY_INITIALIZED is False


def test_initialize_sentry_uses_env_dsn_without_exposing_value(monkeypatch) -> None:
    calls: list[dict] = []

    class DummyScope:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def set_tag(self, _key: str, _value: str) -> None:
            return None

    def fake_init(**kwargs) -> None:
        calls.append(kwargs)

    sentry_sdk_module = types.ModuleType("sentry_sdk")
    sentry_sdk_module.init = fake_init
    sentry_sdk_module.push_scope = lambda: DummyScope()
    sentry_sdk_module.capture_exception = lambda _exc: None
    fastapi_module = types.ModuleType("sentry_sdk.integrations.fastapi")
    fastapi_module.FastApiIntegration = lambda: "fastapi_integration"

    monkeypatch.setitem(sys.modules, "sentry_sdk", sentry_sdk_module)
    monkeypatch.setitem(sys.modules, "sentry_sdk.integrations.fastapi", fastapi_module)
    monkeypatch.setenv("SENTRY_DSN", "https://redacted@sentry.invalid/123")
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "test")
    monkeypatch.setenv("SENTRY_RELEASE", "unit-test")
    monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "0.0")
    sentry_runtime._SENTRY_INITIALIZED = False

    initialized = sentry_runtime.initialize_sentry()

    assert initialized is True
    assert sentry_runtime._SENTRY_INITIALIZED is True
    assert len(calls) == 1
    assert calls[0]["dsn"] == "https://redacted@sentry.invalid/123"
    assert calls[0]["environment"] == "test"
    assert calls[0]["release"] == "unit-test"
    assert calls[0]["send_default_pii"] is False
