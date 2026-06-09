"""WARP-92 — PATCH /admin/settings/live-trading handler.

Verifies the admin global live-trading toggle:

  * non-bool body → HTTP 400
  * valid body upserts system_settings, invalidates the gate cache, and
    records a mode_change_events row with reason=ADMIN_GLOBAL_TOGGLE (user_id
    None, from_mode=prev, to_mode=new).

Hermetic: token check, pool, cache, and audit writer are all patched.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from projects.polymarket.crusaderbot.api import admin as admin_mod
from projects.polymarket.crusaderbot.domain.ops import global_live_gate as glg
from projects.polymarket.crusaderbot.domain.activation import (
    live_opt_in_gate as opt_in,
)


class FakeConn:
    def __init__(self, prev: str | None) -> None:
        self.settings: dict[str, str] = {}
        if prev is not None:
            self.settings["global_live_trading_enabled"] = prev
        self.execute_calls: list[tuple[str, tuple]] = []

    async def fetchrow(self, query: str, *args: Any):
        key = args[0]
        if key in self.settings:
            return {"value": self.settings[key]}
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

    async def __aexit__(self, *a) -> bool:
        return False


class FakePool:
    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn

    def acquire(self) -> FakeAcquire:
        return FakeAcquire(self.conn)


_AUTH = "Bearer secret-token"


def _patch_auth():
    return patch.object(
        admin_mod, "get_settings",
        return_value=SimpleNamespace(ADMIN_API_TOKEN="secret-token"))


def test_non_bool_body_returns_400():
    conn = FakeConn(prev="false")
    with _patch_auth(), patch.object(admin_mod, "get_pool",
                                     return_value=FakePool(conn)):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(admin_mod.set_global_live_trading(
                {"enabled": "yes"}, authorization=_AUTH))
    assert exc.value.status_code == 400


def test_enable_upserts_invalidates_and_audits():
    conn = FakeConn(prev="false")
    writer = AsyncMock(return_value=True)
    with _patch_auth(), \
         patch.object(admin_mod, "get_pool", return_value=FakePool(conn)), \
         patch.object(glg, "invalidate_cache") as cache_inv, \
         patch.object(opt_in, "write_mode_change_event", new=writer):
        result = asyncio.run(admin_mod.set_global_live_trading(
            {"enabled": True}, authorization=_AUTH))

    assert result == {"global_live_trading_enabled": True}
    assert conn.settings["global_live_trading_enabled"] == "true"
    cache_inv.assert_called_once()
    writer.assert_awaited_once()
    _, kwargs = writer.await_args
    assert kwargs["user_id"] is None
    assert kwargs["from_mode"] == "false"
    assert kwargs["to_mode"] == "true"
    assert kwargs["reason"] is opt_in.ModeChangeReason.ADMIN_GLOBAL_TOGGLE


def test_disable_records_prev_true_to_false():
    conn = FakeConn(prev="true")
    writer = AsyncMock(return_value=True)
    with _patch_auth(), \
         patch.object(admin_mod, "get_pool", return_value=FakePool(conn)), \
         patch.object(glg, "invalidate_cache"), \
         patch.object(opt_in, "write_mode_change_event", new=writer):
        result = asyncio.run(admin_mod.set_global_live_trading(
            {"enabled": False}, authorization=_AUTH))

    assert result == {"global_live_trading_enabled": False}
    assert conn.settings["global_live_trading_enabled"] == "false"
    _, kwargs = writer.await_args
    assert kwargs["from_mode"] == "true"
    assert kwargs["to_mode"] == "false"


def test_admin_enum_member_value():
    # The new reason must serialize to the expected DB string.
    assert opt_in.ModeChangeReason.ADMIN_GLOBAL_TOGGLE.value == "admin_global_toggle"
