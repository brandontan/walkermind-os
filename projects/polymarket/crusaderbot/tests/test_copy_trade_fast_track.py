"""Hermetic tests for services/copy_trade/realtime_fast_track.py.

No DB, no HTTP, no scheduler — buffer fetch, monitor._process_one,
watermark UPDATE, and the kill_switch / globally-disabled guards are
all patched at module boundary.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from projects.polymarket.crusaderbot.services.copy_trade import (
    realtime_fast_track as ft,
)


def _make_task(
    *,
    wallet: str = "0xabc",
    user_id: UUID | None = None,
    last_seen: datetime | None = None,
) -> SimpleNamespace:
    """Return an object that quacks like CopyTradeTask for the consumer's
    purposes (.id, .user_id, .wallet_address, .last_realtime_seen_at)."""
    return SimpleNamespace(
        id=uuid4(),
        user_id=user_id or uuid4(),
        wallet_address=wallet,
        last_realtime_seen_at=last_seen,
    )


def _make_pool_with_rows(rows):
    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=rows)
    conn.execute = AsyncMock(return_value="UPDATE 1")
    pool = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=cm)
    return pool, conn


# ---------------------------------------------------------------------------
# Gate tests — kill_switch / globally_disabled / no tasks
# ---------------------------------------------------------------------------


def test_skip_when_kill_switch_active():
    with (
        patch.object(ft._monitor, "kill_switch_is_active",
                     new=AsyncMock(return_value=True)),
        patch.object(ft._monitor, "_is_globally_disabled",
                     new=AsyncMock(return_value=False)),
        patch.object(ft, "list_active_tasks",
                     new=AsyncMock(return_value=[_make_task()])),
    ):
        scanned, dispatched = asyncio.run(ft.run_once())
    assert (scanned, dispatched) == (0, 0)


def test_skip_when_globally_disabled():
    with (
        patch.object(ft._monitor, "kill_switch_is_active",
                     new=AsyncMock(return_value=False)),
        patch.object(ft._monitor, "_is_globally_disabled",
                     new=AsyncMock(return_value=True)),
        patch.object(ft, "list_active_tasks",
                     new=AsyncMock(return_value=[_make_task()])),
    ):
        scanned, dispatched = asyncio.run(ft.run_once())
    assert (scanned, dispatched) == (0, 0)


def test_zero_when_no_active_tasks():
    with (
        patch.object(ft._monitor, "kill_switch_is_active",
                     new=AsyncMock(return_value=False)),
        patch.object(ft._monitor, "_is_globally_disabled",
                     new=AsyncMock(return_value=False)),
        patch.object(ft, "list_active_tasks",
                     new=AsyncMock(return_value=[])),
    ):
        scanned, dispatched = asyncio.run(ft.run_once())
    assert (scanned, dispatched) == (0, 0)


# ---------------------------------------------------------------------------
# Buffer fetch + dispatch
# ---------------------------------------------------------------------------


def test_dispatches_each_fresh_trade_and_bumps_watermark():
    """One task, two fresh buffer rows → two _process_one dispatches +
    watermark UPDATE to the latest trade_time."""
    task = _make_task(last_seen=datetime(2026, 5, 30, 5, 30, tzinfo=timezone.utc))
    rows = [
        {
            "trade_time": datetime(2026, 5, 30, 5, 35, tzinfo=timezone.utc),
            "raw": {"id": "tx1", "side": "BUY", "outcome": "Yes"},
        },
        {
            "trade_time": datetime(2026, 5, 30, 5, 36, tzinfo=timezone.utc),
            "raw": {"id": "tx2", "side": "SELL", "outcome": "No"},
        },
    ]
    pool, conn = _make_pool_with_rows(rows)
    process_one = AsyncMock()

    with (
        patch.object(ft._monitor, "kill_switch_is_active",
                     new=AsyncMock(return_value=False)),
        patch.object(ft._monitor, "_is_globally_disabled",
                     new=AsyncMock(return_value=False)),
        patch.object(ft, "list_active_tasks",
                     new=AsyncMock(return_value=[task])),
        patch.object(ft._monitor, "_process_one", new=process_one),
        patch.object(ft, "get_pool", return_value=pool),
    ):
        scanned, dispatched = asyncio.run(ft.run_once())

    assert scanned == 2
    assert dispatched == 2
    assert process_one.await_count == 2
    # Watermark UPDATE was issued with the latest trade_time (5:36).
    update_calls = [
        c for c in conn.execute.await_args_list
        if "UPDATE copy_trade_tasks" in c.args[0]
    ]
    assert len(update_calls) == 1
    assert update_calls[0].args[1] == task.id
    assert update_calls[0].args[2] == datetime(2026, 5, 30, 5, 36, tzinfo=timezone.utc)


def test_skips_trades_older_than_watermark():
    """A task with watermark 5:35 must NOT dispatch the 5:30 trade."""
    task = _make_task(last_seen=datetime(2026, 5, 30, 5, 35, tzinfo=timezone.utc))
    rows = [
        # Older than the watermark.
        {
            "trade_time": datetime(2026, 5, 30, 5, 30, tzinfo=timezone.utc),
            "raw": {"id": "tx_old"},
        },
        # Newer.
        {
            "trade_time": datetime(2026, 5, 30, 5, 40, tzinfo=timezone.utc),
            "raw": {"id": "tx_new"},
        },
    ]
    pool, conn = _make_pool_with_rows(rows)
    process_one = AsyncMock()

    with (
        patch.object(ft._monitor, "kill_switch_is_active",
                     new=AsyncMock(return_value=False)),
        patch.object(ft._monitor, "_is_globally_disabled",
                     new=AsyncMock(return_value=False)),
        patch.object(ft, "list_active_tasks",
                     new=AsyncMock(return_value=[task])),
        patch.object(ft._monitor, "_process_one", new=process_one),
        patch.object(ft, "get_pool", return_value=pool),
    ):
        scanned, dispatched = asyncio.run(ft.run_once())

    assert scanned == 1
    assert dispatched == 1
    assert process_one.await_args.args[1]["id"] == "tx_new"


def test_null_watermark_uses_fallback_lookback():
    """A task with NULL watermark should look back _INITIAL_LOOKBACK_SEC
    (default 300s = 5min) rather than from epoch."""
    task = _make_task(last_seen=None)  # never run

    now = datetime.now(timezone.utc)
    # One trade within window, one outside.
    row_in = {
        "trade_time": now - timedelta(seconds=60),
        "raw": {"id": "tx_recent"},
    }
    # Buffer fetch SQL filters server-side via the cutoff so an "outside"
    # row would not actually arrive — sim the in-window row only.
    pool, conn = _make_pool_with_rows([row_in])
    process_one = AsyncMock()

    with (
        patch.object(ft._monitor, "kill_switch_is_active",
                     new=AsyncMock(return_value=False)),
        patch.object(ft._monitor, "_is_globally_disabled",
                     new=AsyncMock(return_value=False)),
        patch.object(ft, "list_active_tasks",
                     new=AsyncMock(return_value=[task])),
        patch.object(ft._monitor, "_process_one", new=process_one),
        patch.object(ft, "get_pool", return_value=pool),
    ):
        scanned, dispatched = asyncio.run(ft.run_once())

    assert (scanned, dispatched) == (1, 1)
    # The fetch query was called with earliest = NOW() - 300s; assert the
    # cutoff is within a 5-second jitter window from the expected value.
    fetch_args = conn.fetch.await_args
    cutoff_arg = fetch_args.args[2]
    expected = now - timedelta(seconds=ft._INITIAL_LOOKBACK_SEC)
    assert abs((cutoff_arg - expected).total_seconds()) < 5


def test_process_one_failure_doesnt_break_other_tasks():
    """If _process_one raises for one task, the consumer must continue and
    still dispatch trades for the other task."""
    task_a = _make_task(wallet="0xa", last_seen=None)
    task_b = _make_task(wallet="0xb", last_seen=None)

    a_rows = [{
        "trade_time": datetime.now(timezone.utc),
        "raw": {"id": "tx_a"},
    }]
    b_rows = [{
        "trade_time": datetime.now(timezone.utc),
        "raw": {"id": "tx_b"},
    }]

    # Two separate pool fetches — one per wallet.
    fetch_results = [a_rows, b_rows]
    conn = MagicMock()
    conn.fetch = AsyncMock(side_effect=fetch_results)
    conn.execute = AsyncMock(return_value="UPDATE 1")
    pool = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=cm)

    process_one = AsyncMock(
        side_effect=[RuntimeError("kaboom on a"), None],
    )

    with (
        patch.object(ft._monitor, "kill_switch_is_active",
                     new=AsyncMock(return_value=False)),
        patch.object(ft._monitor, "_is_globally_disabled",
                     new=AsyncMock(return_value=False)),
        patch.object(ft, "list_active_tasks",
                     new=AsyncMock(return_value=[task_a, task_b])),
        patch.object(ft._monitor, "_process_one", new=process_one),
        patch.object(ft, "get_pool", return_value=pool),
    ):
        scanned, dispatched = asyncio.run(ft.run_once())

    # Both attempts counted as scanned; only the successful one as dispatched.
    assert scanned == 2
    assert dispatched == 1


def test_buffer_fetch_failure_returns_zero_doesnt_raise():
    """Pool/connection failure on the buffer fetch must NOT bubble out."""
    task = _make_task(last_seen=None)

    pool = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(side_effect=RuntimeError("pool dead"))
    cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=cm)

    with (
        patch.object(ft._monitor, "kill_switch_is_active",
                     new=AsyncMock(return_value=False)),
        patch.object(ft._monitor, "_is_globally_disabled",
                     new=AsyncMock(return_value=False)),
        patch.object(ft, "list_active_tasks",
                     new=AsyncMock(return_value=[task])),
        patch.object(ft, "get_pool", return_value=pool),
    ):
        scanned, dispatched = asyncio.run(ft.run_once())

    assert (scanned, dispatched) == (0, 0)


# ---------------------------------------------------------------------------
# Source pins
# ---------------------------------------------------------------------------


def test_job_id_pinned():
    assert ft.JOB_ID == "copy_trade_realtime_fast_track"


def test_initial_lookback_default():
    assert ft._INITIAL_LOOKBACK_SEC == 300


def test_feature_flag_defaults_off():
    """The fast-track must default OFF until WARP🔹CMD explicitly enables it."""
    from projects.polymarket.crusaderbot.config import Settings
    assert Settings.model_fields["HEISENBERG_FAST_TRACK_ENABLED"].default is False
