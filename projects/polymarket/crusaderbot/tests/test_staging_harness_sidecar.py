"""Anti-regression: ``_staging_settings`` honours the same CLOB-backend
precedence as the production factory (sidecar > v2 > pysdk > legacy).

If the harness builds the wrong backend, the staging proof would validate
something other than the production code path — exactly the WARP-74 §1.7
class of bug. These tests pin the env→settings mapping.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from unittest.mock import patch

import pytest


@dataclass
class _StubSettings:
    """Minimal Settings clone for the harness override path. Carries every
    attribute ``_staging_settings`` updates via ``model_copy``; mimics
    pydantic's API surface narrowly enough that the harness path doesn't
    care it's not a real BaseSettings."""
    USE_REAL_CLOB: bool = False
    USE_RUST_SIDECAR: bool = False
    USE_CLOB_V2: bool = False
    USE_PYSDK_CLOB: bool = True
    RUST_SIDECAR_PATH: str = "/usr/local/bin/order-sidecar"
    POLYMARKET_PRIVATE_KEY: str = ""
    POLYMARKET_FUNDER_ADDRESS: str = ""
    POLYMARKET_SIGNATURE_TYPE: int = 0
    POLYMARKET_API_KEY: str = ""
    POLYMARKET_API_SECRET: str = ""
    POLYMARKET_API_PASSPHRASE: str = ""
    POLYMARKET_BUILDER_CODE: str = ""
    POLYMARKET_BUILDER_ADDRESS: str = ""
    extras: dict = field(default_factory=dict)

    def model_copy(self, *, update: dict) -> "_StubSettings":
        merged = {k: getattr(self, k) for k in self.__dataclass_fields__
                  if k != "extras"}
        merged.update({k: v for k, v in update.items() if k in merged})
        # Anything not on the dataclass goes in extras so the test can
        # inspect it without forcing us to enumerate the whole Settings.
        extras = {k: v for k, v in update.items() if k not in merged}
        out = _StubSettings(**merged)
        out.extras = extras
        return out


@pytest.fixture(autouse=True)
def _staging_env(monkeypatch):
    """Provide every env var ``_staging_settings`` reads + stub the real
    Settings (loading it requires DATABASE_URL etc. which don't exist in
    CI)."""
    monkeypatch.setenv("STAGING_WALLET_KEY", "0x" + "11" * 32)
    monkeypatch.setenv("STAGING_FUNDER_ADDRESS", "0x" + "cd" * 20)
    monkeypatch.setenv("STAGING_SIGNATURE_TYPE", "3")
    for key in ("USE_RUST_SIDECAR", "USE_CLOB_V2", "USE_PYSDK_CLOB",
                "RUST_SIDECAR_PATH"):
        monkeypatch.delenv(key, raising=False)


@contextmanager
def _patched_harness():
    from projects.polymarket.crusaderbot import config as config_mod
    from projects.polymarket.crusaderbot.tests.staging import (
        test_live_reconcile_staging as harness,
    )
    # _staging_settings re-imports get_settings inside the function, so the
    # patch has to land on the source module (config), not the harness one.
    with patch.object(config_mod, "get_settings", return_value=_StubSettings()), \
         patch.object(harness, "_WALLET", os.environ["STAGING_WALLET_KEY"]):
        yield harness


def _settings():
    with _patched_harness() as harness:
        return harness._staging_settings()


def test_sidecar_toggle_threads_through(monkeypatch):
    """USE_RUST_SIDECAR=1 lands on settings.USE_RUST_SIDECAR — the rest
    (factory precedence over v2/pysdk) is covered by test_rust_sidecar's
    test_factory_selects_sidecar_with_highest_precedence."""
    monkeypatch.setenv("USE_RUST_SIDECAR", "1")
    monkeypatch.setenv("USE_CLOB_V2", "1")
    monkeypatch.setenv("USE_PYSDK_CLOB", "1")
    s = _settings()
    assert s.USE_RUST_SIDECAR is True
    assert s.USE_CLOB_V2 is True
    assert s.USE_PYSDK_CLOB is True


def test_sidecar_toggle_default_off(monkeypatch):
    """Unset USE_RUST_SIDECAR keeps the harness on the prior pysdk default
    so existing proof runs are byte-unchanged."""
    s = _settings()
    assert s.USE_RUST_SIDECAR is False
    assert s.USE_PYSDK_CLOB is True  # legacy default preserved


def test_sidecar_truthy_aliases_all_honoured(monkeypatch):
    for val in ("1", "true", "yes", "on", "TRUE", "On"):
        monkeypatch.setenv("USE_RUST_SIDECAR", val)
        assert _settings().USE_RUST_SIDECAR is True, val


def test_sidecar_falsey_aliases_all_honoured(monkeypatch):
    for val in ("0", "false", "no", "off", ""):
        monkeypatch.setenv("USE_RUST_SIDECAR", val)
        assert _settings().USE_RUST_SIDECAR is False, val


def test_rust_sidecar_path_override(monkeypatch, tmp_path):
    """An operator override of RUST_SIDECAR_PATH (local dev / non-default
    container layout) is threaded into Settings; absence keeps the
    Settings-class default."""
    override = str(tmp_path / "order-sidecar")
    monkeypatch.setenv("RUST_SIDECAR_PATH", override)
    assert _settings().RUST_SIDECAR_PATH == override

    monkeypatch.delenv("RUST_SIDECAR_PATH")
    # Default carried by the stub mirrors the Settings-class default — the
    # harness path does NOT touch RUST_SIDECAR_PATH when the env is unset,
    # so the inherited Settings default flows through unchanged.
    assert _settings().RUST_SIDECAR_PATH == "/usr/local/bin/order-sidecar"
