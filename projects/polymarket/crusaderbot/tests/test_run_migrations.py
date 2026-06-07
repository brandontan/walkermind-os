"""WARP-80 RCA — run_migrations tracking-table behaviour (database.py).

Hermetic: no real DB. A fake asyncpg connection records the SQL it runs and
simulates the schema_migrations tracker, so we can prove the new runner applies
ONLY pending files, records them, skips already-applied ones, warns (not re-runs)
on checksum drift, and fails loud on a migration error — the gap that let
migration 086 be skipped and crash-loop the boot. No production migration is
touched; all migrations are temp fixtures.
"""
from __future__ import annotations

import asyncio

import pytest

from projects.polymarket.crusaderbot import database as db


def _run(coro):
    return asyncio.run(coro)


class _FakeConn:
    """Records migration executions + simulates the schema_migrations tracker."""

    def __init__(self, preapplied: dict[str, str] | None = None):
        self.applied: dict[str, str] = dict(preapplied or {})
        self.executed: list[str] = []          # migration bodies actually run
        self.tracker_created = False

    async def execute(self, sql, *args):
        s = sql.strip()
        if "schema_migrations" in sql and "CREATE TABLE" in sql:
            self.tracker_created = True
            return
        if s.startswith("INSERT INTO schema_migrations"):
            self.applied[args[0]] = args[1]      # filename -> checksum
            return
        # Otherwise it's a migration body.
        self.executed.append(sql)
        if "BOOM" in sql:                        # sentinel for a failing migration
            raise RuntimeError("simulated migration failure")

    async def fetch(self, sql, *args):
        if "FROM schema_migrations" in sql:
            return [{"filename": k, "checksum": v} for k, v in self.applied.items()]
        return []


class _Acquire:
    def __init__(self, conn): self._conn = conn
    async def __aenter__(self): return self._conn
    async def __aexit__(self, *exc): return False


class _FakePool:
    def __init__(self, conn): self._conn = conn
    def acquire(self): return _Acquire(self._conn)


def _write(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


# ── discovery ─────────────────────────────────────────────────────────────────

def test_discover_sorted_sql_only(tmp_path):
    _write(tmp_path, "010_c.sql", "select 10;")
    _write(tmp_path, "002_b.sql", "select 2;")
    _write(tmp_path, "001_a.sql", "select 1;")
    _write(tmp_path, "notes.txt", "ignore me")
    _write(tmp_path, "README.md", "# ignore")
    names = [p.name for p in db._discover_migrations(tmp_path)]
    assert names == ["001_a.sql", "002_b.sql", "010_c.sql"]


def test_checksum_deterministic():
    assert db._migration_checksum("CREATE TABLE x();") == db._migration_checksum("CREATE TABLE x();")
    assert db._migration_checksum("a") != db._migration_checksum("b")


# ── apply / track ─────────────────────────────────────────────────────────────

def test_applies_all_on_empty_tracker(tmp_path):
    _write(tmp_path, "001_a.sql", "CREATE TABLE a();")
    _write(tmp_path, "002_b.sql", "CREATE TABLE b();")
    _write(tmp_path, "003_c.sql", "CREATE TABLE c();")
    conn = _FakeConn()
    newly = _run(db.run_migrations(migrations_dir=tmp_path, pool=_FakePool(conn)))
    assert newly == ["001_a.sql", "002_b.sql", "003_c.sql"]
    assert conn.tracker_created is True
    assert set(conn.applied) == {"001_a.sql", "002_b.sql", "003_c.sql"}
    assert len(conn.executed) == 3


def test_skips_already_applied(tmp_path):
    f1 = _write(tmp_path, "001_a.sql", "CREATE TABLE a();")
    f2 = _write(tmp_path, "002_b.sql", "CREATE TABLE b();")
    _write(tmp_path, "003_c.sql", "CREATE TABLE c();")
    pre = {
        "001_a.sql": db._migration_checksum(f1.read_text()),
        "002_b.sql": db._migration_checksum(f2.read_text()),
    }
    conn = _FakeConn(preapplied=pre)
    newly = _run(db.run_migrations(migrations_dir=tmp_path, pool=_FakePool(conn)))
    assert newly == ["003_c.sql"]               # only the new file
    assert conn.executed == ["CREATE TABLE c();"]
    assert "003_c.sql" in conn.applied


def test_failure_is_fail_loud_and_records_prior(tmp_path):
    _write(tmp_path, "001_a.sql", "CREATE TABLE a();")
    _write(tmp_path, "002_bad.sql", "BOOM this fails;")
    _write(tmp_path, "003_c.sql", "CREATE TABLE c();")
    conn = _FakeConn()
    with pytest.raises(RuntimeError):
        _run(db.run_migrations(migrations_dir=tmp_path, pool=_FakePool(conn)))
    # 001 applied + recorded; the failing 002 and everything after are NOT recorded.
    assert "001_a.sql" in conn.applied
    assert "002_bad.sql" not in conn.applied
    assert "003_c.sql" not in conn.applied


def test_checksum_mismatch_warns_not_rerun(tmp_path):
    _write(tmp_path, "001_a.sql", "CREATE TABLE a();")
    conn = _FakeConn(preapplied={"001_a.sql": "STALE_CHECKSUM"})
    newly = _run(db.run_migrations(migrations_dir=tmp_path, pool=_FakePool(conn)))
    assert newly == []                          # drift is warned, never silently re-run
    assert conn.executed == []                  # migration body NOT executed


def test_no_files_returns_empty(tmp_path):
    conn = _FakeConn()
    assert _run(db.run_migrations(migrations_dir=tmp_path, pool=_FakePool(conn))) == []


def test_rerun_is_noop_once_recorded(tmp_path):
    """Second run with the same tracker state applies nothing (idempotent boot)."""
    _write(tmp_path, "001_a.sql", "CREATE TABLE a();")
    conn = _FakeConn()
    first = _run(db.run_migrations(migrations_dir=tmp_path, pool=_FakePool(conn)))
    assert first == ["001_a.sql"]
    conn.executed.clear()
    second = _run(db.run_migrations(migrations_dir=tmp_path, pool=_FakePool(conn)))
    assert second == [] and conn.executed == []
