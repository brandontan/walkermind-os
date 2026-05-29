"""WebTrader Admin console + global strategy on/off — hermetic tests."""
from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from projects.polymarket.crusaderbot.webtrader.backend import router as r
from projects.polymarket.crusaderbot.webtrader.backend.schemas import StrategyToggleRequest
from projects.polymarket.crusaderbot.services.signal_scan import signal_scan_job as job


# ── fake pool helpers ─────────────────────────────────────────────────────────


def _ctx(value=None):
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=value)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _pool(conn):
    p = MagicMock()
    p.acquire = MagicMock(return_value=_ctx(conn))
    return p


# ── global strategy gate (scanner) ────────────────────────────────────────────


def test_preset_allows_blocks_globally_disabled():
    """A globally-disabled strategy is never allowed, regardless of preset."""
    original = job._GLOBALLY_DISABLED_STRATEGIES
    try:
        job._GLOBALLY_DISABLED_STRATEGIES = frozenset({"late_entry_v3"})
        # late_entry_v3 would normally be allowed under a candle preset
        assert job._preset_allows("close_sweep", "late_entry_v3") is False
        # a non-disabled strategy still follows preset rules
        assert job._preset_allows(None, "momentum") is True
    finally:
        job._GLOBALLY_DISABLED_STRATEGIES = original


def test_preset_allows_default_when_none_disabled():
    original = job._GLOBALLY_DISABLED_STRATEGIES
    try:
        job._GLOBALLY_DISABLED_STRATEGIES = frozenset()
        assert job._preset_allows(None, "momentum") is True
    finally:
        job._GLOBALLY_DISABLED_STRATEGIES = original


def test_refresh_disabled_strategies_fail_safe():
    """A DB error must NOT change the disabled set (fail-safe)."""
    original = job._GLOBALLY_DISABLED_STRATEGIES
    try:
        job._GLOBALLY_DISABLED_STRATEGIES = frozenset({"x"})
        boom = MagicMock()
        boom.acquire = MagicMock(side_effect=RuntimeError("db down"))
        with patch.object(job, "get_pool", return_value=boom):
            asyncio.run(job._refresh_disabled_strategies())
        assert job._GLOBALLY_DISABLED_STRATEGIES == frozenset({"x"})  # unchanged
    finally:
        job._GLOBALLY_DISABLED_STRATEGIES = original


def test_signal_following_loader_has_global_gate():
    """The signal_following loader query must fail-safe gate on the strategies table."""
    src = inspect.getsource(job)
    assert "NOT EXISTS" in src
    assert "FROM strategies st" in src
    assert "st.enabled = FALSE" in src


def test_run_once_refreshes_toggle():
    src = inspect.getsource(job.run_once)
    assert "_refresh_disabled_strategies()" in src


# ── _require_admin ────────────────────────────────────────────────────────────


def test_require_admin_allows_admin():
    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value="admin")
    with patch.object(r, "get_pool", return_value=_pool(conn)):
        out = asyncio.run(r._require_admin({"user_id": str(uuid4())}))
    assert out["user_id"]


def test_require_admin_rejects_non_admin():
    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value="user")
    with patch.object(r, "get_pool", return_value=_pool(conn)):
        with pytest.raises(Exception) as exc:
            asyncio.run(r._require_admin({"user_id": str(uuid4())}))
    assert "403" in str(exc.value) or "admin only" in str(exc.value)


# ── admin_strategies ──────────────────────────────────────────────────────────


def test_admin_strategies_returns_full_roster_default_on():
    conn = MagicMock()
    # only one explicit row (disabled); the rest default to ON
    conn.fetch = AsyncMock(return_value=[{"name": "copy_trade", "enabled": False}])
    with patch.object(r, "get_pool", return_value=_pool(conn)):
        out = asyncio.run(r.admin_strategies({"user_id": "x"}))
    names = {s["name"]: s["enabled"] for s in out["strategies"]}
    assert names["copy_trade"] is False           # explicit disabled
    assert names["late_entry_v3"] is True          # default ON (no row)
    assert len(out["strategies"]) == len(r._ADMIN_STRATEGIES)


# ── admin_toggle_strategy ─────────────────────────────────────────────────────


def test_admin_toggle_rejects_unknown_strategy():
    body = StrategyToggleRequest(name="not_a_strategy", enabled=False)
    with pytest.raises(Exception) as exc:
        asyncio.run(r.admin_toggle_strategy(body, {"user_id": str(uuid4())}))
    assert "unknown strategy" in str(exc.value) or "400" in str(exc.value)


def test_admin_toggle_writes_and_audits():
    body = StrategyToggleRequest(name="late_entry_v3", enabled=False)
    conn = MagicMock()
    conn.execute = AsyncMock()
    with patch.object(r, "get_pool", return_value=_pool(conn)), \
         patch.object(r.audit, "write", AsyncMock()) as mock_audit:
        out = asyncio.run(r.admin_toggle_strategy(body, {"user_id": str(uuid4())}))
    assert out == {"name": "late_entry_v3", "enabled": False}
    conn.execute.assert_awaited_once()
    mock_audit.assert_awaited_once()


# ── /me role ──────────────────────────────────────────────────────────────────


def test_get_me_includes_role_and_is_admin():
    conn = MagicMock()
    async def fetchrow(q, *a):
        return {"email": "a@b.com", "username": "u", "telegram_user_id": 1, "role": "admin"}
    conn.fetchrow = fetchrow
    with patch.object(r, "get_pool", return_value=_pool(conn)):
        out = asyncio.run(r.get_me({"user_id": "x", "first_name": "A"}))
    assert out["role"] == "admin"
    assert out["is_admin"] is True
