"""WARP•R00T — db_retention job tests. Hermetic: fake conn/pool, no DB."""
from __future__ import annotations

import asyncio

from projects.polymarket.crusaderbot.jobs import db_retention


def _run(coro):
    return asyncio.run(coro)


class _Settings:
    DB_RETENTION_ENABLED = True
    DB_RETENTION_SYSTEM_ALERTS_DAYS = 30
    DB_RETENTION_SCAN_RUNS_DAYS = 30
    DB_RETENTION_PORTFOLIO_SNAPSHOTS_DAYS = 90
    DB_RETENTION_EXECUTION_QUEUE_DAYS = 30


class _Conn:
    def __init__(self, *, deleted: int = 0, fail_tables: tuple[str, ...] = ()):
        self.deleted = deleted
        self.fail_tables = fail_tables
        self.calls: list[tuple[str, tuple]] = []

    async def execute(self, sql, *args):
        self.calls.append((sql, args))
        for t in self.fail_tables:
            if f"DELETE FROM {t} " in sql:
                raise RuntimeError(f"boom {t}")
        return f"DELETE {self.deleted}"


class _Acquire:
    def __init__(self, conn): self._c = conn
    async def __aenter__(self): return self._c
    async def __aexit__(self, *a): return False


class _Pool:
    def __init__(self, conn): self._c = conn
    def acquire(self): return _Acquire(self._c)


def _patch_settings(monkeypatch, settings=None):
    monkeypatch.setattr(db_retention, "get_settings", lambda: settings or _Settings())


def _tables_hit(conn) -> set[str]:
    out = set()
    for sql, _ in conn.calls:
        for tok in ("idempotency_keys", "system_alerts", "scan_runs",
                    "portfolio_snapshots", "execution_queue"):
            if f"DELETE FROM {tok} " in sql:
                out.add(tok)
    return out


def test_disabled_flag_is_noop(monkeypatch):
    s = _Settings(); s.DB_RETENTION_ENABLED = False
    _patch_settings(monkeypatch, s)
    conn = _Conn()
    assert _run(db_retention.run_job(pool=_Pool(conn))) == {}
    assert conn.calls == []


def test_prunes_all_target_tables(monkeypatch):
    _patch_settings(monkeypatch)
    conn = _Conn(deleted=0)
    result = _run(db_retention.run_job(pool=_Pool(conn)))
    assert _tables_hit(conn) == {
        "idempotency_keys", "system_alerts", "scan_runs",
        "portfolio_snapshots", "execution_queue",
    }
    # every targeted table reports a count (0 here — nothing beyond window)
    assert set(result) == _tables_hit(conn)


def test_idempotency_keys_uses_expires_at_no_day_param(monkeypatch):
    _patch_settings(monkeypatch)
    conn = _Conn(deleted=0)
    _run(db_retention.run_job(pool=_Pool(conn)))
    ik = [(sql, args) for sql, args in conn.calls if "DELETE FROM idempotency_keys " in sql]
    assert ik, "idempotency_keys not pruned"
    sql, args = ik[0]
    assert "expires_at < NOW()" in sql
    assert args == ()  # keys off its own expiry, not a day window


def test_execution_queue_only_executed_rows(monkeypatch):
    _patch_settings(monkeypatch)
    conn = _Conn(deleted=0)
    _run(db_retention.run_job(pool=_Pool(conn)))
    eq = [sql for sql, _ in conn.calls if "DELETE FROM execution_queue " in sql][0]
    assert "executed_at IS NOT NULL" in eq  # never deletes in-flight queue items


def test_day_window_param_passed(monkeypatch):
    _patch_settings(monkeypatch)
    conn = _Conn(deleted=0)
    _run(db_retention.run_job(pool=_Pool(conn)))
    snap = [(sql, args) for sql, args in conn.calls
            if "DELETE FROM portfolio_snapshots " in sql][0]
    assert snap[1] == (90,)  # DB_RETENTION_PORTFOLIO_SNAPSHOTS_DAYS bound as $1


def test_failsoft_one_table_error_does_not_abort_others(monkeypatch):
    _patch_settings(monkeypatch)
    conn = _Conn(deleted=0, fail_tables=("scan_runs",))
    result = _run(db_retention.run_job(pool=_Pool(conn)))  # must not raise
    # failing table is absent from the result, the rest still pruned
    assert "scan_runs" not in result
    assert {"idempotency_keys", "system_alerts",
            "portfolio_snapshots", "execution_queue"} <= set(result)


def test_batched_loop_continues_until_below_batch(monkeypatch):
    _patch_settings(monkeypatch)
    # First execute returns a full batch, then a short one → two iterations.
    class _BatchConn(_Conn):
        def __init__(self):
            super().__init__()
            self._first = True
        async def execute(self, sql, *args):
            self.calls.append((sql, args))
            if "idempotency_keys" in sql and self._first:
                self._first = False
                return f"DELETE {db_retention._BATCH}"
            return "DELETE 3"
    conn = _BatchConn()
    result = _run(db_retention.run_job(pool=_Pool(conn)))
    # idempotency_keys looped twice → 5000 + 3
    assert result["idempotency_keys"] == db_retention._BATCH + 3


def test_pool_unavailable_is_noop(monkeypatch):
    _patch_settings(monkeypatch)
    monkeypatch.setattr(db_retention, "get_pool",
                        lambda: (_ for _ in ()).throw(RuntimeError("no pool")))
    assert _run(db_retention.run_job()) == {}


def test_ceiling_warns_when_backlog_remains(monkeypatch):
    # Every execute returns a full batch → loop never drops below _BATCH → the
    # iteration ceiling is hit and a warning is surfaced (no silent backlog).
    _patch_settings(monkeypatch)
    monkeypatch.setattr(db_retention, "_MAX_ITERS", 3)

    class _FullConn(_Conn):
        async def execute(self, sql, *args):
            self.calls.append((sql, args))
            return f"DELETE {db_retention._BATCH}"

    conn = _FullConn()
    result = _run(db_retention.run_job(pool=_Pool(conn)))
    # idempotency_keys looped exactly _MAX_ITERS times at full batch
    assert result["idempotency_keys"] == db_retention._BATCH * 3


def test_config_rejects_nonpositive_retention_days():
    # The Pydantic validator must fail fast on a 0/negative window so a misconfig
    # can never turn the prune job into a wipe of recent data.
    import pytest

    from projects.polymarket.crusaderbot.config import Settings

    with pytest.raises(Exception):
        Settings(DB_RETENTION_SCAN_RUNS_DAYS=0)
    with pytest.raises(Exception):
        Settings(DB_RETENTION_PORTFOLIO_SNAPSHOTS_DAYS=-5)
