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

from projects.polymarket.crusaderbot.services import heisenberg_buffer, heisenberg_trades
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


def test_job_records_to_buffer_no_db():
    """run_job fetches trades and records them into the in-memory buffer, never
    touching the DB — the get_pool dependency is gone."""
    assert not hasattr(sync_job, "get_pool")  # DB dependency fully removed
    heisenberg_buffer.clear()
    now = datetime.now(timezone.utc)
    sample_trades = [
        heisenberg_trades.RealtimeTrade(
            wallet="0xabc", condition_id="cond-1", side="YES", price=0.42,
            size_usdc=50.0, trade_time=now, raw={"k": "v"},
        ),
        heisenberg_trades.RealtimeTrade(
            wallet="0xdef", condition_id="cond-2", side="NO", price=None,
            size_usdc=None, trade_time=now, raw={"k": "v2"},
        ),
    ]
    with (
        patch.dict("os.environ", {"HEISENBERG_API_TOKEN": "x"}),
        patch.object(sync_job, "get_settings", return_value=_fake_settings()),
        patch.object(
            sync_job.heisenberg_trades, "fetch_recent",
            new=AsyncMock(return_value=sample_trades),
        ),
    ):
        recorded, pruned = asyncio.run(sync_job.run_job())

    assert (recorded, pruned) == (2, 0)
    assert heisenberg_buffer.size() == 2  # both landed in the buffer


def test_job_returns_zero_when_no_trades():
    heisenberg_buffer.clear()
    with (
        patch.dict("os.environ", {"HEISENBERG_API_TOKEN": "x"}),
        patch.object(sync_job, "get_settings", return_value=_fake_settings()),
        patch.object(
            sync_job.heisenberg_trades, "fetch_recent",
            new=AsyncMock(return_value=[]),
        ),
    ):
        recorded, pruned = asyncio.run(sync_job.run_job())
    assert (recorded, pruned) == (0, 0)
    assert heisenberg_buffer.size() == 0


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


# ---------------------------------------------------------------------------
# Gemini review pins — falsy 0 preservation + broadened never-raises contract
# ---------------------------------------------------------------------------


def test_normalise_preserves_zero_price_and_zero_size():
    """Price=0 and size_usdc=0 are LEGITIMATE in prediction markets
    (fully-resolved-NO outcome; flatten-to-zero orders). The `or` fallback
    chain would drop them — `_first_not_none` must not."""
    row = {
        "wallet": "0xzero",
        "condition_id": "cond-zero",
        "side": "NO",
        "price": 0,           # legitimately 0 (resolved NO)
        "size_usdc": 0.0,     # legitimately 0 (zero notional)
        "trade_time": "2026-05-30T05:00:00Z",
    }
    tr = heisenberg_trades._normalise(row)
    assert tr is not None
    assert tr.price == 0.0    # not None!
    assert tr.size_usdc == 0.0  # not None!


def test_normalise_falls_through_to_alias_when_primary_is_none():
    """If `price` key is missing/None, fall through to `fill_price`. If
    `size_usdc` is None, fall through to `size`, then `notional_usdc`."""
    row = {
        "wallet": "0xfallback",
        "condition_id": "cond-fb",
        "side": "YES",
        "price": None,
        "fill_price": 0.55,
        "size_usdc": None,
        "size": None,
        "notional_usdc": 25.0,
        "trade_time": "2026-05-30T05:00:00Z",
    }
    tr = heisenberg_trades._normalise(row)
    assert tr is not None
    assert tr.price == pytest.approx(0.55)
    assert tr.size_usdc == pytest.approx(25.0)


def test_fetch_recent_swallows_json_decode_error():
    """Upstream returning invalid JSON must NOT raise — return [] instead."""
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.text = "not valid json"
    fake_resp.json = MagicMock(side_effect=ValueError("malformed json"))

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


def test_fetch_recent_rejects_non_dict_response():
    """Upstream returning a JSON list / scalar (not a dict) must NOT raise on
    `.get()` — return [] with a warning instead."""
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json = MagicMock(return_value=["unexpected", "list"])

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
# CodeRabbit review pins — UTC normalisation + never-raises DB guard
# ---------------------------------------------------------------------------


def test_coerce_dt_normalises_naive_datetime_to_utc():
    """A naive datetime instance must come out tagged as UTC, not pass through
    unchanged (which would silently break the `trade_time` UTC contract)."""
    naive = datetime(2026, 5, 30, 4, 0)  # no tzinfo
    out = heisenberg_trades._coerce_dt(naive)
    assert out is not None
    assert out.tzinfo == timezone.utc
    assert out == datetime(2026, 5, 30, 4, 0, tzinfo=timezone.utc)


def test_coerce_dt_converts_non_utc_aware_to_utc():
    """An aware datetime in a different tz must be converted (not passed through),
    so every downstream value is in the same UTC frame."""
    from datetime import timedelta as _td
    jakarta = timezone(_td(hours=7))
    aware_jkt = datetime(2026, 5, 30, 11, 0, tzinfo=jakarta)  # = 04:00 UTC
    out = heisenberg_trades._coerce_dt(aware_jkt)
    assert out is not None
    assert out.tzinfo == timezone.utc
    assert out == datetime(2026, 5, 30, 4, 0, tzinfo=timezone.utc)


def test_coerce_dt_normalises_iso_string_without_tz_to_utc():
    """ISO-8601 timestamps without explicit offset must default to UTC, not
    pass through as naive (which would break the contract for downstream)."""
    out = heisenberg_trades._coerce_dt("2026-05-30T04:00:00")  # naive ISO
    assert out is not None
    assert out.tzinfo == timezone.utc
    assert out == datetime(2026, 5, 30, 4, 0, tzinfo=timezone.utc)


def test_job_has_no_db_dependency():
    """Persistence is fully removed — the job module no longer imports get_pool,
    so a DB outage cannot affect the real-time buffer feed."""
    assert not hasattr(sync_job, "get_pool")
    heisenberg_buffer.clear()
    sample_trades = [
        heisenberg_trades.RealtimeTrade(
            wallet="0xabc", condition_id="cond-1", side="YES", price=0.42,
            size_usdc=50.0, trade_time=datetime.now(timezone.utc), raw={"k": "v"},
        ),
    ]
    with (
        patch.dict("os.environ", {"HEISENBERG_API_TOKEN": "x"}),
        patch.object(sync_job, "get_settings", return_value=_fake_settings()),
        patch.object(
            sync_job.heisenberg_trades, "fetch_recent",
            new=AsyncMock(return_value=sample_trades),
        ),
    ):
        recorded, pruned = asyncio.run(sync_job.run_job())
    assert (recorded, pruned) == (1, 0)
    assert heisenberg_buffer.size() == 1
