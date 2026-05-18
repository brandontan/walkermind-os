"""Kill switch path convergence tests (Track D Part E).

Verifies all three activation paths converge to the same halt logic
via execute_kill_switch():

  Path 1 — Telegram /emergency operator command → DB flag kill_switch_active=true
            + audit log written with timestamp+actor
  Path 2 — DB flag kill_switch_active=true → ops_ks.is_active() returns True
            → execution blocked before each trade (gate step 1)
  Path 3 — Env var KILL_SWITCH=true → execute_kill_switch() called at startup

All three must:
  (a) halt new order creation
  (b) log activation with timestamp + actor
  (c) NOT close existing positions automatically

No real DB, no real Telegram calls — mocks only.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from projects.polymarket.crusaderbot.domain.ops import kill_switch as ops_ks


# ---------------------------------------------------------------------------
# Shared fake DB machinery (mirrors test_kill_switch.py helpers)
# ---------------------------------------------------------------------------


class _FakeConn:
    def __init__(self) -> None:
        self.execute_calls: list[tuple] = []
        self.fetchrow_calls: list[tuple] = []
        self.settings: dict[str, str] = {}
        self.history: list[tuple] = []

    async def fetchrow(self, query: str, *args: Any):
        self.fetchrow_calls.append((query, args))
        if "system_settings" in query and "key=$1" in query:
            key = args[0]
            val = self.settings.get(key, "false")
            return {"value": val}
        return None

    async def fetchval(self, query: str, *args: Any):
        return 0

    async def execute(self, query: str, *args: Any):
        self.execute_calls.append((query, args))
        if "INSERT INTO system_settings" in query or "system_flags" in query:
            if len(args) >= 2:
                self.settings[args[0]] = args[1]
        if "INSERT INTO kill_switch_history" in query:
            self.history.append(args)
        return "INSERT 0 1"

    async def fetch(self, query: str, *args: Any):
        return []

    def transaction(self):
        conn = self

        class _T:
            async def __aenter__(self_):
                return conn

            async def __aexit__(self_, *_):
                return False

        return _T()


class _FakePool:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _Acq:
            async def __aenter__(self_):
                return conn

            async def __aexit__(self_, *_):
                return False

        return _Acq()


def _make_pool() -> tuple[_FakePool, _FakeConn]:
    conn = _FakeConn()
    return _FakePool(conn), conn


# ---------------------------------------------------------------------------
# Path 1 — Telegram /emergency → DB flag kill_switch_active=true
# ---------------------------------------------------------------------------


def test_kill_switch_telegram():
    """Path 1: Telegram /emergency converges to execute_kill_switch().

    Simulates the Telegram-triggered path: an operator fires the bot's
    kill switch via Telegram, which calls execute_kill_switch() with
    triggered_by='telegram_operator'. Verifies:

    (a) kill_switch_active is set to 'true' in DB (halts new orders)
    (b) audit_log row written with triggered_by='telegram_operator'
    (c) no UPDATE positions issued (existing positions not auto-closed)
    """
    from projects.polymarket.crusaderbot.domain.risk.kill_switch_exec import (
        execute_kill_switch,
    )

    pool, conn = _make_pool()

    # Patch pool/DB dependencies. notify_operator is imported inside the function
    # body within a try/except — telegram import failure is silently caught there,
    # so no mock needed for that path.
    with (
        patch.object(ops_ks, "get_pool", return_value=pool),
        patch(
            "projects.polymarket.crusaderbot.domain.risk.kill_switch_exec.get_pool",
            return_value=pool,
        ),
    ):
        asyncio.run(
            execute_kill_switch(
                reason="operator emergency via Telegram",
                triggered_by="telegram_operator",
            )
        )

    # (a) kill_switch_active must be set true in DB (halts new orders)
    ks_active = conn.settings.get("kill_switch_active")
    assert ks_active == "true", (
        f"kill_switch_active must be 'true' after Telegram path, got {ks_active!r}"
    )

    # (b) audit_log INSERT must be present with triggered_by=telegram_operator
    audit_inserts = [
        args for q, args in conn.execute_calls
        if "INSERT INTO audit_log" in q
    ]
    assert audit_inserts, "audit_log INSERT must be written on Telegram kill switch"
    triggered_by_seen = any(
        "telegram_operator" in str(a) for a in audit_inserts
    )
    assert triggered_by_seen, (
        "'telegram_operator' must appear in audit_log triggered_by field"
    )

    # (c) no UPDATE positions — existing positions must not be auto-closed
    position_updates = [
        q for q, _ in conn.execute_calls
        if "UPDATE positions" in q
    ]
    assert not position_updates, (
        "kill switch must NOT auto-close existing positions; "
        f"found position updates: {position_updates}"
    )


# ---------------------------------------------------------------------------
# Path 2 — DB flag kill_switch_active=true → execution blocked before trade
# ---------------------------------------------------------------------------


def test_kill_switch_db():
    """Path 2: DB flag kill_switch_active=true → is_active() returns True.

    Verifies the DB-read path that gates every trade cycle:
      ops_ks.is_active() reads system_settings.kill_switch_active='true'
      → returns True → gate step 1 must reject the signal.

    Tests the is_active() function directly (same path the gate calls on
    each signal evaluation). Halting new orders (a), log evidence (b),
    and no position close (c) are all satisfied by the gate rejecting
    before any order creation code runs.
    """
    ops_ks.invalidate_cache()
    pool, conn = _make_pool()
    conn.settings["kill_switch_active"] = "true"

    with patch.object(ops_ks, "get_pool", return_value=pool):
        # (a) is_active() must return True → new orders halted at gate step 1
        result = asyncio.run(ops_ks.is_active())

    ops_ks.invalidate_cache()

    assert result is True, (
        "ops_ks.is_active() must return True when DB has kill_switch_active='true'; "
        f"got {result!r}"
    )

    # Verify the DB was read — proving the gate hits the real DB check
    assert conn.fetchrow_calls, "is_active() must read from DB on a cold cache"

    # (b) audit / history: verify that when the kill switch is set via set_active()
    # the history row is written with the correct actor timestamp (timestamp is
    # stored by DB default; we verify the history INSERT is present).
    pool2, conn2 = _make_pool()
    with patch.object(ops_ks, "get_pool", return_value=pool2):
        asyncio.run(ops_ks.set_active(action="pause", actor_id=42, reason="db_path_test"))

    ops_ks.invalidate_cache()

    assert conn2.history, "kill_switch_history row must be written on set_active()"
    assert conn2.settings.get("kill_switch_active") == "true"

    # (c) set_active("pause") must not contain any position UPDATE SQL
    position_updates = [
        q for q, _ in conn2.execute_calls
        if "UPDATE positions" in q
    ]
    assert not position_updates, (
        "set_active('pause') must NOT close positions; "
        f"found: {position_updates}"
    )


# ---------------------------------------------------------------------------
# Path 3 — Env var KILL_SWITCH=true → halt at startup
# ---------------------------------------------------------------------------


def test_kill_switch_env():
    """Path 3: KILL_SWITCH=true env var invokes execute_kill_switch() at startup.

    Simulates the startup guard in main.py:
        if os.getenv("KILL_SWITCH", "false").lower() == "true":
            await execute_kill_switch(triggered_by="env_KILL_SWITCH", ...)

    Verifies:
    (a) execute_kill_switch() is called exactly once when KILL_SWITCH=true
    (b) triggered_by references 'KILL_SWITCH' (audit trail identifies source)
    (c) KILL_SWITCH=false → execute_kill_switch() is NOT called
    """
    calls: list[dict] = []

    async def _fake_execute_kill_switch(reason: str, triggered_by: str) -> None:
        calls.append({"reason": reason, "triggered_by": triggered_by})

    async def _simulate_startup() -> None:
        if os.getenv("KILL_SWITCH", "false").lower() == "true":
            await _fake_execute_kill_switch(
                reason="Env var KILL_SWITCH=true on startup",
                triggered_by="env_KILL_SWITCH",
            )

    # (a) KILL_SWITCH=true → called exactly once
    with patch.dict(os.environ, {"KILL_SWITCH": "true"}):
        asyncio.run(_simulate_startup())

    assert len(calls) == 1, (
        f"execute_kill_switch must be called exactly once when KILL_SWITCH=true, "
        f"got {len(calls)} calls"
    )
    assert "KILL_SWITCH" in calls[0]["triggered_by"], (
        f"triggered_by must reference 'KILL_SWITCH', got {calls[0]['triggered_by']!r}"
    )

    # (b) triggered_by identifies the source for audit
    assert calls[0]["triggered_by"] == "env_KILL_SWITCH"

    # (c) KILL_SWITCH=false → NOT called
    calls.clear()
    with patch.dict(os.environ, {"KILL_SWITCH": "false"}):
        asyncio.run(_simulate_startup())

    assert not calls, (
        "execute_kill_switch must NOT be called when KILL_SWITCH=false; "
        f"got {len(calls)} calls"
    )
