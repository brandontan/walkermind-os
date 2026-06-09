"""Runtime-config overlay (domain/ops/runtime_config.py).

Hermetic: a fake asyncpg pool drives the system_settings reads/writes. Covers the
override precedence, fail-safe fallbacks, whitelist isolation, validation, and the
write→invalidate→reread cycle.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from projects.polymarket.crusaderbot.domain.ops import runtime_config as rc


def _run(coro):
    return asyncio.run(coro)


class _FakeConn:
    def __init__(self, store: dict[str, str]) -> None:
        self._store = store

    async def fetch(self, query: str, *args: Any) -> list[dict[str, str]]:
        # Mimic: SELECT key, value FROM system_settings WHERE key LIKE 'cfg:%'
        return [{"key": k, "value": v} for k, v in self._store.items()]

    async def execute(self, query: str, *args: Any) -> None:
        if query.strip().startswith("INSERT"):
            key, value = args[0], args[1]
            self._store[str(key)] = str(value)
        elif query.strip().startswith("DELETE"):
            self._store.pop(str(args[0]), None)

    async def __aenter__(self) -> "_FakeConn":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False


class _FakePool:
    def __init__(self, store: dict[str, str]) -> None:
        self._conn = _FakeConn(store)

    def acquire(self) -> _FakeConn:
        return self._conn


class _BoomPool:
    def acquire(self) -> Any:
        raise RuntimeError("db down")


def _wire(monkeypatch: pytest.MonkeyPatch, store: dict[str, str]) -> dict[str, str]:
    monkeypatch.setattr(rc, "get_pool", lambda: _FakePool(store))
    rc.invalidate_cache()
    return store


class _Settings:
    WEATHER_STRATEGY_ENABLED = False
    COMPLETE_SET_ARB_ENABLED = False
    SCAN_SNAPSHOT_ENABLED = False


# --- resolve_bool -------------------------------------------------------------

def test_resolve_bool_uses_env_default_when_no_override(monkeypatch):
    _wire(monkeypatch, {})
    assert _run(rc.resolve_bool("WEATHER_STRATEGY_ENABLED", False)) is False
    assert _run(rc.resolve_bool("WEATHER_STRATEGY_ENABLED", True)) is True


def test_resolve_bool_db_override_wins(monkeypatch):
    _wire(monkeypatch, {"cfg:WEATHER_STRATEGY_ENABLED": "true"})
    # env default OFF, DB override ON -> ON
    assert _run(rc.resolve_bool("WEATHER_STRATEGY_ENABLED", False)) is True


def test_resolve_bool_db_override_off_beats_env_on(monkeypatch):
    _wire(monkeypatch, {"cfg:COMPLETE_SET_ARB_ENABLED": "false"})
    assert _run(rc.resolve_bool("COMPLETE_SET_ARB_ENABLED", True)) is False


def test_resolve_bool_invalid_override_falls_back(monkeypatch):
    _wire(monkeypatch, {"cfg:WEATHER_STRATEGY_ENABLED": "maybe"})
    assert _run(rc.resolve_bool("WEATHER_STRATEGY_ENABLED", False)) is False


def test_resolve_bool_non_whitelisted_returns_env(monkeypatch):
    _wire(monkeypatch, {"cfg:SECRET_KNOB": "true"})
    assert _run(rc.resolve_bool("SECRET_KNOB", False)) is False


def test_resolve_bool_db_error_fails_safe_to_env(monkeypatch):
    monkeypatch.setattr(rc, "get_pool", lambda: _BoomPool())
    rc.invalidate_cache()
    # DB unreachable -> static env default (OFF for a strategy flag)
    assert _run(rc.resolve_bool("WEATHER_STRATEGY_ENABLED", False)) is False


# --- set_override / clear_override / validation -------------------------------

def test_set_override_persists_and_is_read_back(monkeypatch):
    store = _wire(monkeypatch, {})
    _run(rc.set_override("WEATHER_STRATEGY_ENABLED", True))
    assert store["cfg:WEATHER_STRATEGY_ENABLED"] == "true"
    # cache invalidated on write -> reread reflects it
    assert _run(rc.resolve_bool("WEATHER_STRATEGY_ENABLED", False)) is True


def test_set_override_unknown_key_raises_keyerror(monkeypatch):
    _wire(monkeypatch, {})
    with pytest.raises(KeyError):
        _run(rc.set_override("ENABLE_LIVE_TRADING", True))  # guard, not whitelisted


def test_set_override_bad_bool_raises_valueerror(monkeypatch):
    _wire(monkeypatch, {})
    with pytest.raises(ValueError):
        _run(rc.set_override("WEATHER_STRATEGY_ENABLED", "banana"))


def test_clear_override_reverts_to_env(monkeypatch):
    store = _wire(monkeypatch, {"cfg:COMPLETE_SET_ARB_ENABLED": "true"})
    assert _run(rc.resolve_bool("COMPLETE_SET_ARB_ENABLED", False)) is True
    _run(rc.clear_override("COMPLETE_SET_ARB_ENABLED"))
    assert "cfg:COMPLETE_SET_ARB_ENABLED" not in store
    assert _run(rc.resolve_bool("COMPLETE_SET_ARB_ENABLED", False)) is False


# --- list_effective -----------------------------------------------------------

def test_list_effective_reports_default_and_override(monkeypatch):
    _wire(monkeypatch, {"cfg:WEATHER_STRATEGY_ENABLED": "true"})
    rows = _run(rc.list_effective(_Settings()))
    by_key = {r["key"]: r for r in rows}
    wx = by_key["WEATHER_STRATEGY_ENABLED"]
    assert wx["overridden"] is True
    assert wx["effective"] is True
    assert wx["env_default"] is False
    cs = by_key["COMPLETE_SET_ARB_ENABLED"]
    assert cs["overridden"] is False
    assert cs["effective"] is False


# --- SCAN_SNAPSHOT_ENABLED (Phase-2c-2 capture toggle) ------------------------

def test_scan_snapshot_is_whitelisted_bool():
    spec = rc.RUNTIME_SETTINGS.get("SCAN_SNAPSHOT_ENABLED")
    assert spec is not None, "SCAN_SNAPSHOT_ENABLED must be runtime-editable"
    assert spec.kind == "bool"


def test_scan_snapshot_dormant_by_default(monkeypatch):
    # No override row -> falls back to the static env/Fly default (OFF). This is
    # the "DEFAULT false" guarantee: absence of an override == capture disabled.
    _wire(monkeypatch, {})
    assert _run(rc.resolve_bool("SCAN_SNAPSHOT_ENABLED", False)) is False


def test_scan_snapshot_db_override_enables_without_redeploy(monkeypatch):
    # Operator flips it ON in the DB overlay -> capture armed, no redeploy.
    _wire(monkeypatch, {"cfg:SCAN_SNAPSHOT_ENABLED": "true"})
    assert _run(rc.resolve_bool("SCAN_SNAPSHOT_ENABLED", False)) is True


def test_scan_snapshot_override_off_beats_env_on(monkeypatch):
    # Kill-switch precedence: DB OFF wins even if the env default were ON.
    _wire(monkeypatch, {"cfg:SCAN_SNAPSHOT_ENABLED": "false"})
    assert _run(rc.resolve_bool("SCAN_SNAPSHOT_ENABLED", True)) is False


def test_scan_snapshot_appears_in_list_effective(monkeypatch):
    _wire(monkeypatch, {"cfg:SCAN_SNAPSHOT_ENABLED": "true"})
    rows = _run(rc.list_effective(_Settings()))
    by_key = {r["key"]: r for r in rows}
    snap = by_key["SCAN_SNAPSHOT_ENABLED"]
    assert snap["overridden"] is True
    assert snap["effective"] is True
    assert snap["env_default"] is False


def test_whitelist_excludes_secrets_and_guards():
    # Hard invariant: no secret / LIVE guard is ever runtime-editable.
    forbidden = {
        "ENABLE_LIVE_TRADING", "EXECUTION_PATH_VALIDATED", "CAPITAL_MODE_CONFIRMED",
        "DATABASE_URL", "WALLET_HD_SEED", "WALLET_ENCRYPTION_KEY",
        "TELEGRAM_BOT_TOKEN", "POLYMARKET_API_KEY",
    }
    assert forbidden.isdisjoint(rc.RUNTIME_SETTINGS.keys())


# --- float spec (forward-looking; bounds enforcement) -------------------------

def test_resolve_float_clamps_out_of_bounds_to_default(monkeypatch):
    # Inject a temporary float spec to exercise bounds without shipping a knob.
    spec = rc.SettingSpec("X_TEST_FLOAT", "float", "t", "t", min_value=0.0, max_value=0.5)
    monkeypatch.setitem(rc.RUNTIME_SETTINGS, "X_TEST_FLOAT", spec)
    _wire(monkeypatch, {"cfg:X_TEST_FLOAT": "0.9"})  # above max -> default
    assert _run(rc.resolve_float("X_TEST_FLOAT", 0.01)) == 0.01
    _wire(monkeypatch, {"cfg:X_TEST_FLOAT": "0.25"})  # in-bounds -> override
    assert _run(rc.resolve_float("X_TEST_FLOAT", 0.01)) == 0.25


def test_set_override_float_rejects_out_of_bounds(monkeypatch):
    spec = rc.SettingSpec("X_TEST_FLOAT", "float", "t", "t", min_value=0.0, max_value=0.5)
    monkeypatch.setitem(rc.RUNTIME_SETTINGS, "X_TEST_FLOAT", spec)
    _wire(monkeypatch, {})
    with pytest.raises(ValueError):
        _run(rc.set_override("X_TEST_FLOAT", 1.5))
    with pytest.raises(ValueError):
        _run(rc.set_override("X_TEST_FLOAT", float("nan")))
