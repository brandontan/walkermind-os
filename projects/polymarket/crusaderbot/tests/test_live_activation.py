"""Hermetic tests for WARP-92 is_live_execution_allowed composition.

All four conditions must hold for True. Each is independently falsified.
No real DB/network. ENABLE_LIVE_TRADING and the global gate are patched;
user_settings reads come from a fake pool.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from projects.polymarket.crusaderbot.domain.execution import live_activation as la

_UID = uuid4()


class FakeConn:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row
        self.fetchrow_calls = 0

    async def fetchrow(self, query: str, *args: Any):
        self.fetchrow_calls += 1
        return self._row


class FakeAcquire:
    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn

    async def __aenter__(self) -> FakeConn:
        return self.conn

    async def __aexit__(self, *a) -> bool:
        return False


class FakePool:
    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn

    def acquire(self) -> FakeAcquire:
        return FakeAcquire(self.conn)


def _run(row, *, env_live=True, global_live=True):
    conn = FakeConn(row)
    with patch.object(la, "get_settings",
                      return_value=SimpleNamespace(ENABLE_LIVE_TRADING=env_live)), \
         patch.object(la, "is_global_live_enabled",
                      new=AsyncMock(return_value=global_live)), \
         patch.object(la, "get_pool", return_value=FakePool(conn)):
        return asyncio.run(la.is_live_execution_allowed(_UID)), conn


_GOOD_ROW = {
    "trading_mode": "live",
    "paper_mode_override": False,
    "live_capital_cap_usdc": 500,
}


def test_all_conditions_hold_returns_true():
    result, _ = _run(dict(_GOOD_ROW))
    assert result is True


def test_env_guard_off_returns_false():
    result, conn = _run(dict(_GOOD_ROW), env_live=False)
    assert result is False
    # Short-circuit: no user_settings read when env guard is off.
    assert conn.fetchrow_calls == 0


def test_global_flag_false_returns_false():
    result, conn = _run(dict(_GOOD_ROW), global_live=False)
    assert result is False
    assert conn.fetchrow_calls == 0


def test_missing_user_row_returns_false():
    result, _ = _run(None)
    assert result is False


def test_paper_mode_override_true_returns_false():
    row = dict(_GOOD_ROW, paper_mode_override=True)
    result, _ = _run(row)
    assert result is False


def test_trading_mode_not_live_returns_false():
    row = dict(_GOOD_ROW, trading_mode="paper")
    result, _ = _run(row)
    assert result is False


def test_zero_capital_cap_returns_false():
    row = dict(_GOOD_ROW, live_capital_cap_usdc=0)
    result, _ = _run(row)
    assert result is False


def test_null_capital_cap_returns_false():
    row = dict(_GOOD_ROW, live_capital_cap_usdc=None)
    result, _ = _run(row)
    assert result is False
