"""WARP-95 (Issue 1): the orchestrator's user-load is decoupled from
signal_following, and each strategy toggle gates only itself.

Root cause of the 5.5h outage: _load_enrolled_users INNER-JOINed the
signal_following enrolment row + a NOT EXISTS(strategies signal_following
disabled) clause, so flipping the signal_following operator switch OFF returned
ZERO users and killed the WHOLE orchestrator — candle_auto / late_entry_v3
(Smart Strike) included. Fix: load by auto_trade_on (signal_following LEFT-JOINed
only for the legacy weight fallback); per-strategy gating stays in _preset_allows.

Hermetic — no network, no DB.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

from projects.polymarket.crusaderbot.services.signal_scan import signal_scan_job as job
from projects.polymarket.crusaderbot.services.signal_scan.signal_scan_job import (
    _preset_allows,
)


class _CapturingConn:
    """Captures the SQL passed to fetch so we can assert the query shape."""

    def __init__(self) -> None:
        self.sql: str | None = None

    async def fetch(self, sql, *args):
        self.sql = sql
        return []


class _Pool:
    def __init__(self, conn) -> None:
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _Ctx:
            async def __aenter__(self_inner):
                return conn

            async def __aexit__(self_inner, *a):
                return False

        return _Ctx()


# ── Issue 1a: user-load query no longer gated on signal_following ───────────

def test_load_enrolled_users_query_decoupled_from_signal_following():
    conn = _CapturingConn()
    with patch.object(job, "get_pool", return_value=_Pool(conn)):
        asyncio.run(job._load_enrolled_users())
    sql = conn.sql or ""
    # Driven off the users table now, gated purely on auto_trade_on / paused.
    assert "FROM users" in sql
    assert "FROM user_strategies" not in sql
    assert "auto_trade_on = TRUE" in sql
    # The signal_following killer clause is gone — disabling it can no longer
    # zero out the whole orchestrator.
    assert "NOT EXISTS" not in sql
    # Enrolment row is still LEFT-JOINed for the legacy us.weight fallback.
    assert "LEFT JOIN user_strategies" in sql


# ── Issue 1b: per-strategy gate independence (the run/no-run decision) ──────

def test_signal_following_off_does_not_block_late_entry_v3():
    """signal_following=OFF + late_entry_v3=ON → candle_auto still runs."""
    _orig = job._GLOBALLY_DISABLED_STRATEGIES
    job._GLOBALLY_DISABLED_STRATEGIES = frozenset({"signal_following"})
    try:
        for preset in ("candle_auto", "close_sweep", "safe_close", "flip_hunter"):
            assert _preset_allows(preset, "late_entry_v3") is True, preset
    finally:
        job._GLOBALLY_DISABLED_STRATEGIES = _orig


def test_late_entry_v3_off_blocks_only_late_entry_v3():
    """late_entry_v3=OFF → late_entry does NOT run; signal_following gate is
    unaffected (each toggle independent)."""
    _orig = job._GLOBALLY_DISABLED_STRATEGIES
    job._GLOBALLY_DISABLED_STRATEGIES = frozenset({"late_entry_v3"})
    try:
        assert _preset_allows("candle_auto", "late_entry_v3") is False
        # Disabling late_entry_v3 must not implicitly disable signal_following.
        assert "signal_following" not in job._GLOBALLY_DISABLED_STRATEGIES
    finally:
        job._GLOBALLY_DISABLED_STRATEGIES = _orig


def test_candle_auto_never_routes_to_signal_following():
    """candle_auto maps to late_entry_v3 only — Phase C (signal_following feed)
    can never fire for a candle_auto user regardless of toggles."""
    assert _preset_allows("candle_auto", "signal_following") is False
