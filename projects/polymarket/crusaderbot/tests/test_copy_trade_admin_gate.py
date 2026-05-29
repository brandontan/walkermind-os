"""Regression tests for the operator's global copy_trade admin toggle.

Mirrors the FAIL-SAFE contract in signal_scan_job._refresh_disabled_strategies():
a missing row in the `strategies` table = ON (no behaviour change). Only an
explicit `enabled=FALSE` row stops the copy_trade monitor tick.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from projects.polymarket.crusaderbot.services.copy_trade import monitor


class _FakeConn:
    def __init__(self, enabled_val):
        self._enabled = enabled_val

    async def fetchval(self, sql, *args):
        return self._enabled


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _Ctx:
            async def __aenter__(self_inner):
                return conn

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        return _Ctx()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


def test_is_globally_disabled_true_when_row_says_false():
    pool = _FakePool(_FakeConn(False))
    with patch.object(monitor, "get_pool", return_value=pool):
        assert _run(monitor._is_globally_disabled()) is True


def test_is_globally_disabled_false_when_row_says_true():
    pool = _FakePool(_FakeConn(True))
    with patch.object(monitor, "get_pool", return_value=pool):
        assert _run(monitor._is_globally_disabled()) is False


def test_is_globally_disabled_false_when_row_missing():
    """FAIL-SAFE: missing row = ON (no behaviour change)."""
    pool = _FakePool(_FakeConn(None))
    with patch.object(monitor, "get_pool", return_value=pool):
        assert _run(monitor._is_globally_disabled()) is False


def test_is_globally_disabled_false_on_db_error():
    """FAIL-SAFE: a DB blip never silently disables copy_trade."""

    class _BrokenPool:
        def acquire(self_inner):
            raise RuntimeError("db down")

    with patch.object(monitor, "get_pool", return_value=_BrokenPool()):
        assert _run(monitor._is_globally_disabled()) is False


def test_run_once_skips_tick_when_admin_disabled():
    """When the operator has toggled copy_trade OFF, the tick must exit before
    touching list_active_tasks or the execution path."""
    pool = _FakePool(_FakeConn(False))  # enabled=FALSE
    with (
        patch.object(monitor, "kill_switch_is_active", new=AsyncMock(return_value=False)),
        patch.object(monitor, "get_pool", return_value=pool),
        patch.object(monitor, "list_active_tasks", new=AsyncMock(return_value=[])) as la,
    ):
        _run(monitor.run_once())
    la.assert_not_awaited()


def test_run_once_proceeds_when_admin_enabled():
    pool = _FakePool(_FakeConn(True))  # enabled=TRUE
    with (
        patch.object(monitor, "kill_switch_is_active", new=AsyncMock(return_value=False)),
        patch.object(monitor, "get_pool", return_value=pool),
        patch.object(monitor, "list_active_tasks", new=AsyncMock(return_value=[])) as la,
    ):
        _run(monitor.run_once())
    la.assert_awaited_once()


def test_run_once_proceeds_when_strategies_row_missing():
    """Fail-safe at run_once level: no row -> proceed (no behaviour change)."""
    pool = _FakePool(_FakeConn(None))
    with (
        patch.object(monitor, "kill_switch_is_active", new=AsyncMock(return_value=False)),
        patch.object(monitor, "get_pool", return_value=pool),
        patch.object(monitor, "list_active_tasks", new=AsyncMock(return_value=[])) as la,
    ):
        _run(monitor.run_once())
    la.assert_awaited_once()


def test_run_once_kill_switch_still_wins():
    """The kill switch check fires before the admin gate."""
    pool = _FakePool(_FakeConn(False))
    with (
        patch.object(monitor, "kill_switch_is_active", new=AsyncMock(return_value=True)),
        patch.object(monitor, "get_pool", return_value=pool),
        patch.object(monitor, "list_active_tasks", new=AsyncMock(return_value=[])) as la,
    ):
        _run(monitor.run_once())
    la.assert_not_awaited()
