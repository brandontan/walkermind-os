"""Hermetic tests for the WARP-92 global live-trading gate.

No real DB. ``asyncpg.Pool``/``Connection`` are replaced with async-context
doubles. Mirrors test_kill_switch.py. Covers:

  * truthy/falsey parse of system_settings value
  * missing key → False (fail-safe to paper)
  * DB error → False (fail-safe to paper), not cached
  * cache hit within TTL (one DB read)
  * invalidate_cache() forces a re-read
  * set_global_live() upserts and invalidates the cache
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest

from projects.polymarket.crusaderbot.domain.ops import global_live_gate as glg


class FakeConn:
    def __init__(self, *, settings: dict[str, str] | None = None,
                 raise_on_fetchrow: bool = False) -> None:
        self.settings = dict(settings or {})
        self.raise_on_fetchrow = raise_on_fetchrow
        self.fetchrow_calls: list[tuple[str, tuple]] = []
        self.execute_calls: list[tuple[str, tuple]] = []

    async def fetchrow(self, query: str, *args: Any):
        if self.raise_on_fetchrow:
            raise RuntimeError("DB blip")
        self.fetchrow_calls.append((query, args))
        if "system_settings" in query and "key=$1" in query:
            key = args[0]
            if key in self.settings:
                return {"value": self.settings[key]}
            return None
        return None

    async def execute(self, query: str, *args: Any):
        self.execute_calls.append((query, args))
        if "INSERT INTO system_settings" in query:
            key, val = args
            self.settings[key] = val
        return "INSERT 0 1"


class FakeAcquire:
    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn

    async def __aenter__(self) -> FakeConn:
        return self.conn

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class FakePool:
    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn

    def acquire(self) -> FakeAcquire:
        return FakeAcquire(self.conn)


@pytest.fixture(autouse=True)
def _reset_cache():
    glg.invalidate_cache()
    yield
    glg.invalidate_cache()


@pytest.mark.parametrize("raw,expected", [
    ("true", True), ("TRUE", True), ("1", True), ("yes", True),
    ("on", True), (" On ", True),
    ("false", False), ("0", False), ("no", False), ("", False),
    ("garbage", False),
])
def test_parses_truthy_and_falsey(raw, expected):
    conn = FakeConn(settings={"global_live_trading_enabled": raw})
    with patch.object(glg, "get_pool", return_value=FakePool(conn)):
        assert asyncio.run(glg.is_global_live_enabled()) is expected


def test_missing_key_is_false():
    conn = FakeConn(settings={})
    with patch.object(glg, "get_pool", return_value=FakePool(conn)):
        assert asyncio.run(glg.is_global_live_enabled()) is False


def test_db_error_fails_safe_to_false_not_cached():
    conn = FakeConn(raise_on_fetchrow=True)
    with patch.object(glg, "get_pool", return_value=FakePool(conn)):
        # Error → False (NOT True like kill switch — live must default OFF).
        assert asyncio.run(glg.is_global_live_enabled()) is False
        # Failure is not cached: the next call re-attempts the read.
        ok_conn = FakeConn(settings={"global_live_trading_enabled": "true"})
        with patch.object(glg, "get_pool", return_value=FakePool(ok_conn)):
            assert asyncio.run(glg.is_global_live_enabled()) is True


def test_cache_within_ttl_single_db_read():
    conn = FakeConn(settings={"global_live_trading_enabled": "true"})
    with patch.object(glg, "get_pool", return_value=FakePool(conn)):
        a = asyncio.run(glg.is_global_live_enabled())
        b = asyncio.run(glg.is_global_live_enabled())
        c = asyncio.run(glg.is_global_live_enabled())
    assert (a, b, c) == (True, True, True)
    assert len(conn.fetchrow_calls) == 1


def test_invalidate_cache_forces_reread():
    conn = FakeConn(settings={"global_live_trading_enabled": "false"})
    with patch.object(glg, "get_pool", return_value=FakePool(conn)):
        assert asyncio.run(glg.is_global_live_enabled()) is False
        glg.invalidate_cache()
        conn.settings["global_live_trading_enabled"] = "true"
        before = len(conn.fetchrow_calls)
        assert asyncio.run(glg.is_global_live_enabled()) is True
        assert len(conn.fetchrow_calls) > before


def test_set_global_live_upserts_and_invalidates():
    conn = FakeConn(settings={"global_live_trading_enabled": "false"})
    with patch.object(glg, "get_pool", return_value=FakePool(conn)):
        # Warm the cache with the current (false) value.
        assert asyncio.run(glg.is_global_live_enabled()) is False
        out = asyncio.run(glg.set_global_live(True))
        assert out is True
        assert conn.settings["global_live_trading_enabled"] == "true"
        # Cache was invalidated by the write → next read sees the new value.
        before = len(conn.fetchrow_calls)
        assert asyncio.run(glg.is_global_live_enabled()) is True
        assert len(conn.fetchrow_calls) > before


def test_shared_conn_bypasses_cache_both_ways():
    """WARP-92 review fix: a shared transaction ``conn`` bypasses the in-process
    cache entirely — it reads directly every call (no caching of tx reads) and
    never pollutes the global cache for the pooled path. Strict tx isolation."""
    glg.invalidate_cache()
    tx = FakeConn(settings={"global_live_trading_enabled": "true"})
    # Two consecutive conn-shared reads each hit the conn (tx reads are not cached).
    assert asyncio.run(glg.is_global_live_enabled(tx)) is True
    assert asyncio.run(glg.is_global_live_enabled(tx)) is True
    assert len(tx.fetchrow_calls) == 2
    # The tx read did NOT populate the module cache: a subsequent pooled read
    # still queries the DB and returns its own value (here 'false').
    pooled = FakeConn(settings={"global_live_trading_enabled": "false"})
    with patch.object(glg, "get_pool", return_value=FakePool(pooled)):
        assert asyncio.run(glg.is_global_live_enabled()) is False
        assert len(pooled.fetchrow_calls) == 1
    glg.invalidate_cache()
