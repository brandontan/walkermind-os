"""Hermetic tests for the R12f kill-switch domain module.

No real DB. ``asyncpg.Pool`` and ``asyncpg.Connection`` are replaced
with async-context-manager doubles so the test suite exercises:

    * is_active() returns DB value when cache is cold
    * is_active() returns cached value within TTL (no DB hit)
    * is_active() fails SAFE (returns True) when the DB read raises
    * set_active("pause") upserts true and writes one history row
    * set_active("resume") upserts false and clears lock_mode
    * set_active("lock") upserts true+true AND flips users.auto_trade_on
    * set_active() invalidates the cache so the next read re-fetches
    * record_history() rejects unknown actions
    * fetch_history() returns the rows asyncpg gave it as plain dicts
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest

from projects.polymarket.crusaderbot.domain.ops import kill_switch as ks


# ---------- Fake asyncpg machinery ------------------------------------------


class FakeConn:
    """asyncpg.Connection stand-in capturing every SQL call."""

    def __init__(self, *, settings: dict[str, str] | None = None,
                 lock_mode: bool = False,
                 raise_on_fetchrow: bool = False) -> None:
        self.settings = dict(settings or {})
        self.lock_mode = lock_mode
        self.raise_on_fetchrow = raise_on_fetchrow
        self.execute_calls: list[tuple[str, tuple]] = []
        self.fetchrow_calls: list[tuple[str, tuple]] = []
        self.fetchval_calls: list[tuple[str, tuple]] = []
        self.history_rows: list[tuple] = []
        self.users_disabled = 0

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

    async def fetchval(self, query: str, *args: Any):
        self.fetchval_calls.append((query, args))
        if "auto_trade_on=FALSE" in query and "auto_trade_on=TRUE" in query:
            return self.users_disabled
        return 0

    async def execute(self, query: str, *args: Any):
        self.execute_calls.append((query, args))
        if "INSERT INTO system_settings" in query:
            key, val = args
            self.settings[key] = val
        elif "INSERT INTO kill_switch_history" in query:
            self.history_rows.append(args)
        return "INSERT 0 1"

    async def fetch(self, query: str, *args: Any):
        # used by fetch_history
        return [
            {"action": "pause", "actor_id": 42, "reason": None,
             "ts": "2026-05-05T00:00:00+00:00"},
        ]

    def transaction(self):
        conn = self

        class _Txn:
            async def __aenter__(self_inner):
                return conn

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        return _Txn()


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
    ks.invalidate_cache()
    yield
    ks.invalidate_cache()


# ---------- is_active() -----------------------------------------------------


def test_is_active_returns_db_value_on_cold_cache():
    conn = FakeConn(settings={"kill_switch_active": "true"})
    with patch.object(ks, "get_pool", return_value=FakePool(conn)):
        result = asyncio.run(ks.is_active())
    assert result is True
    # Exactly one fetchrow against system_settings.
    assert len(conn.fetchrow_calls) == 1


def test_is_active_returns_false_when_setting_missing():
    conn = FakeConn(settings={})
    with patch.object(ks, "get_pool", return_value=FakePool(conn)):
        result = asyncio.run(ks.is_active())
    assert result is False


def test_is_active_uses_cache_within_ttl():
    conn = FakeConn(settings={"kill_switch_active": "false"})
    with patch.object(ks, "get_pool", return_value=FakePool(conn)):
        first = asyncio.run(ks.is_active())
        second = asyncio.run(ks.is_active())
        third = asyncio.run(ks.is_active())
    assert (first, second, third) == (False, False, False)
    # Only the first call should have hit the DB.
    assert len(conn.fetchrow_calls) == 1


def test_is_active_fails_safe_on_db_error():
    conn = FakeConn(raise_on_fetchrow=True)
    with patch.object(ks, "get_pool", return_value=FakePool(conn)):
        result = asyncio.run(ks.is_active())
    # Fail SAFE: when the DB read errors, the gate must assume ACTIVE so
    # no new trades route until the issue is resolved.
    assert result is True


def test_is_active_uses_provided_conn_without_pool():
    conn = FakeConn(settings={"kill_switch_active": "true"})
    # If is_active reaches into get_pool when a conn is supplied, this
    # patch will assert via NotImplementedError.
    with patch.object(ks, "get_pool",
                      side_effect=AssertionError("pool must not be used")):
        result = asyncio.run(ks.is_active(conn))
    assert result is True


# ---------- set_active() ----------------------------------------------------


def test_set_active_pause_upserts_and_writes_history():
    conn = FakeConn(settings={"kill_switch_active": "false"})
    with patch.object(ks, "get_pool", return_value=FakePool(conn)):
        result = asyncio.run(ks.set_active(action="pause", actor_id=42))
    assert result == {"active": True, "lock_mode": False, "users_disabled": 0}
    assert conn.settings["kill_switch_active"] == "true"
    # Exactly one history row written.
    assert len(conn.history_rows) == 1
    action, actor_id, _reason = conn.history_rows[0]
    assert action == "pause"
    assert actor_id == 42


def test_set_active_resume_clears_lock_mode():
    conn = FakeConn(settings={
        "kill_switch_active": "true",
        "kill_switch_lock_mode": "true",
    })
    with patch.object(ks, "get_pool", return_value=FakePool(conn)):
        result = asyncio.run(ks.set_active(action="resume", actor_id=7))
    assert result == {"active": False, "lock_mode": False, "users_disabled": 0}
    assert conn.settings["kill_switch_active"] == "false"
    assert conn.settings["kill_switch_lock_mode"] == "false"


def test_set_active_lock_disables_users():
    conn = FakeConn(settings={"kill_switch_active": "false"})
    conn.users_disabled = 5
    with patch.object(ks, "get_pool", return_value=FakePool(conn)):
        result = asyncio.run(ks.set_active(action="lock", actor_id=99))
    assert result == {"active": True, "lock_mode": True, "users_disabled": 5}
    assert conn.settings["kill_switch_active"] == "true"
    assert conn.settings["kill_switch_lock_mode"] == "true"
    # The auto_trade UPDATE must have run.
    matched = [
        q for q, _ in conn.fetchval_calls
        if "auto_trade_on=FALSE" in q and "auto_trade_on=TRUE" in q
    ]
    assert matched, "lock action must flip every user's auto_trade_on"


def test_set_active_rejects_invalid_action():
    with pytest.raises(ValueError):
        asyncio.run(ks.set_active(action="nuke", actor_id=1))


def test_set_active_invalidates_cache():
    conn = FakeConn(settings={"kill_switch_active": "false"})
    with patch.object(ks, "get_pool", return_value=FakePool(conn)):
        # Warm cache with FALSE.
        assert asyncio.run(ks.is_active()) is False
        assert len(conn.fetchrow_calls) == 1
        # Now flip to pause; the cache must be cleared so the next is_active
        # re-reads the DB.
        asyncio.run(ks.set_active(action="pause"))
        # Update simulated DB so the post-pause read returns the new value.
        conn.settings["kill_switch_active"] = "true"
        assert asyncio.run(ks.is_active()) is True
        assert len(conn.fetchrow_calls) == 2


# ---------- record_history --------------------------------------------------


def test_record_history_rejects_unknown_action():
    conn = FakeConn()
    with pytest.raises(ValueError):
        asyncio.run(ks.record_history(conn, action="explode", actor_id=1))


def test_record_history_writes_one_row():
    conn = FakeConn()
    asyncio.run(ks.record_history(
        conn, action="pause", actor_id=7, reason="incident",
    ))
    assert conn.history_rows == [("pause", 7, "incident")]


# ---------- fetch_history ---------------------------------------------------


def test_fetch_history_zero_limit_returns_empty():
    conn = FakeConn()
    with patch.object(ks, "get_pool", return_value=FakePool(conn)):
        out = asyncio.run(ks.fetch_history(0))
    assert out == []


def test_fetch_history_returns_dicts():
    conn = FakeConn()
    with patch.object(ks, "get_pool", return_value=FakePool(conn)):
        out = asyncio.run(ks.fetch_history(5))
    assert out == [{"action": "pause", "actor_id": 42, "reason": None,
                    "ts": "2026-05-05T00:00:00+00:00"}]
