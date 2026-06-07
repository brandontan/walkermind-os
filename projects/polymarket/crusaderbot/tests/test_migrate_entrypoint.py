"""WARP-80 follow-up — release migration entrypoint retry behaviour.

Hermetic: no DB. Monkeypatches run_migrations to prove the connect-phase retry
rides out a transient failure and re-raises (fail-loud) once attempts exhaust.
Backoff delays are zeroed so the test does not actually sleep.
"""
from __future__ import annotations

import asyncio

import pytest

from projects.polymarket.crusaderbot.scripts import migrate


def _run(coro):
    return asyncio.run(coro)


async def _noop_close():
    return None


def test_retry_succeeds_after_transient_failures(monkeypatch):
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise OSError("connection refused")
        return ["001_x.sql"]

    monkeypatch.setattr(migrate, "run_migrations", flaky)
    monkeypatch.setattr(migrate, "close_pool", _noop_close)
    monkeypatch.setattr(migrate, "_BASE_DELAY_SEC", 0.0)
    monkeypatch.setattr(migrate, "_MAX_DELAY_SEC", 0.0)

    out = _run(migrate._run_with_retry())
    assert out == ["001_x.sql"]
    assert calls["n"] == 3            # failed twice, succeeded on the third


def test_retry_exhausts_then_reraises(monkeypatch):
    attempts = {"n": 0}

    async def always_fail():
        attempts["n"] += 1
        raise OSError("db unreachable")

    monkeypatch.setattr(migrate, "run_migrations", always_fail)
    monkeypatch.setattr(migrate, "close_pool", _noop_close)
    monkeypatch.setattr(migrate, "_BASE_DELAY_SEC", 0.0)
    monkeypatch.setattr(migrate, "_MAX_DELAY_SEC", 0.0)

    with pytest.raises(OSError):
        _run(migrate._run_with_retry())
    assert attempts["n"] == migrate._MAX_ATTEMPTS   # tried the full budget


def test_main_returns_1_on_failure(monkeypatch):
    async def always_fail():
        raise RuntimeError("boom")

    monkeypatch.setattr(migrate, "run_migrations", always_fail)
    monkeypatch.setattr(migrate, "close_pool", _noop_close)
    monkeypatch.setattr(migrate, "_BASE_DELAY_SEC", 0.0)
    monkeypatch.setattr(migrate, "_MAX_DELAY_SEC", 0.0)
    assert _run(migrate._main()) == 1


def test_main_returns_0_on_success(monkeypatch):
    async def ok():
        return []

    monkeypatch.setattr(migrate, "run_migrations", ok)
    monkeypatch.setattr(migrate, "close_pool", _noop_close)
    assert _run(migrate._main()) == 0
