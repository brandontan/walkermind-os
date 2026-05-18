"""Nightly logical deposit sweep — correct count + audit breadcrumb.

Regression: the old ``UPDATE ... RETURNING 1`` + ``fetchval`` always
logged 1/None, never the true number of swept rows (a silent
observability failure). The sweep now wraps the UPDATE in a CTE and
COUNT(*)s it inside a transaction, and writes an audit row.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from projects.polymarket.crusaderbot import scheduler


class _Txn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return None


class _Conn:
    def __init__(self, count: int) -> None:
        self._count = count
        self.fetchval = AsyncMock(return_value=count)

    def transaction(self):
        return _Txn()


class _Acq:
    def __init__(self, conn: _Conn) -> None:
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *_a):
        return None


class _Pool:
    def __init__(self, conn: _Conn) -> None:
        self._conn = conn

    def acquire(self):
        return _Acq(self._conn)


def _run_sweep(count: int) -> AsyncMock:
    conn = _Conn(count)
    audit_mock = AsyncMock()
    with patch.object(scheduler, "get_pool", return_value=_Pool(conn)), \
         patch.object(scheduler.audit, "write", new=audit_mock):
        asyncio.run(scheduler.sweep_deposits())
    return audit_mock, conn


def test_sweep_logs_true_count_and_audits():
    audit_mock, conn = _run_sweep(7)
    conn.fetchval.assert_awaited_once()
    sql = conn.fetchval.call_args[0][0]
    assert "COUNT(*)" in sql and "WITH u AS" in sql
    audit_mock.assert_awaited_once()
    kwargs = audit_mock.call_args.kwargs
    assert kwargs["action"] == "deposit_sweep"
    assert kwargs["payload"] == {"count": 7}
    assert kwargs["actor_role"] == "bot"


def test_sweep_zero_rows_still_audits_zero():
    audit_mock, _ = _run_sweep(0)
    audit_mock.assert_awaited_once()
    assert audit_mock.call_args.kwargs["payload"] == {"count": 0}
