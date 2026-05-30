"""Hermetic tests for Heisenberg agent 556 (real-time trades) client + job.

No DB, no HTTP, no scheduler. Pool + httpx + env patched at module boundary.
Covers: client field-aliasing, dt parsing, token-unset short-circuit, job
upsert + prune mechanics, scheduler conditional registration.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from projects.polymarket.crusaderbot.services import heisenberg_trades
from projects.polymarket.crusaderbot.jobs import heisenberg_realtime_sync as sync_job


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pool():
    conn = MagicMock()
    conn.execute = AsyncMock(return_value="INSERT 0 1")
    pool = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=cm)
    return pool, conn


def _fake_settings(**overrides):
    base = dict(
        HEISENBERG_REALTIME_TRADES_ENABLED=True,
        HEISENBERG_REALTIME_TRADES_INTERVAL_SEC=60,
        HEISENBERG_REALTIME_TRADES_WINDOW_SEC=300,
        HEISENBERG_REALTIME_TRADES_RETENTION_HOURS=24,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# Client — field aliasing
# ---------------------------------------------------------------------------


def test_normalise_accepts_canonical_field_names():
    row = {
        "wallet": "0xabc",
        "condition_id": "cond-1",
        "side": "YES",
        "price": "0.42",
        "size_usdc": "50",
        "trade_time": "2026-05-30T04:30:00Z",
    }
    tr = heisenberg_trades._normalise(row)
    assert tr is not None
    assert tr.wallet == "0xabc"
    assert tr.condition_id == "cond-1"
    assert tr.side == "YES"
    assert tr.price == pytest.approx(0.42)
    assert tr.size_usdc == pytest.approx(50.0)
    assert tr.trade_time == datetime(2026, 5, 30, 4, 30, tzinfo=timezone.utc)


def test_normalise_accepts_proxy_wallet_alias():
    row = {
        "proxy_wallet": "0xdef",
        "conditionId": "cond-2",   # camelCase alias
        "direction": "NO",          # 'direction' alias for 'side'
        "trade_time": 1748579400,   # epoch int
    }
    tr = heisenberg_trades._normalise(row)
    assert tr is not None
    assert tr.wallet == "0xdef"
    assert tr.condition_id == "cond-2"
    assert tr.side == "NO"
    assert tr.price is None
    assert tr.size_usdc is None
    assert tr.trade_time.tzinfo == timezone.utc


def test_normalise_rejects_missing_required_fields():
    assert heisenberg_trades._normalise({"wallet": "0xabc"}) is None
    assert heisenberg_trades._normalise({"wallet": "0xabc", "side": "YES"}) is None


def test_normalise_rejects_bad_timestamp():
    bad = {
        "wallet": "0xabc",
        "condition_id": "c1",
        "side": "YES",
        "trade_time": "not-a-date",
    }
    assert heisenberg_trades._normalise(bad) is None


def test_safe_float_rejects_nan_and_infinity():
    assert heisenberg_trades._safe_float(float("nan")) is None
    assert heisenberg_trades._safe_float(float("inf")) is None
    assert heisenberg_trades._safe_float(float("-inf")) is None
    assert heisenberg_trades._safe_float("garbage") is None
    assert heisenberg_trades._safe_float(0) == 0.0
    assert heisenberg_trades._safe_float("1.5") == pytest.approx(1.5)


# ---------------------------------------------------------------------------
# Client — token guard
# ---------------------------------------------------------------------------


def test_fetch_recent_returns_empty_when_token_unset():
    with patch.dict("os.environ", {"HEISENBERG_API_TOKEN": ""}):
        result = asyncio.run(heisenberg_trades.fetch_recent())
    assert result == []


def test_fetch_recent_swallows_http_error_returns_empty():
    fake_resp = MagicMock()
    fake_resp.status_code = 500
    fake_resp.text = "boom"

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            return fake_resp

    with (
        patch.dict("os.environ", {"HEISENBERG_API_TOKEN": "x"}),
        patch.object(heisenberg_trades.httpx, "AsyncClient", return_value=_Client()),
    ):
        result = asyncio.run(heisenberg_trades.fetch_recent())
    assert result == []


# ---------------------------------------------------------------------------
# Job — token-unset guard
# ---------------------------------------------------------------------------


def test_job_returns_zero_when_token_unset():
    with patch.dict("os.environ", {"HEISENBERG_API_TOKEN": ""}):
        upserted, pruned = asyncio.run(sync_job.run_job())
    assert (upserted, pruned) == (0, 0)


# ---------------------------------------------------------------------------
# Job — upsert + prune flow
# ---------------------------------------------------------------------------


def test_job_upserts_each_trade_and_prunes():
    pool, conn = _make_pool()

    sample_trades = [
        heisenberg_trades.RealtimeTrade(
            wallet="0xabc",
            condition_id="cond-1",
            side="YES",
            price=0.42,
            size_usdc=50.0,
            trade_time=datetime(2026, 5, 30, 4, 30, tzinfo=timezone.utc),
            raw={"k": "v"},
        ),
        heisenberg_trades.RealtimeTrade(
            wallet="0xdef",
            condition_id="cond-2",
            side="NO",
            price=None,
            size_usdc=None,
            trade_time=datetime(2026, 5, 30, 4, 31, tzinfo=timezone.utc),
            raw={"k": "v2"},
        ),
    ]

    # Prune DELETE returns 'DELETE 7' → parsed to int 7
    conn.execute = AsyncMock(side_effect=["INSERT 0 1", "INSERT 0 1", "DELETE 7"])

    with (
        patch.dict("os.environ", {"HEISENBERG_API_TOKEN": "x"}),
        patch.object(sync_job, "get_settings", return_value=_fake_settings()),
        patch.object(sync_job, "get_pool", return_value=pool),
        patch.object(
            sync_job.heisenberg_trades,
            "fetch_recent",
            new=AsyncMock(return_value=sample_trades),
        ),
    ):
        upserted, pruned = asyncio.run(sync_job.run_job())

    assert upserted == 2
    assert pruned == 7
    assert conn.execute.await_count == 3  # 2 upserts + 1 prune

    # First upsert call has the expected SQL shape (INSERT … ON CONFLICT).
    first_sql = conn.execute.await_args_list[0].args[0]
    assert "INSERT INTO heisenberg_realtime_trades" in first_sql
    assert "ON CONFLICT (wallet, condition_id, trade_time, side)" in first_sql
    # raw is JSON-serialised as a string for $7::jsonb.
    assert isinstance(conn.execute.await_args_list[0].args[7], str)
    json.loads(conn.execute.await_args_list[0].args[7])  # parses cleanly


def test_job_returns_zero_when_no_trades_but_still_prunes():
    pool, conn = _make_pool()
    conn.execute = AsyncMock(return_value="DELETE 3")

    with (
        patch.dict("os.environ", {"HEISENBERG_API_TOKEN": "x"}),
        patch.object(sync_job, "get_settings", return_value=_fake_settings()),
        patch.object(sync_job, "get_pool", return_value=pool),
        patch.object(
            sync_job.heisenberg_trades,
            "fetch_recent",
            new=AsyncMock(return_value=[]),
        ),
    ):
        upserted, pruned = asyncio.run(sync_job.run_job())

    assert upserted == 0
    assert pruned == 3
    # Only the prune query ran — no upserts.
    assert conn.execute.await_count == 1
    assert "DELETE FROM heisenberg_realtime_trades" in conn.execute.await_args.args[0]


def test_prune_skipped_when_retention_zero():
    pool, conn = _make_pool()

    with (
        patch.dict("os.environ", {"HEISENBERG_API_TOKEN": "x"}),
        patch.object(
            sync_job, "get_settings",
            return_value=_fake_settings(HEISENBERG_REALTIME_TRADES_RETENTION_HOURS=0),
        ),
        patch.object(sync_job, "get_pool", return_value=pool),
        patch.object(
            sync_job.heisenberg_trades,
            "fetch_recent",
            new=AsyncMock(return_value=[]),
        ),
    ):
        upserted, pruned = asyncio.run(sync_job.run_job())

    assert (upserted, pruned) == (0, 0)
    assert conn.execute.await_count == 0


# ---------------------------------------------------------------------------
# Foundation pin — defaults
# ---------------------------------------------------------------------------


def test_feature_flag_defaults_off_in_settings_class():
    """Source-level pin: the foundation lane MUST default OFF until WARP🔹CMD
    explicitly enables it after confirming field-name shapes against prod."""
    from projects.polymarket.crusaderbot.config import Settings
    # Pydantic Settings reads from env at instantiation; we want the
    # class-level default — read it directly off the model fields.
    field = Settings.model_fields["HEISENBERG_REALTIME_TRADES_ENABLED"]
    assert field.default is False


def test_job_id_pinned():
    """Source-level pin so scheduler.add_job id collisions are caught here."""
    assert sync_job.JOB_ID == "heisenberg_realtime_trades_sync"
