"""WARP-59 hermetic tests for the MVP copy-wallet → production scanner bridge.

The MVP Telegram UX (`bot/handlers/mvp/copy_wallet.py`) used to write wallet
entries to `copy_targets`, but the production execution scanner
(`services/copy_trade/monitor.py:run_once`) reads `copy_trade_tasks` via
`domain/copy_trade/repository.py:list_active_tasks`. WARP-59 aligns the MVP
write path to `copy_trade_tasks` so wallets added via the MVP UX are picked
up by the scanner end-to-end.

No DB, no Telegram network. The asyncpg pool is replaced with a recording
fake that captures every executed SQL string so the assertions can pin the
exact table the handler is writing to.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

import projects.polymarket.crusaderbot.bot.handlers.mvp.copy_wallet as cw_mod
import projects.polymarket.crusaderbot.domain.copy_trade.repository as repo_mod


# ---------------------------------------------------------------------------
# Fake asyncpg pool that records every SQL string + args it sees.
# ---------------------------------------------------------------------------


class _RecConn:
    """Minimal asyncpg.Connection stand-in.

    Each instance carries a script keyed by SQL substring → queued results.
    The first script entry whose key is a substring of the SQL wins; queued
    results are popped FIFO so a single connection can serve multiple
    sequential calls with deterministic returns.
    """

    def __init__(self, rows: dict[str, list[Any]] | None = None) -> None:
        self._rows = rows or {}
        self.calls: list[tuple[str, str, tuple]] = []  # (method, sql, args)

    def _match(self, sql: str) -> Any:
        for needle, queue in self._rows.items():
            if needle in sql and queue:
                return queue.pop(0)
        return None

    async def execute(self, sql: str, *args: Any) -> None:
        self.calls.append(("execute", sql, args))

    async def fetchrow(self, sql: str, *args: Any) -> Any:
        self.calls.append(("fetchrow", sql, args))
        return self._match(sql)

    async def fetch(self, sql: str, *args: Any) -> list[Any]:
        self.calls.append(("fetch", sql, args))
        v = self._match(sql)
        return v if v is not None else []

    async def fetchval(self, sql: str, *args: Any) -> Any:
        self.calls.append(("fetchval", sql, args))
        v = self._match(sql)
        return v if v is not None else 0


class _RecPool:
    def __init__(self, conn: _RecConn) -> None:
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _Ctx:
            async def __aenter__(self_inner):
                return conn

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        return _Ctx()


# ---------------------------------------------------------------------------
# Update / ContextTypes stand-ins — only the attributes the handler touches.
# ---------------------------------------------------------------------------


def _make_update() -> SimpleNamespace:
    user = SimpleNamespace(id=42, username="alice")
    return SimpleNamespace(effective_user=user, message=None, callback_query=None)


class _Ctx:
    def __init__(self) -> None:
        self.user_data: dict = {}


_USER_UUID = uuid4()
_WALLET = "0x" + "ab" * 20  # 40 hex chars
_WALLET_LOWER = _WALLET.lower()


def _patch_handler_pool(conn: _RecConn):
    return patch(
        "projects.polymarket.crusaderbot.database.get_pool",
        return_value=_RecPool(conn),
    )


def _patch_repo_pool(conn: _RecConn):
    return patch(
        "projects.polymarket.crusaderbot.domain.copy_trade.repository.get_pool",
        return_value=_RecPool(conn),
    )


def _patch_fetch_user():
    return patch(
        "projects.polymarket.crusaderbot.bot.handlers.mvp._users.fetch_user",
        new=AsyncMock(return_value={"id": _USER_UUID}),
    )


def _patch_send_or_edit():
    return patch(
        "projects.polymarket.crusaderbot.bot.handlers.mvp._send.send_or_edit",
        new=AsyncMock(return_value=None),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_do_start_copying_inserts_into_copy_trade_tasks():
    """First-time wallet add hits copy_trade_tasks, not copy_targets."""
    conn = _RecConn(rows={
        "FROM copy_trade_tasks": [None],  # existing-row probe → None
    })

    upd = _make_update()
    ctx = _Ctx()
    ctx.user_data[cw_mod._FLOW_KEY] = {
        "step": "review",
        "address": _WALLET,
        "allocation": 50.0,
        "risk": "Balanced",
    }

    with _patch_handler_pool(conn), _patch_fetch_user(), _patch_send_or_edit():
        asyncio.run(cw_mod.do_start_copying(upd, ctx))

    insert_calls = [c for c in conn.calls if c[0] == "execute"
                    and "INSERT INTO copy_trade_tasks" in c[1]]
    assert len(insert_calls) == 1, (
        f"Expected exactly one INSERT INTO copy_trade_tasks; got {conn.calls!r}"
    )
    sql, args = insert_calls[0][1], insert_calls[0][2]

    # No legacy table writes survive.
    assert "copy_targets" not in sql

    # Args order: user_id, wallet_address, task_name, copy_amount
    assert args[0] == _USER_UUID
    assert args[1] == _WALLET_LOWER
    assert args[3] == 50.0  # allocation_usdc → copy_amount


def test_do_start_copying_updates_existing_row_instead_of_duplicate():
    """Re-adding the same wallet updates the existing row (manual upsert)."""
    existing_id = uuid4()
    conn = _RecConn(rows={
        "FROM copy_trade_tasks": [{"id": existing_id}],  # existing-row probe
    })

    upd = _make_update()
    ctx = _Ctx()
    ctx.user_data[cw_mod._FLOW_KEY] = {
        "step": "review",
        "address": _WALLET,
        "allocation": 250.0,
        "risk": "Balanced",
    }

    with _patch_handler_pool(conn), _patch_fetch_user(), _patch_send_or_edit():
        asyncio.run(cw_mod.do_start_copying(upd, ctx))

    inserts = [c for c in conn.calls if c[0] == "execute"
               and "INSERT INTO copy_trade_tasks" in c[1]]
    updates = [c for c in conn.calls if c[0] == "execute"
               and "UPDATE copy_trade_tasks" in c[1]]

    assert not inserts, "Must not INSERT when an existing row is found"
    assert len(updates) == 1, f"Expected one UPDATE; got {conn.calls!r}"
    sql, args = updates[0][1], updates[0][2]
    assert "'active'" in sql
    assert args[0] == 250.0  # copy_amount = allocation_usdc
    assert args[2] == existing_id  # WHERE id=$3


def test_do_pause_targets_copy_trade_tasks():
    """Pause hits copy_trade_tasks (status='paused'), not copy_targets."""
    conn = _RecConn()

    upd = _make_update()
    ctx = _Ctx()

    with _patch_handler_pool(conn), _patch_fetch_user(), _patch_send_or_edit():
        asyncio.run(cw_mod.do_pause(upd, ctx))

    pause_calls = [c for c in conn.calls if c[0] == "execute"
                   and "UPDATE copy_trade_tasks" in c[1]]
    assert pause_calls, f"Expected an UPDATE on copy_trade_tasks; got {conn.calls!r}"
    sql = pause_calls[0][1]
    assert "copy_targets" not in sql
    assert "'paused'" in sql


def test_read_wallets_reads_copy_trade_tasks():
    """`_read_wallets` SELECT targets copy_trade_tasks with mapped aliases."""
    row = {
        "id": uuid4(),
        "address": _WALLET_LOWER,
        "enabled": True,
        "allocation": 100.0,
    }
    conn = _RecConn(rows={"FROM copy_trade_tasks": [[row]]})

    with _patch_handler_pool(conn):
        out = asyncio.run(cw_mod._read_wallets(_USER_UUID))

    fetch_calls = [c for c in conn.calls if c[0] == "fetch"]
    assert fetch_calls, "Expected one fetch() on copy_trade_tasks"
    sql = fetch_calls[0][1]
    assert "FROM copy_trade_tasks" in sql
    assert "copy_targets" not in sql
    assert out and out[0]["address"] == _WALLET_LOWER
    assert out[0]["enabled"] is True
    assert out[0]["allocation"] == 100.0


def test_bridge_end_to_end_visibility_to_list_active_tasks():
    """An MVP-inserted row is visible to list_active_tasks() via the same DB.

    The fake pool serves both writers (MVP handler) and readers
    (`domain/copy_trade/repository.list_active_tasks`). After the MVP insert
    runs, the next scanner read returns a row that matches the inserted
    wallet — proving the bridge holds without any view/trigger.
    """
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    inserted_row = {
        "id": uuid4(),
        "user_id": _USER_UUID,
        "wallet_address": _WALLET_LOWER,
        "task_name": "MVP",
        "status": "active",
        "copy_mode": "fixed",
        "copy_amount": 100.0,
        "copy_pct": None,
        "tp_pct": 0.20,
        "sl_pct": 0.10,
        "max_daily_spend": 100.00,
        "slippage_pct": 0.05,
        "min_trade_size": 0.50,
        "reverse_copy": False,
        "created_at": now,
        "updated_at": now,
        "nickname": "MVP",
        "copy_direction": "buys_only",
        "execution_mode": "auto",
        "allow_topups": True,
    }
    # Conn serves: (a) handler upsert probe (None → triggers INSERT),
    # (b) scanner-style SELECT against copy_trade_tasks.
    conn = _RecConn(rows={
        "FROM copy_trade_tasks": [None, [inserted_row]],
    })

    # Step 1 — MVP write path
    upd = _make_update()
    ctx = _Ctx()
    ctx.user_data[cw_mod._FLOW_KEY] = {
        "step": "review",
        "address": _WALLET,
        "allocation": 100.0,
        "risk": "Balanced",
    }
    with _patch_handler_pool(conn), _patch_fetch_user(), _patch_send_or_edit():
        asyncio.run(cw_mod.do_start_copying(upd, ctx))

    # Step 2 — production scanner read path (same DB, same conn)
    with _patch_repo_pool(conn):
        tasks = asyncio.run(repo_mod.list_active_tasks())

    assert len(tasks) == 1
    t = tasks[0]
    assert t.wallet_address == _WALLET_LOWER
    assert t.status == "active"
    assert t.copy_mode == "fixed"
    assert float(t.copy_amount) == 100.0


def test_no_legacy_copy_targets_writes_remain():
    """Module audit: no SQL string in copy_wallet.py references copy_targets."""
    import inspect

    src = inspect.getsource(cw_mod)
    assert "copy_targets" not in src, (
        "WARP-59 contract: bot/handlers/mvp/copy_wallet.py must not reference "
        "copy_targets — production scanner reads copy_trade_tasks."
    )
