"""Hermetic tests for the R12e auto-redeem services.

No DB, no Polygon, no Polymarket, no Telegram. Patches:
  * ``redeem_router.claim_queue_row`` / ``mark_done`` /
    ``release_back_to_pending`` so worker logic can be exercised without
    a live ``redeem_queue`` table.
  * ``redeem_router.settle_winning_position`` so success / first-fail-
    then-ok / always-fail paths are deterministic.
  * ``polygon.gas_price_gwei`` for gas-spike branches.
  * ``alerts._dispatch`` so operator-alert calls are captured rather
    than dispatched.
  * ``asyncio.sleep`` is monkey-patched to a no-op so the 30s instant
    retry does not slow the test suite.

Coverage targets (R12e DONE CRITERIA):
  - AUTO_REDEEM_ENABLED guard short-circuits every entry point
  - Instant: success path
  - Instant: gas spike defers to hourly (no settle, no failure increment)
  - Instant: gas read failure also defers
  - Instant: paper position skips gas check entirely
  - Instant: first attempt fails, retry succeeds → done
  - Instant: both attempts fail → release with failure_count++
  - Hourly: success path
  - Hourly: failure increments failure_count, no operator alert below threshold
  - Hourly: failure_count >= 2 pages the operator
  - Hourly: per-row exception isolated — does not poison the batch
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from projects.polymarket.crusaderbot.services.redeem import (
    hourly_worker, instant_worker, redeem_router,
)


def _run(coro):
    return asyncio.run(coro)


def _make_claim(*, mode: str = "paper", failure_count: int = 0) -> dict[str, Any]:
    return {
        "queue_id": uuid4(),
        "id": uuid4(),
        "user_id": uuid4(),
        "market_id": "mkt-1",
        "side": "yes",
        "mode": mode,
        "status": "open",
        "size_usdc": 100.0,
        "entry_price": 0.40,
        "telegram_user_id": 123,
        "auto_redeem_mode": "instant" if mode == "paper" else "hourly",
        "failure_count": failure_count,
        "market_condition_id": "0xabc",
        "outcome_index": 0,
    }


# ---------------- Activation guard ----------------

def test_instant_worker_short_circuits_when_disabled():
    with patch.object(instant_worker, "get_settings") as gs, \
         patch.object(redeem_router, "claim_queue_row",
                      new=AsyncMock()) as claim:
        gs.return_value.AUTO_REDEEM_ENABLED = False
        _run(instant_worker.try_process(uuid4()))
        claim.assert_not_called()


def test_hourly_worker_short_circuits_when_disabled():
    with patch.object(hourly_worker, "get_settings") as gs, \
         patch.object(hourly_worker, "get_pool") as get_pool:
        gs.return_value.AUTO_REDEEM_ENABLED = False
        _run(hourly_worker.run_once())
        get_pool.assert_not_called()


def test_router_detect_short_circuits_when_disabled():
    with patch.object(redeem_router, "get_settings") as gs, \
         patch.object(redeem_router, "get_pool") as get_pool:
        gs.return_value.AUTO_REDEEM_ENABLED = False
        _run(redeem_router.detect_resolutions())
        get_pool.assert_not_called()


# ---------------- Instant worker ----------------

def test_instant_paper_success_no_gas_check():
    """Paper positions never hit the gas RPC."""
    claim = _make_claim(mode="paper")
    with patch.object(instant_worker, "get_settings") as gs, \
         patch.object(redeem_router, "claim_queue_row",
                      new=AsyncMock(return_value=claim)), \
         patch.object(redeem_router, "settle_winning_position",
                      new=AsyncMock()) as settle, \
         patch.object(redeem_router, "mark_done",
                      new=AsyncMock()) as done, \
         patch("projects.polymarket.crusaderbot.services.redeem"
               ".instant_worker.polygon.gas_price_gwei",
               new=AsyncMock()) as gas:
        gs.return_value.AUTO_REDEEM_ENABLED = True
        gs.return_value.INSTANT_REDEEM_GAS_GWEI_MAX = 100.0
        _run(instant_worker.try_process(claim["queue_id"]))
        gas.assert_not_called()  # paper bypasses gas
        settle.assert_awaited_once()
        done.assert_awaited_once_with(claim["queue_id"])


def test_instant_live_gas_spike_defers():
    """Live + gas above threshold → release without incrementing failure."""
    claim = _make_claim(mode="live")
    with patch.object(instant_worker, "get_settings") as gs, \
         patch.object(redeem_router, "claim_queue_row",
                      new=AsyncMock(return_value=claim)), \
         patch.object(redeem_router, "settle_winning_position",
                      new=AsyncMock()) as settle, \
         patch.object(redeem_router, "release_back_to_pending",
                      new=AsyncMock()) as release, \
         patch("projects.polymarket.crusaderbot.services.redeem"
               ".instant_worker.polygon.gas_price_gwei",
               new=AsyncMock(return_value=250.0)):
        gs.return_value.AUTO_REDEEM_ENABLED = True
        gs.return_value.INSTANT_REDEEM_GAS_GWEI_MAX = 100.0
        _run(instant_worker.try_process(claim["queue_id"]))
        settle.assert_not_called()
        release.assert_awaited_once_with(
            claim["queue_id"], increment_failure=False,
        )


def test_instant_live_gas_read_failure_defers():
    """Gas RPC failure → defer (treat as spike), no failure increment."""
    claim = _make_claim(mode="live")
    with patch.object(instant_worker, "get_settings") as gs, \
         patch.object(redeem_router, "claim_queue_row",
                      new=AsyncMock(return_value=claim)), \
         patch.object(redeem_router, "settle_winning_position",
                      new=AsyncMock()) as settle, \
         patch.object(redeem_router, "release_back_to_pending",
                      new=AsyncMock()) as release, \
         patch("projects.polymarket.crusaderbot.services.redeem"
               ".instant_worker.polygon.gas_price_gwei",
               new=AsyncMock(side_effect=RuntimeError("rpc down"))):
        gs.return_value.AUTO_REDEEM_ENABLED = True
        gs.return_value.INSTANT_REDEEM_GAS_GWEI_MAX = 100.0
        _run(instant_worker.try_process(claim["queue_id"]))
        settle.assert_not_called()
        release.assert_awaited_once_with(
            claim["queue_id"], increment_failure=False,
        )


def test_instant_retry_succeeds_on_second_attempt():
    """First settle raises, second succeeds → done, no release."""
    claim = _make_claim(mode="paper")
    settle_mock = AsyncMock(side_effect=[RuntimeError("flaky"), None])
    sleep_mock = AsyncMock()
    with patch.object(instant_worker, "get_settings") as gs, \
         patch.object(redeem_router, "claim_queue_row",
                      new=AsyncMock(return_value=claim)), \
         patch.object(redeem_router, "settle_winning_position",
                      new=settle_mock), \
         patch.object(redeem_router, "mark_done",
                      new=AsyncMock()) as done, \
         patch.object(redeem_router, "release_back_to_pending",
                      new=AsyncMock()) as release, \
         patch("projects.polymarket.crusaderbot.services.redeem"
               ".instant_worker.asyncio.sleep", new=sleep_mock):
        gs.return_value.AUTO_REDEEM_ENABLED = True
        gs.return_value.INSTANT_REDEEM_GAS_GWEI_MAX = 100.0
        _run(instant_worker.try_process(claim["queue_id"]))
        assert settle_mock.await_count == 2
        sleep_mock.assert_awaited_once_with(
            instant_worker.INSTANT_RETRY_DELAY_SECONDS,
        )
        done.assert_awaited_once()
        release.assert_not_called()


def test_instant_both_attempts_fail_defers_to_hourly():
    """Both settle attempts raise → release with failure_count++."""
    claim = _make_claim(mode="paper")
    settle_mock = AsyncMock(side_effect=RuntimeError("dead"))
    with patch.object(instant_worker, "get_settings") as gs, \
         patch.object(redeem_router, "claim_queue_row",
                      new=AsyncMock(return_value=claim)), \
         patch.object(redeem_router, "settle_winning_position",
                      new=settle_mock), \
         patch.object(redeem_router, "mark_done",
                      new=AsyncMock()) as done, \
         patch.object(redeem_router, "release_back_to_pending",
                      new=AsyncMock()) as release, \
         patch("projects.polymarket.crusaderbot.services.redeem"
               ".instant_worker.asyncio.sleep", new=AsyncMock()):
        gs.return_value.AUTO_REDEEM_ENABLED = True
        gs.return_value.INSTANT_REDEEM_GAS_GWEI_MAX = 100.0
        _run(instant_worker.try_process(claim["queue_id"]))
        assert settle_mock.await_count == 2
        done.assert_not_called()
        release.assert_awaited_once()
        kwargs = release.await_args.kwargs
        assert kwargs["increment_failure"] is True


def test_instant_claim_returns_none_no_settle():
    """Race: row already claimed by hourly worker → return cleanly."""
    with patch.object(instant_worker, "get_settings") as gs, \
         patch.object(redeem_router, "claim_queue_row",
                      new=AsyncMock(return_value=None)), \
         patch.object(redeem_router, "settle_winning_position",
                      new=AsyncMock()) as settle:
        gs.return_value.AUTO_REDEEM_ENABLED = True
        _run(instant_worker.try_process(uuid4()))
        settle.assert_not_called()


# ---------------- Hourly worker ----------------

def _stub_pool_returning(rows: list[dict]):
    """Build a context-manager-shaped fake asyncpg pool returning ``rows``."""
    class _Conn:
        async def fetch(self, *a, **kw):
            return rows
    class _Acquire:
        async def __aenter__(self):
            return _Conn()
        async def __aexit__(self, *a):
            return None
    class _Pool:
        def acquire(self):
            return _Acquire()
    return _Pool()


def test_hourly_drains_pending_rows_success():
    rows = [{"id": uuid4()}, {"id": uuid4()}]
    claim = _make_claim()
    with patch.object(hourly_worker, "get_settings") as gs, \
         patch.object(hourly_worker, "get_pool",
                      return_value=_stub_pool_returning(rows)), \
         patch.object(redeem_router, "reap_stale_processing",
                      new=AsyncMock(return_value=0)), \
         patch.object(redeem_router, "claim_queue_row",
                      new=AsyncMock(return_value=claim)), \
         patch.object(redeem_router, "settle_winning_position",
                      new=AsyncMock()) as settle, \
         patch.object(redeem_router, "mark_done",
                      new=AsyncMock()) as done:
        gs.return_value.AUTO_REDEEM_ENABLED = True
        _run(hourly_worker.run_once())
        assert settle.await_count == 2
        assert done.await_count == 2


def test_hourly_reaps_stale_processing_before_drain():
    """Stale processing rows are released back to pending each tick."""
    rows = [{"id": uuid4()}]
    claim = _make_claim()
    with patch.object(hourly_worker, "get_settings") as gs, \
         patch.object(hourly_worker, "get_pool",
                      return_value=_stub_pool_returning(rows)), \
         patch.object(redeem_router, "reap_stale_processing",
                      new=AsyncMock(return_value=3)) as reap, \
         patch.object(redeem_router, "claim_queue_row",
                      new=AsyncMock(return_value=claim)), \
         patch.object(redeem_router, "settle_winning_position",
                      new=AsyncMock()), \
         patch.object(redeem_router, "mark_done",
                      new=AsyncMock()):
        gs.return_value.AUTO_REDEEM_ENABLED = True
        _run(hourly_worker.run_once())
        reap.assert_awaited_once()


def test_hourly_reap_failure_does_not_block_drain():
    """Reaper failure is logged and the drain still runs."""
    rows = [{"id": uuid4()}]
    claim = _make_claim()
    with patch.object(hourly_worker, "get_settings") as gs, \
         patch.object(hourly_worker, "get_pool",
                      return_value=_stub_pool_returning(rows)), \
         patch.object(redeem_router, "reap_stale_processing",
                      new=AsyncMock(side_effect=RuntimeError("db down"))), \
         patch.object(redeem_router, "claim_queue_row",
                      new=AsyncMock(return_value=claim)), \
         patch.object(redeem_router, "settle_winning_position",
                      new=AsyncMock()) as settle, \
         patch.object(redeem_router, "mark_done",
                      new=AsyncMock()) as done:
        gs.return_value.AUTO_REDEEM_ENABLED = True
        _run(hourly_worker.run_once())
        settle.assert_awaited_once()
        done.assert_awaited_once()


def test_hourly_failure_increments_no_alert_below_threshold():
    rows = [{"id": uuid4()}]
    claim = _make_claim()
    with patch.object(hourly_worker, "get_settings") as gs, \
         patch.object(hourly_worker, "get_pool",
                      return_value=_stub_pool_returning(rows)), \
         patch.object(redeem_router, "reap_stale_processing",
                      new=AsyncMock(return_value=0)), \
         patch.object(redeem_router, "claim_queue_row",
                      new=AsyncMock(return_value=claim)), \
         patch.object(redeem_router, "settle_winning_position",
                      new=AsyncMock(side_effect=RuntimeError("nope"))), \
         patch.object(redeem_router, "release_back_to_pending",
                      new=AsyncMock(return_value=1)), \
         patch.object(hourly_worker.alerts, "_dispatch",
                      new=AsyncMock()) as dispatch:
        gs.return_value.AUTO_REDEEM_ENABLED = True
        _run(hourly_worker.run_once())
        dispatch.assert_not_called()


def test_hourly_failure_at_threshold_pages_operator():
    rows = [{"id": uuid4()}]
    claim = _make_claim()
    with patch.object(hourly_worker, "get_settings") as gs, \
         patch.object(hourly_worker, "get_pool",
                      return_value=_stub_pool_returning(rows)), \
         patch.object(redeem_router, "reap_stale_processing",
                      new=AsyncMock(return_value=0)), \
         patch.object(redeem_router, "claim_queue_row",
                      new=AsyncMock(return_value=claim)), \
         patch.object(redeem_router, "settle_winning_position",
                      new=AsyncMock(side_effect=RuntimeError("nope"))), \
         patch.object(redeem_router, "release_back_to_pending",
                      new=AsyncMock(return_value=2)), \
         patch.object(hourly_worker.alerts, "_dispatch",
                      new=AsyncMock()) as dispatch:
        gs.return_value.AUTO_REDEEM_ENABLED = True
        _run(hourly_worker.run_once())
        dispatch.assert_awaited_once()
        args, _ = dispatch.await_args
        assert args[0] == "redeem_failed_persistent"


def test_hourly_per_row_exception_isolated():
    """One leaking row must not stop the rest of the batch."""
    rows = [{"id": uuid4()}, {"id": uuid4()}]
    # First claim raises (defensive net), second returns a valid claim.
    claim = _make_claim()
    claim_seq = AsyncMock(side_effect=[RuntimeError("leak"), claim])
    with patch.object(hourly_worker, "get_settings") as gs, \
         patch.object(hourly_worker, "get_pool",
                      return_value=_stub_pool_returning(rows)), \
         patch.object(redeem_router, "reap_stale_processing",
                      new=AsyncMock(return_value=0)), \
         patch.object(redeem_router, "claim_queue_row", new=claim_seq), \
         patch.object(redeem_router, "settle_winning_position",
                      new=AsyncMock()) as settle, \
         patch.object(redeem_router, "mark_done",
                      new=AsyncMock()) as done:
        gs.return_value.AUTO_REDEEM_ENABLED = True
        _run(hourly_worker.run_once())
        # Second row still settled despite first row leaking.
        settle.assert_awaited_once()
        done.assert_awaited_once()


# ---------------- Hourly: empty queue is a no-op ----------------

def test_hourly_empty_queue_noop():
    with patch.object(hourly_worker, "get_settings") as gs, \
         patch.object(hourly_worker, "get_pool",
                      return_value=_stub_pool_returning([])), \
         patch.object(redeem_router, "reap_stale_processing",
                      new=AsyncMock(return_value=0)), \
         patch.object(redeem_router, "claim_queue_row",
                      new=AsyncMock()) as claim:
        gs.return_value.AUTO_REDEEM_ENABLED = True
        _run(hourly_worker.run_once())
        claim.assert_not_called()
