"""Hermetic tests for bankroll circuit-breaker state persistence.

WARP/ROOT/bankroll-cb-persistence-impl — closes audit F19/F4.

Covers the restart-durability of the breaker's in-memory state:
    * _persist_bankroll_circuit_state — UPSERT shape + values (trip + resume)
    * _restore_bankroll_circuit_state — round-trip into the in-memory dicts
    * tripped latch survives a simulated restart (the core F19 regression)
    * baseline restored is the persisted peak, not the drawn-down balance
    * restore does NOT clobber state already warmed this process
    * fail-OPEN: a DB error in persist/restore never raises
    * no persisted row / invalid baseline rows are skipped defensively

No DB, no broker, no network — the asyncpg pool is faked.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch
from uuid import uuid4

from projects.polymarket.crusaderbot.services.signal_scan import (
    signal_scan_job as job,
)


# ---------------------------------------------------------------------------
# Minimal fake asyncpg pool: records executes, replays a fetch result set.
# ---------------------------------------------------------------------------


class _FakeConn:
    def __init__(self, fetch_rows=None, raise_on=None):
        self._fetch_rows = fetch_rows or []
        self._raise_on = raise_on  # "fetch" | "execute" | None
        self.executes: list[tuple] = []

    async def fetch(self, sql, *args):
        if self._raise_on == "fetch":
            raise RuntimeError("simulated DB fetch failure")
        return list(self._fetch_rows)

    async def execute(self, sql, *args):
        if self._raise_on == "execute":
            raise RuntimeError("simulated DB execute failure")
        self.executes.append((sql, args))


class _FakePool:
    def __init__(self, conn: _FakeConn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _Ctx:
            async def __aenter__(self_inner):
                return conn

            async def __aexit__(self_inner, *a):
                return False

        return _Ctx()


def _patch_pool(conn: _FakeConn):
    return patch.object(job, "get_pool", return_value=_FakePool(conn))


def _run(coro):
    return asyncio.run(coro)


def _setup():
    """Isolate in-memory breaker state before each test."""
    job._bankroll_reset_for_tests()


# ---------------------------------------------------------------------------
# persist
# ---------------------------------------------------------------------------


def test_persist_upserts_baseline_and_tripped():
    _setup()
    uid = str(uuid4())
    job._bankroll_ema_baseline[uid] = 100.0
    job._bankroll_circuit_tripped[uid] = True
    conn = _FakeConn()
    with _patch_pool(conn):
        _run(job._persist_bankroll_circuit_state(uid))
    assert len(conn.executes) == 1
    sql, args = conn.executes[0]
    assert "INSERT INTO bankroll_circuit_state" in sql
    assert "ON CONFLICT (user_id) DO UPDATE" in sql
    # user_id column is UUID; the param is a Python str, so the query MUST cast
    # ($1::uuid) or asyncpg raises DataError and — under the fail-open wrapper —
    # silently never persists. Pin the cast.
    assert "$1::uuid" in sql
    assert args == (uid, 100.0, True)


def test_persist_writes_resume_state_false():
    _setup()
    uid = str(uuid4())
    job._bankroll_ema_baseline[uid] = 250.0
    job._bankroll_circuit_tripped[uid] = False  # resumed
    conn = _FakeConn()
    with _patch_pool(conn):
        _run(job._persist_bankroll_circuit_state(uid))
    _sql, args = conn.executes[0]
    assert args == (uid, 250.0, False)


def test_persist_skips_when_no_baseline():
    _setup()
    uid = str(uuid4())  # no baseline warmed
    conn = _FakeConn()
    with _patch_pool(conn):
        _run(job._persist_bankroll_circuit_state(uid))
    assert conn.executes == []  # nothing to persist


def test_persist_fail_open_on_db_error():
    _setup()
    uid = str(uuid4())
    job._bankroll_ema_baseline[uid] = 100.0
    conn = _FakeConn(raise_on="execute")
    with _patch_pool(conn):
        # Must NOT raise — fail-open contract.
        _run(job._persist_bankroll_circuit_state(uid))


# ---------------------------------------------------------------------------
# restore
# ---------------------------------------------------------------------------


def test_restore_round_trip_into_memory():
    _setup()
    uid = str(uuid4())
    conn = _FakeConn(fetch_rows=[{"user_id": uid, "baseline": 500.0, "tripped": True}])
    with _patch_pool(conn):
        _run(job._restore_bankroll_circuit_state())
    assert job._bankroll_ema_baseline[uid] == 500.0
    assert job._bankroll_circuit_tripped[uid] is True


def test_tripped_latch_survives_restart():
    """Core F19 regression: a tripped breaker must NOT silently un-trip on
    restart. Simulate restart = clear in-memory state, then restore from DB."""
    _setup()
    uid = str(uuid4())
    # Pre-restart: user is tripped at baseline 1000.
    job._bankroll_ema_baseline[uid] = 1000.0
    job._bankroll_circuit_tripped[uid] = True
    persist_conn = _FakeConn()
    with _patch_pool(persist_conn):
        _run(job._persist_bankroll_circuit_state(uid))
    _sql, args = persist_conn.executes[0]
    persisted = {"user_id": args[0], "baseline": args[1], "tripped": args[2]}

    # Simulate process restart: in-memory state is wiped.
    job._bankroll_reset_for_tests()
    assert uid not in job._bankroll_circuit_tripped

    # Restore from the persisted row.
    restore_conn = _FakeConn(fetch_rows=[persisted])
    with _patch_pool(restore_conn):
        _run(job._restore_bankroll_circuit_state())

    # The latch is back — the breaker is still tripped after restart.
    assert job._bankroll_circuit_tripped[uid] is True
    assert job._bankroll_ema_baseline[uid] == 1000.0


def test_restore_does_not_clobber_warmed_state():
    _setup()
    uid = str(uuid4())
    # State already warmed this process (fresher than DB).
    job._bankroll_ema_baseline[uid] = 900.0
    job._bankroll_circuit_tripped[uid] = False
    conn = _FakeConn(fetch_rows=[{"user_id": uid, "baseline": 100.0, "tripped": True}])
    with _patch_pool(conn):
        _run(job._restore_bankroll_circuit_state())
    # Untouched — in-process state wins.
    assert job._bankroll_ema_baseline[uid] == 900.0
    assert job._bankroll_circuit_tripped[uid] is False


def test_restore_skips_invalid_baseline_rows():
    _setup()
    good = str(uuid4())
    bad_zero = str(uuid4())
    bad_none = str(uuid4())
    conn = _FakeConn(fetch_rows=[
        {"user_id": good, "baseline": 300.0, "tripped": False},
        {"user_id": bad_zero, "baseline": 0.0, "tripped": True},
        {"user_id": bad_none, "baseline": None, "tripped": True},
    ])
    with _patch_pool(conn):
        _run(job._restore_bankroll_circuit_state())
    assert job._bankroll_ema_baseline[good] == 300.0
    assert bad_zero not in job._bankroll_ema_baseline
    assert bad_none not in job._bankroll_ema_baseline


def test_restore_fail_open_on_db_error():
    _setup()
    conn = _FakeConn(raise_on="fetch")
    with _patch_pool(conn):
        # Must NOT raise; dicts stay empty (cold-start behaviour).
        _run(job._restore_bankroll_circuit_state())
    assert job._bankroll_ema_baseline == {}
    assert job._bankroll_circuit_tripped == {}


def test_restore_empty_table_noop():
    _setup()
    conn = _FakeConn(fetch_rows=[])
    with _patch_pool(conn):
        _run(job._restore_bankroll_circuit_state())
    assert job._bankroll_ema_baseline == {}


# ---------------------------------------------------------------------------
# Source pins — fail closed if the wiring is removed.
# ---------------------------------------------------------------------------


def test_run_once_restore_is_flag_gated():
    """run_once must gate the restore on BANKROLL_CIRCUIT_BREAKER_ENABLED so the
    feature is a no-op (zero DB work) while the breaker is dark."""
    import inspect

    src = inspect.getsource(job.run_once)
    assert "_restore_bankroll_circuit_state" in src
    assert "BANKROLL_CIRCUIT_BREAKER_ENABLED" in src


def test_gate_persists_after_evaluate():
    """The circuit-breaker gate must persist state after evaluating (so both
    trip and resume transitions are written)."""
    import inspect

    src = inspect.getsource(job._process_candidate)
    assert "_persist_bankroll_circuit_state" in src
