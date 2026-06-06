"""WARP-78 cutover orchestrator kill-switch (Track B).

Hermetic — a fake asyncpg pool drives the system_settings overlay (mirrors
tests/test_runtime_config.py). Covers: default OFF → orchestrator allowed;
override ON → router fallback; persistence across reads; env/Fly backstop;
and the (preset, rule) gate (candle_auto + auto only).
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from projects.polymarket.crusaderbot import config
from projects.polymarket.crusaderbot.domain.ops import runtime_config as rc
from projects.polymarket.crusaderbot.domain.strategy import ev_comparator as ev


def _run(coro):
    return asyncio.run(coro)


class _FakeConn:
    def __init__(self, store: dict[str, str]) -> None:
        self._store = store

    async def fetch(self, query: str, *args: Any) -> list[dict[str, str]]:
        return [{"key": k, "value": v} for k, v in self._store.items()]

    async def execute(self, query: str, *args: Any) -> None:
        if query.strip().startswith("INSERT"):
            self._store[str(args[0])] = str(args[1])
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


class _Stub:
    def __init__(self, kill: bool = False) -> None:
        self.ORCHESTRATOR_KILL_SWITCH = kill


def _wire(monkeypatch: pytest.MonkeyPatch, store: dict[str, str], *, env_kill: bool = False) -> dict[str, str]:
    monkeypatch.setattr(rc, "get_pool", lambda: _FakePool(store))
    monkeypatch.setattr(config, "get_settings", lambda: _Stub(env_kill))
    # Fresh lock per test: the module-level _cache.lock is created once at import,
    # but each test drives a new event loop via asyncio.run — rebinding it here
    # avoids a cross-loop "Lock bound to a different event loop" RuntimeError.
    monkeypatch.setattr(rc._cache, "_lock", asyncio.Lock())
    rc.invalidate_cache()
    return store


def test_whitelisted_as_bool() -> None:
    spec = rc.RUNTIME_SETTINGS.get("ORCHESTRATOR_KILL_SWITCH")
    assert spec is not None and spec.kind == "bool"


def test_default_off_orchestrator_allowed(monkeypatch) -> None:
    _wire(monkeypatch, {})
    assert _run(ev.orchestrator_kill_switch_active()) is False
    assert _run(ev.orchestrator_routes("candle_auto", "auto")) is True


def test_kill_switch_on_falls_back_to_router(monkeypatch) -> None:
    _wire(monkeypatch, {"cfg:ORCHESTRATOR_KILL_SWITCH": "true"})
    assert _run(ev.orchestrator_kill_switch_active()) is True
    assert _run(ev.orchestrator_routes("candle_auto", "auto")) is False


def test_override_off_keeps_orchestrator(monkeypatch) -> None:
    _wire(monkeypatch, {"cfg:ORCHESTRATOR_KILL_SWITCH": "false"})
    assert _run(ev.orchestrator_routes("candle_auto", "auto")) is True


def test_env_backstop_engages_without_db_override(monkeypatch) -> None:
    # No DB row, but the Fly/env default is true → kill-switch engaged.
    _wire(monkeypatch, {}, env_kill=True)
    assert _run(ev.orchestrator_kill_switch_active()) is True
    assert _run(ev.orchestrator_routes("candle_auto", "auto")) is False


def test_db_override_off_beats_env_on(monkeypatch) -> None:
    # Operator explicitly cleared the kill-switch in the DB; env backstop is on.
    _wire(monkeypatch, {"cfg:ORCHESTRATOR_KILL_SWITCH": "false"}, env_kill=True)
    assert _run(ev.orchestrator_kill_switch_active()) is False


def test_gate_only_candle_auto_plus_auto(monkeypatch) -> None:
    _wire(monkeypatch, {})  # kill-switch OFF → orchestrator allowed in principle
    # pinned rule on candle_auto → router (orchestrator does not route)
    assert _run(ev.orchestrator_routes("candle_auto", "close_sweep")) is False
    # other presets never route via the orchestrator
    assert _run(ev.orchestrator_routes("weather_monitor", "auto")) is False
    assert _run(ev.orchestrator_routes("playbook", "auto")) is False
    assert _run(ev.orchestrator_routes(None, None)) is False


def test_failsafe_returns_env_default_on_read_error(monkeypatch) -> None:
    # If resolve_bool blows up, the env/Fly backstop must still win — a hardcoded
    # False would silently re-enable the orchestrator during a DB outage.
    async def _boom(*_a, **_k):
        raise RuntimeError("overlay read failed")

    monkeypatch.setattr(config, "get_settings", lambda: _Stub(True))  # Fly backstop ON
    monkeypatch.setattr(rc, "resolve_bool", _boom)
    assert _run(ev.orchestrator_kill_switch_active()) is True

    monkeypatch.setattr(config, "get_settings", lambda: _Stub(False))
    assert _run(ev.orchestrator_kill_switch_active()) is False


def test_persists_across_reads_via_cache(monkeypatch) -> None:
    _wire(monkeypatch, {"cfg:ORCHESTRATOR_KILL_SWITCH": "true"})
    assert _run(ev.orchestrator_kill_switch_active()) is True
    assert _run(ev.orchestrator_kill_switch_active()) is True


def test_set_override_then_read(monkeypatch) -> None:
    _wire(monkeypatch, {})
    _run(rc.set_override("ORCHESTRATOR_KILL_SWITCH", True))
    assert _run(ev.orchestrator_routes("candle_auto", "auto")) is False
    _run(rc.clear_override("ORCHESTRATOR_KILL_SWITCH"))
    assert _run(ev.orchestrator_routes("candle_auto", "auto")) is True
