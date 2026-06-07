"""WARP-82 — disk_monitor job tests. Hermetic: fake conn/pool, no DB."""
from __future__ import annotations

import asyncio

from projects.polymarket.crusaderbot.jobs import disk_monitor


def _run(coro):
    return asyncio.run(coro)


class _Conn:
    def __init__(self, size_bytes: int, *, throttled: bool = False, boom: bool = False):
        self.size_bytes = size_bytes
        self.throttled = throttled
        self.boom = boom
        self.inserts: list = []

    async def fetchval(self, sql, *args):
        if self.boom:
            raise RuntimeError("db down")
        if "pg_database_size" in sql:
            return self.size_bytes
        if "system_alerts" in sql:           # throttle probe
            return 1 if self.throttled else None
        return None

    async def execute(self, sql, *args):
        self.inserts.append((sql, args))


class _Acquire:
    def __init__(self, conn): self._c = conn
    async def __aenter__(self): return self._c
    async def __aexit__(self, *a): return False


class _Pool:
    def __init__(self, conn): self._c = conn
    def acquire(self): return _Acquire(self._c)


_MB = 1024 * 1024


def test_no_alert_under_threshold():
    conn = _Conn(100 * _MB)
    assert _run(disk_monitor.run_job(pool=_Pool(conn))) is None
    assert conn.inserts == []


def test_warning_at_360mb():
    conn = _Conn(360 * _MB)
    assert _run(disk_monitor.run_job(pool=_Pool(conn))) == "warning"
    assert len(conn.inserts) == 1
    args = conn.inserts[0][1]
    assert args[0] == "warning"               # severity
    assert "disk_usage" in args[3]            # metadata JSON discriminator


def test_critical_at_430mb():
    conn = _Conn(430 * _MB)
    assert _run(disk_monitor.run_job(pool=_Pool(conn))) == "critical"
    assert conn.inserts[0][1][0] == "critical"


def test_throttled_second_alert_suppressed():
    conn = _Conn(430 * _MB, throttled=True)
    assert _run(disk_monitor.run_job(pool=_Pool(conn))) is None
    assert conn.inserts == []                 # throttle → no duplicate insert


def test_failsoft_on_db_error_does_not_raise():
    conn = _Conn(430 * _MB, boom=True)
    # Must swallow + return None (never crash the scheduler).
    assert _run(disk_monitor.run_job(pool=_Pool(conn))) is None
