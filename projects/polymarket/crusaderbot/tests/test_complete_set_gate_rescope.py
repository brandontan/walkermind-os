"""Lane 2C-1 — complete-set risk-gate re-scope + kill switch.

Covers: (1) COMPLETE_SET_ARB_ENABLED defaults OFF; (2) the step-7 concurrency
helper counts a complete set (two paired legs) as ONE unit, not two, via the
set-aware SQL.
"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from projects.polymarket.crusaderbot import config as crusaderbot_config
from projects.polymarket.crusaderbot.domain.risk import gate as gate_mod


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("OPERATOR_CHAT_ID", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("WALLET_HD_SEED", "seed")
    monkeypatch.setenv("WALLET_ENCRYPTION_KEY", "k")
    monkeypatch.setenv("POLYGON_RPC_URL", "https://rpc")
    monkeypatch.setenv("ALCHEMY_POLYGON_WS_URL", "wss://ws")


def test_complete_set_arb_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.delenv("COMPLETE_SET_ARB_ENABLED", raising=False)
    settings = crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert settings.COMPLETE_SET_ARB_ENABLED is False
    crusaderbot_config.get_settings.cache_clear()


class _FakeConn:
    def __init__(self, count: int) -> None:
        self.count = count
        self.last_query: str = ""

    async def fetchval(self, query: str, *args: Any) -> int:
        self.last_query = query
        return self.count

    async def __aenter__(self) -> "_FakeConn":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False


class _FakePool:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    def acquire(self) -> _FakeConn:
        return self._conn


@pytest.mark.asyncio
async def test_open_position_count_uses_set_aware_query(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn(count=3)
    monkeypatch.setattr(gate_mod, "get_pool", lambda: _FakePool(conn))
    n = await gate_mod._open_position_count(uuid4())
    assert n == 3
    # The query must collapse a paired set to one group key so a set counts once.
    assert "DISTINCT LEAST(id, COALESCE(paired_position_id, id))" in conn.last_query
    assert "status IN ('open','pending_settlement')" in conn.last_query
