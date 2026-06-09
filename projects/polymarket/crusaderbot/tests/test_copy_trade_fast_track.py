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
from projects.polymarket.crusaderbot.services import heisenberg_buffer as buf
from projects.polymarket.crusaderbot.services.heisenberg_trades import RealtimeTrade


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


def _make_pool():
    """Pool whose conn serves the watermark UPDATE (the only DB hop left —
    the trade read now comes from the in-memory buffer)."""
    conn = MagicMock()
    conn.execute = AsyncMock(return_value="UPDATE 1")
    pool = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=cm)
    return pool, conn


def _rt(wallet, trade_time, raw, *, cid="c1", side="YES", size=10.0):
    return RealtimeTrade(
        wallet=wallet, condition_id=cid, side=side, price=0.5,
        size_usdc=size, trade_time=trade_time, raw=raw,
    )


def _seed(*trades):
    buf.clear()
    if trades:
        buf.record_trades(list(trades))


def _fake_cfg(**overrides) -> SimpleNamespace:
    """Minimal settings stub the consumer's gate checks read from."""
    base = dict(
        HEISENBERG_FAST_TRACK_ENABLED=True,
        HEISENBERG_REALTIME_TRADES_ENABLED=True,
        HEISENBERG_API_TOKEN="x",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# Gate tests — kill_switch / globally_disabled / no tasks
# ---------------------------------------------------------------------------


def test_skip_when_kill_switch_active():
    with (
        patch.object(ft, "get_settings", return_value=_fake_cfg()),
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
        patch.object(ft, "get_settings", return_value=_fake_cfg()),
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
        patch.object(ft, "get_settings", return_value=_fake_cfg()),
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
    """One task, two fresh buffer trades → two _process_one dispatches +
    watermark UPDATE to the latest trade_time."""
    now = datetime.now(timezone.utc)
    task = _make_task(last_seen=now - timedelta(minutes=10))
    t1 = now - timedelta(minutes=5)
    t2 = now - timedelta(minutes=4)
    _seed(
        _rt("0xabc", t1, {"id": "tx1", "side": "BUY", "outcome": "Yes"}),
        _rt("0xabc", t2, {"id": "tx2", "side": "SELL", "outcome": "No"}),
    )
    pool, conn = _make_pool()
    process_one = AsyncMock()

    with (
        patch.object(ft, "get_settings", return_value=_fake_cfg()),
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
    # Watermark UPDATE was issued with the latest trade_time (t2).
    update_calls = [
        c for c in conn.execute.await_args_list
        if "UPDATE copy_trade_tasks" in c.args[0]
    ]
    assert len(update_calls) == 1
    assert update_calls[0].args[1] == task.id
    assert update_calls[0].args[2] == t2


def test_skips_trades_older_than_watermark():
    """A task with watermark 5:35 must NOT dispatch the 5:30 trade."""
    now = datetime.now(timezone.utc)
    task = _make_task(last_seen=now - timedelta(minutes=5))
    t_old = now - timedelta(minutes=10)  # older than the watermark
    t_new = now - timedelta(minutes=2)   # newer
    _seed(
        _rt("0xabc", t_old, {"id": "tx_old"}),
        _rt("0xabc", t_new, {"id": "tx_new"}),
    )
    pool, conn = _make_pool()
    process_one = AsyncMock()

    with (
        patch.object(ft, "get_settings", return_value=_fake_cfg()),
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
    trade = _rt("0xabc", now - timedelta(seconds=60), {"id": "tx_recent"})
    pool, conn = _make_pool()
    process_one = AsyncMock()
    # Spy on the buffer read so we can assert the NULL-watermark fallback cutoff.
    read_spy = MagicMock(return_value=[trade])

    with (
        patch.object(ft, "get_settings", return_value=_fake_cfg()),
        patch.object(ft._monitor, "kill_switch_is_active",
                     new=AsyncMock(return_value=False)),
        patch.object(ft._monitor, "_is_globally_disabled",
                     new=AsyncMock(return_value=False)),
        patch.object(ft, "list_active_tasks",
                     new=AsyncMock(return_value=[task])),
        patch.object(ft._monitor, "_process_one", new=process_one),
        patch.object(ft.heisenberg_buffer, "trades_for_wallet", read_spy),
        patch.object(ft, "get_pool", return_value=pool),
    ):
        scanned, dispatched = asyncio.run(ft.run_once())

    assert (scanned, dispatched) == (1, 1)
    # Buffer was read with since = NOW() - 300s; assert the cutoff is within a
    # 5-second jitter window from the expected fallback value.
    cutoff_arg = read_spy.call_args.args[1]
    expected = now - timedelta(seconds=ft._INITIAL_LOOKBACK_SEC)
    assert abs((cutoff_arg - expected).total_seconds()) < 5


def test_failure_halts_task_and_does_not_advance_watermark():
    """Critical correctness pin (CodeRabbit review). If _process_one raises
    for the FIRST eligible trade, the watermark must NOT advance — neither
    past the failed trade nor past any subsequent trade in the same tick —
    so the failure gets retried on the next tick (idempotency dedupes any
    earlier successes that happen to fall before the failed trade)."""
    now = datetime.now(timezone.utc)
    task = _make_task(last_seen=now - timedelta(minutes=10))
    t1 = now - timedelta(minutes=5)
    t2 = now - timedelta(minutes=4)
    _seed(_rt("0xabc", t1, {"id": "tx1"}), _rt("0xabc", t2, {"id": "tx2"}))
    pool, conn = _make_pool()
    process_one = AsyncMock(side_effect=[RuntimeError("kaboom on first"), None])

    with (
        patch.object(ft, "get_settings", return_value=_fake_cfg()),
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

    # Only the failed trade was attempted; loop halted before t2.
    assert scanned == 1
    assert dispatched == 0
    assert process_one.await_count == 1
    # CRITICAL: watermark UPDATE must NOT have been issued — latest_seen
    # never advanced past task_cutoff because no trade succeeded.
    update_calls = [
        c for c in conn.execute.await_args_list
        if "UPDATE copy_trade_tasks" in c.args[0]
    ]
    assert update_calls == [], "watermark must not advance on failure"


def test_success_then_failure_advances_only_to_success():
    """If first trade succeeds but second trade fails, watermark advances
    to the success but stops there — the failed trade gets retried next tick."""
    now = datetime.now(timezone.utc)
    task = _make_task(last_seen=now - timedelta(minutes=10))
    t1_ok = now - timedelta(minutes=5)
    t2_fail = now - timedelta(minutes=4)
    _seed(_rt("0xabc", t1_ok, {"id": "tx1"}), _rt("0xabc", t2_fail, {"id": "tx2"}))
    pool, conn = _make_pool()
    process_one = AsyncMock(side_effect=[None, RuntimeError("kaboom on second")])

    with (
        patch.object(ft, "get_settings", return_value=_fake_cfg()),
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
    assert dispatched == 1
    update_calls = [
        c for c in conn.execute.await_args_list
        if "UPDATE copy_trade_tasks" in c.args[0]
    ]
    # Watermark moved to t1 (success) but not t2 (failure).
    assert len(update_calls) == 1
    assert update_calls[0].args[2] == t1_ok


def test_process_one_failure_doesnt_break_other_tasks():
    """If _process_one raises for one task, the consumer must continue and
    still dispatch trades for the other task."""
    task_a = _make_task(wallet="0xa", last_seen=None)
    task_b = _make_task(wallet="0xb", last_seen=None)

    now = datetime.now(timezone.utc)
    _seed(
        _rt("0xa", now - timedelta(seconds=30), {"id": "tx_a"}),
        _rt("0xb", now - timedelta(seconds=30), {"id": "tx_b"}),
    )
    pool, conn = _make_pool()

    process_one = AsyncMock(
        side_effect=[RuntimeError("kaboom on a"), None],
    )

    with (
        patch.object(ft, "get_settings", return_value=_fake_cfg()),
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


def test_buffer_read_failure_returns_zero_doesnt_raise():
    """A failure in the buffer read must NOT bubble out — fail-soft to (0, 0)."""
    task = _make_task(last_seen=None)
    pool, _conn = _make_pool()

    with (
        patch.object(ft, "get_settings", return_value=_fake_cfg()),
        patch.object(ft._monitor, "kill_switch_is_active",
                     new=AsyncMock(return_value=False)),
        patch.object(ft._monitor, "_is_globally_disabled",
                     new=AsyncMock(return_value=False)),
        patch.object(ft, "list_active_tasks",
                     new=AsyncMock(return_value=[task])),
        patch.object(ft.heisenberg_buffer, "trades_for_wallet",
                     MagicMock(side_effect=RuntimeError("buffer boom"))),
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


# ---------------------------------------------------------------------------
# Gemini review pin — wallet case normalisation
# ---------------------------------------------------------------------------


def test_buffer_query_lowercases_wallet():
    """task.wallet_address may be checksummed (mixed case) but the agent 556
    buffer stores all-lowercase hex. The consumer MUST lowercase before the
    buffer read, otherwise it silently returns 0 trades."""
    task = _make_task(
        wallet="0xAaBbCcDdEeFf112233445566778899AaBbCcDdEe",  # checksummed
        last_seen=None,
    )
    pool, _conn = _make_pool()
    read_spy = MagicMock(return_value=[])

    with (
        patch.object(ft, "get_settings", return_value=_fake_cfg()),
        patch.object(ft._monitor, "kill_switch_is_active",
                     new=AsyncMock(return_value=False)),
        patch.object(ft._monitor, "_is_globally_disabled",
                     new=AsyncMock(return_value=False)),
        patch.object(ft, "list_active_tasks",
                     new=AsyncMock(return_value=[task])),
        patch.object(ft._monitor, "_process_one", new=AsyncMock()),
        patch.object(ft.heisenberg_buffer, "trades_for_wallet", read_spy),
        patch.object(ft, "get_pool", return_value=pool),
    ):
        asyncio.run(ft.run_once())

    # The buffer read wallet arg must be lowercased.
    wallet_arg = read_spy.call_args.args[0]
    assert wallet_arg == "0xaabbccddeeff112233445566778899aabbccddee"
    assert wallet_arg != task.wallet_address  # explicitly different from original


# ---------------------------------------------------------------------------
# Defence-in-depth gate tests — fast-track / producer / token flags
# ---------------------------------------------------------------------------


def test_skip_when_fast_track_flag_off():
    """If HEISENBERG_FAST_TRACK_ENABLED is False, run_once must return (0,0)
    before any other check (defends staged rollouts where the scheduler
    didn't see the latest flag flip)."""
    with patch.object(ft, "get_settings",
                      return_value=_fake_cfg(HEISENBERG_FAST_TRACK_ENABLED=False)):
        scanned, dispatched = asyncio.run(ft.run_once())
    assert (scanned, dispatched) == (0, 0)


def test_skip_when_realtime_producer_disabled():
    """If HEISENBERG_REALTIME_TRADES_ENABLED is False, the buffer is stale.
    Consumer must skip rather than dispatch old trades."""
    with patch.object(ft, "get_settings",
                      return_value=_fake_cfg(HEISENBERG_REALTIME_TRADES_ENABLED=False)):
        scanned, dispatched = asyncio.run(ft.run_once())
    assert (scanned, dispatched) == (0, 0)


def test_skip_when_heisenberg_token_missing():
    """If HEISENBERG_API_TOKEN is empty/whitespace, the producer cannot
    populate the buffer. Consumer skips."""
    with patch.object(ft, "get_settings",
                      return_value=_fake_cfg(HEISENBERG_API_TOKEN="   ")):
        scanned, dispatched = asyncio.run(ft.run_once())
    assert (scanned, dispatched) == (0, 0)
