"""Tests for the portfolio_snapshots writer (WARP-52, issue #1245).

Hermetic — no DB, no broker, no Telegram. The pool/conn surface is faked
with ``AsyncMock`` so the writer's SQL contract and the close-of-trade
integration are both exercised without touching Postgres.

Coverage targets (from WARP-52 acceptance criteria):
  - portfolio_snapshots has at least one writer in Python code
  - writer fires after paper.close_position
  - cb_portfolio NOTIFY is wired structurally (trigger present in mig 029
    and the writer INSERTs into portfolio_snapshots, which is the trigger
    source — verified by SQL string assertion)
  - writer never raises into trade-close path (best-effort contract)
  - snapshot_active_users iterates and writes per user
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from projects.polymarket.crusaderbot.services import portfolio_snapshots
from projects.polymarket.crusaderbot.domain.execution import paper as paper_exec


def _run(coro):
    return asyncio.run(coro)


def _make_pool(*, metrics_row: dict | None, insert_id: UUID | None = None):
    """Return (pool, conn, fetchrow_mock, fetchval_mock) for assertions."""
    conn = MagicMock()
    fetchrow_mock = AsyncMock(return_value=metrics_row)
    fetchval_mock = AsyncMock(return_value=insert_id)
    conn.fetchrow = fetchrow_mock
    conn.fetchval = fetchval_mock
    pool = MagicMock()
    acq = MagicMock()
    acq.__aenter__ = AsyncMock(return_value=conn)
    acq.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=acq)
    return pool, conn, fetchrow_mock, fetchval_mock


# ---------------------------------------------------------------------------
# write_snapshot: happy path, missing user, DB error.
# ---------------------------------------------------------------------------


def test_write_snapshot_inserts_row_and_returns_id():
    """Happy path: metrics fetched, INSERT executed with correct args,
    returned id propagated back to caller. Trigger fires automatically on
    INSERT — verified structurally by asserting the table name in SQL.
    """
    user_id = uuid4()
    snapshot_id = uuid4()
    metrics = {
        "balance_usdc": Decimal("1000.00"),
        "equity_usdc": Decimal("1050.00"),
        "pnl_today": Decimal("12.50"),
        "pnl_7d": Decimal("48.75"),
        "open_positions": 2,
    }
    pool, _conn, fetchrow_mock, fetchval_mock = _make_pool(
        metrics_row=metrics, insert_id=snapshot_id,
    )

    with patch.object(portfolio_snapshots, "get_pool", return_value=pool):
        result = _run(portfolio_snapshots.write_snapshot(user_id))

    assert result == snapshot_id
    # Metrics SELECT executed with user_id.
    fetchrow_mock.assert_awaited_once()
    select_sql, select_arg = fetchrow_mock.call_args.args
    assert "wallets" in select_sql
    assert "portfolio_snapshots" not in select_sql.split("INSERT")[0]
    assert select_arg == user_id
    # INSERT executed against portfolio_snapshots with the computed metrics.
    fetchval_mock.assert_awaited_once()
    insert_sql, *insert_args = fetchval_mock.call_args.args
    assert "INSERT INTO portfolio_snapshots" in insert_sql
    assert insert_args[0] == user_id
    assert insert_args[1] == Decimal("1000.00")     # balance_usdc
    assert insert_args[2] == Decimal("1050.00")     # equity_usdc
    assert insert_args[3] == Decimal("12.50")       # pnl_today
    assert insert_args[4] == Decimal("48.75")       # pnl_7d
    assert insert_args[5] == 2                       # open_positions


def test_write_snapshot_skips_when_user_has_no_wallet():
    """Unknown user (no wallet row) -> returns None, no INSERT attempted."""
    user_id = uuid4()
    pool, _conn, fetchrow_mock, fetchval_mock = _make_pool(metrics_row=None)

    with patch.object(portfolio_snapshots, "get_pool", return_value=pool):
        result = _run(portfolio_snapshots.write_snapshot(user_id))

    assert result is None
    fetchrow_mock.assert_awaited_once()
    fetchval_mock.assert_not_awaited()


def test_write_snapshot_swallows_db_errors():
    """Best-effort contract: any DB error returns None instead of raising.
    Trade-close path depends on this — a snapshot outage must not corrupt
    realised-close semantics.
    """
    user_id = uuid4()

    def _raising_get_pool():
        raise RuntimeError("pool acquire failed")

    with patch.object(portfolio_snapshots, "get_pool", side_effect=_raising_get_pool):
        result = _run(portfolio_snapshots.write_snapshot(user_id))

    assert result is None


# ---------------------------------------------------------------------------
# snapshot_active_users: iterates and writes per row.
# ---------------------------------------------------------------------------


def test_snapshot_active_users_writes_one_per_active_user():
    """Scheduler tick path: pulls active users, calls write_snapshot for each."""
    user_ids = [uuid4(), uuid4(), uuid4()]
    rows = [{"user_id": uid} for uid in user_ids]

    pool = MagicMock()
    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=rows)
    acq = MagicMock()
    acq.__aenter__ = AsyncMock(return_value=conn)
    acq.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=acq)

    write_mock = AsyncMock(side_effect=[uuid4(), None, uuid4()])

    with patch.object(portfolio_snapshots, "get_pool", return_value=pool), \
         patch.object(portfolio_snapshots, "write_snapshot", write_mock):
        written = _run(portfolio_snapshots.snapshot_active_users())

    assert write_mock.await_count == 3
    # write_snapshot returned None for index 1 -> only 2 counted as written.
    assert written == 2


def test_snapshot_active_users_swallows_top_level_errors():
    """Scheduler must not crash if the discovery query itself fails."""
    def _raising_get_pool():
        raise RuntimeError("transient")

    with patch.object(portfolio_snapshots, "get_pool", side_effect=_raising_get_pool):
        written = _run(portfolio_snapshots.snapshot_active_users())

    assert written == 0


# ---------------------------------------------------------------------------
# paper.close_position integration: snapshot fires after the close txn.
# ---------------------------------------------------------------------------


def test_paper_close_position_invokes_snapshot_writer():
    """End-to-end wiring proof: after the close transaction commits, the
    snapshot writer is called with the position's user_id. This is the
    primary acceptance criterion of WARP-52.
    """
    pos_id = uuid4()
    user_id = uuid4()
    position = {
        "id": pos_id,
        "user_id": user_id,
        "size_usdc": Decimal("100"),
        "entry_price": 0.40,
        "side": "yes",
    }

    # Fake transactional pool — UPDATE returns pos_id (success), ledger
    # credit is a no-op so we only need the conn.execute / fetchval surface.
    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value=pos_id)
    conn.fetchrow = AsyncMock(return_value=None)
    conn.execute = AsyncMock(return_value=None)
    txn = MagicMock()
    txn.__aenter__ = AsyncMock(return_value=None)
    txn.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=txn)
    pool = MagicMock()
    acq = MagicMock()
    acq.__aenter__ = AsyncMock(return_value=conn)
    acq.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=acq)

    snapshot_mock = AsyncMock(return_value=uuid4())
    audit_mock = AsyncMock(return_value=None)

    with patch.object(paper_exec, "get_pool", return_value=pool), \
         patch.object(paper_exec.portfolio_snapshots, "write_snapshot", snapshot_mock), \
         patch.object(paper_exec.audit, "write", audit_mock):
        result = _run(paper_exec.close_position(
            position=position, exit_price=0.50, exit_reason="tp_hit",
        ))

    # Position closed successfully (PnL = 100 * (0.50-0.40)/0.40 = +25).
    assert result["exit_reason"] == "tp_hit"
    # Snapshot writer fired with the closer's user_id — the critical wiring.
    snapshot_mock.assert_awaited_once_with(user_id)


def test_paper_close_skip_already_closed_does_not_snapshot():
    """If the UPDATE is a no-op (position already closed), no snapshot is
    written — there is no new realised PnL to push.
    """
    pos_id = uuid4()
    user_id = uuid4()
    position = {
        "id": pos_id,
        "user_id": user_id,
        "size_usdc": Decimal("100"),
        "entry_price": 0.40,
        "side": "yes",
    }

    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value=None)  # UPDATE matched zero rows
    conn.fetchrow = AsyncMock(return_value=None)
    conn.execute = AsyncMock(return_value=None)
    txn = MagicMock()
    txn.__aenter__ = AsyncMock(return_value=None)
    txn.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=txn)
    pool = MagicMock()
    acq = MagicMock()
    acq.__aenter__ = AsyncMock(return_value=conn)
    acq.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=acq)

    snapshot_mock = AsyncMock(return_value=uuid4())
    audit_mock = AsyncMock(return_value=None)

    with patch.object(paper_exec, "get_pool", return_value=pool), \
         patch.object(paper_exec.portfolio_snapshots, "write_snapshot", snapshot_mock), \
         patch.object(paper_exec.audit, "write", audit_mock):
        result = _run(paper_exec.close_position(
            position=position, exit_price=0.50, exit_reason="tp_hit",
        ))

    assert result["exit_reason"] == "already_closed"
    snapshot_mock.assert_not_awaited()
