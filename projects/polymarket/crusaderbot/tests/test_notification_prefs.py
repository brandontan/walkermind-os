"""Hermetic tests for webtrader/backend/notification_prefs.py.

Covers fail-open semantics, channel/key validation, and the persist_user_alert
short-circuit when the user disables web delivery for an alert.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from projects.polymarket.crusaderbot.webtrader.backend import notification_prefs as np


_USER = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


def _fake_pool(*, prefs_blob=None, insert_id=None) -> MagicMock:
    """Build an asyncpg-shaped fake pool that returns a single row of prefs."""
    conn = AsyncMock()
    conn.__aenter__.return_value = conn
    conn.__aexit__.return_value = None
    if prefs_blob is None:
        conn.fetchrow = AsyncMock(return_value=None)
    else:
        async def _fetchrow(q, *args, **kw):
            if "INSERT INTO system_alerts" in q:
                return {"id": insert_id} if insert_id else None
            return {"notification_prefs": prefs_blob}
        conn.fetchrow = AsyncMock(side_effect=_fetchrow)
    conn.execute = AsyncMock(return_value=None)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=conn)
    return pool


@pytest.mark.asyncio
async def test_should_notify_defaults_true_when_no_prefs():
    """No row in user_settings → default ON for every (key, channel)."""
    pool = _fake_pool(prefs_blob=None)
    with patch.object(np, "get_pool", return_value=pool):
        assert await np.should_notify(_USER, "trade_opened", "web") is True
        assert await np.should_notify(_USER, "trade_closed", "tg") is True


@pytest.mark.asyncio
async def test_should_notify_respects_explicit_off():
    """User flips trade_opened.tg OFF — gate returns False only for that pair."""
    prefs = {"trade_opened": {"web": True, "tg": False}}
    with patch.object(np, "get_pool", return_value=_fake_pool(prefs_blob=prefs)):
        assert await np.should_notify(_USER, "trade_opened", "web") is True
        assert await np.should_notify(_USER, "trade_opened", "tg") is False
        # Unrelated key still defaults ON.
        assert await np.should_notify(_USER, "kill_switch", "tg") is True


@pytest.mark.asyncio
async def test_should_notify_fail_open_on_unknown_key_or_channel():
    """Unknown alert_key / channel always returns True — UI is the schema source."""
    with patch.object(np, "get_pool", return_value=_fake_pool(prefs_blob={})):
        assert await np.should_notify(_USER, "made_up_alert", "web") is True
        assert await np.should_notify(_USER, "trade_opened", "sms") is True  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_should_notify_fail_open_on_db_error():
    """DB read error → return True (rather than silently drop a notification)."""
    conn = AsyncMock()
    conn.__aenter__.return_value = conn
    conn.__aexit__.return_value = None
    conn.fetchrow = AsyncMock(side_effect=RuntimeError("pool down"))
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=conn)
    with patch.object(np, "get_pool", return_value=pool):
        assert await np.should_notify(_USER, "trade_opened", "web") is True


@pytest.mark.asyncio
async def test_should_notify_none_user_returns_true():
    """user_id=None (broadcast path) → fall back to ON without a DB roundtrip."""
    # No pool patch needed — the early-return path must not touch the DB.
    assert await np.should_notify(None, "trade_opened", "web") is True


@pytest.mark.asyncio
async def test_persist_user_alert_skips_when_web_disabled():
    """User disabled web delivery for kill_switch → no row inserted."""
    prefs = {"kill_switch": {"web": False, "tg": True}}
    pool = _fake_pool(prefs_blob=prefs, insert_id="row-xyz")
    with patch.object(np, "get_pool", return_value=pool):
        result = await np.persist_user_alert(
            user_id=_USER, alert_key="kill_switch",
            title="Killed", body="kill switch armed",
        )
    assert result is None


@pytest.mark.asyncio
async def test_persist_user_alert_inserts_when_web_enabled():
    """User has web ON (or default) → row inserted, alert id returned."""
    pool = _fake_pool(prefs_blob={}, insert_id="row-xyz")
    with patch.object(np, "get_pool", return_value=pool):
        result = await np.persist_user_alert(
            user_id=_USER, alert_key="trade_opened",
            title="BUY", body="opened", severity="info",
        )
    assert result == "row-xyz"


@pytest.mark.asyncio
async def test_persist_user_alert_normalizes_bad_severity():
    """Severity outside enum coerced to default ('info') — never raises."""
    # We just need to confirm no exception and the INSERT path runs.
    pool = _fake_pool(prefs_blob={}, insert_id="row-abc")
    with patch.object(np, "get_pool", return_value=pool):
        result = await np.persist_user_alert(
            user_id=_USER, alert_key="trade_opened",
            title="BUY", severity="bogus",
        )
    assert result == "row-abc"


@pytest.mark.asyncio
async def test_set_prefs_drops_unknown_keys_and_channels():
    """Unknown alert_key / channel silently dropped before DB write."""
    pool = _fake_pool(prefs_blob={})
    conn = pool.acquire.return_value
    with patch.object(np, "get_pool", return_value=pool):
        await np.set_prefs(_USER, {
            "trade_opened": {"web": True, "tg": False, "sms": True},  # sms dropped
            "made_up_key": {"web": True},                              # whole row dropped
            "kill_switch": {"web": False, "tg": False},
        })
    args = conn.execute.await_args.args
    # second arg = JSON-encoded blob
    import json
    written = json.loads(args[1])
    assert "made_up_key" not in written
    assert "sms" not in written["trade_opened"]
    assert written["trade_opened"] == {"web": True, "tg": False}
    assert written["kill_switch"] == {"web": False, "tg": False}


def test_alert_keys_match_frontend_schema():
    """Regression guard: ALERT_KEYS must mirror NotificationPrefsCard.tsx exactly.

    Drift here means the UI can post a key the backend silently drops.
    """
    expected = {
        "trade_opened", "trade_closed", "position_resolved",
        "signal_detected", "system_status", "bot_errors",
        "kill_switch", "low_balance", "daily_report",
    }
    assert np.ALERT_KEYS == frozenset(expected)
