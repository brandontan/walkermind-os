"""Hermetic tests for the string-tier access layer.

Covers:
- services/tiers.py: get_user_tier, set_user_tier, meets_tier, tier_rank,
  list_all_user_tiers, VALID_TIERS
- bot/middleware/access_tier.py: require_access_tier decorator (allow + deny paths)
- bot/handlers/admin.py: _is_admin_user, admin_root routing + subcommands
  (_admin_users, _admin_settier, _admin_stats, _admin_broadcast) — no DB, no network.

No DB connection is made. All pool/conn interactions are mocked.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.run(coro)


def _update(user_id: int = 999, message_text: str = "/admin"):
    msg = MagicMock()
    msg.reply_text = AsyncMock()
    msg.text = message_text
    user = SimpleNamespace(id=user_id)
    upd = MagicMock()
    upd.effective_user = user
    upd.effective_message = msg
    upd.message = msg
    upd.callback_query = None
    return upd


def _ctx(*args: str):
    ctx = MagicMock()
    ctx.args = list(args)
    return ctx


# ---------------------------------------------------------------------------
# services/tiers.py — pure logic (no DB)
# ---------------------------------------------------------------------------

from projects.polymarket.crusaderbot.services import tiers as tier_svc


def test_tier_rank_ordering():
    assert tier_svc.tier_rank("FREE") < tier_svc.tier_rank("PREMIUM")
    assert tier_svc.tier_rank("PREMIUM") < tier_svc.tier_rank("ADMIN")


def test_meets_tier_same():
    assert tier_svc.meets_tier("PREMIUM", "PREMIUM") is True


def test_meets_tier_above():
    assert tier_svc.meets_tier("ADMIN", "PREMIUM") is True


def test_meets_tier_below():
    assert tier_svc.meets_tier("FREE", "PREMIUM") is False


def test_meets_tier_unknown_user_tier_defaults_to_free_rank():
    # Unknown user tier maps to rank 0 (same as FREE), so it meets FREE but not PREMIUM.
    assert tier_svc.meets_tier("UNKNOWN", "FREE") is True
    assert tier_svc.meets_tier("UNKNOWN", "PREMIUM") is False


def test_meets_tier_raises_on_unknown_required_tier():
    # Fail closed: a misspelled required tier raises rather than granting access.
    with pytest.raises(ValueError, match="unknown required tier"):
        tier_svc.meets_tier("ADMIN", "PREMUM")  # typo


def test_valid_tiers_set():
    assert tier_svc.VALID_TIERS == frozenset({"FREE", "PREMIUM", "ADMIN"})


# ---------------------------------------------------------------------------
# services/tiers.py — DB mocked
# ---------------------------------------------------------------------------

def _mock_pool(fetchrow_return=None, execute_return=None, fetch_return=None):
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow_return)
    conn.execute = AsyncMock(return_value=execute_return)
    conn.fetch = AsyncMock(return_value=fetch_return or [])

    class _CM:
        async def __aenter__(self):
            return conn

        async def __aexit__(self, *_):
            pass

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_CM())
    return pool, conn


def test_get_user_tier_returns_free_when_missing():
    pool, _ = _mock_pool(fetchrow_return=None)
    with patch("projects.polymarket.crusaderbot.services.tiers.get_pool",
               return_value=pool):
        result = _run(tier_svc.get_user_tier(123))
    assert result == "FREE"


def test_get_user_tier_returns_db_value():
    pool, _ = _mock_pool(fetchrow_return={"tier": "PREMIUM"})
    with patch("projects.polymarket.crusaderbot.services.tiers.get_pool",
               return_value=pool):
        result = _run(tier_svc.get_user_tier(123))
    assert result == "PREMIUM"


def test_set_user_tier_raises_on_invalid():
    pool, _ = _mock_pool()
    with patch("projects.polymarket.crusaderbot.services.tiers.get_pool",
               return_value=pool):
        with pytest.raises(ValueError, match="Invalid tier"):
            _run(tier_svc.set_user_tier(123, "GODMODE", assigned_by=1))


def test_set_user_tier_upserts():
    pool, conn = _mock_pool()
    with patch("projects.polymarket.crusaderbot.services.tiers.get_pool",
               return_value=pool):
        _run(tier_svc.set_user_tier(456, "PREMIUM", assigned_by=99))
    conn.execute.assert_awaited_once()
    sql = conn.execute.await_args.args[0]
    assert "INSERT INTO user_tiers" in sql
    assert "ON CONFLICT" in sql


def test_list_all_user_tiers_empty():
    pool, _ = _mock_pool(fetch_return=[])
    with patch("projects.polymarket.crusaderbot.services.tiers.get_pool",
               return_value=pool):
        rows = _run(tier_svc.list_all_user_tiers())
    assert rows == []


def test_list_all_user_tiers_returns_dicts():
    from datetime import datetime, timezone
    row = {"user_id": 1, "tier": "ADMIN", "assigned_by": 9,
           "assigned_at": datetime(2026, 1, 1, tzinfo=timezone.utc)}
    pool, _ = _mock_pool(fetch_return=[row])
    with patch("projects.polymarket.crusaderbot.services.tiers.get_pool",
               return_value=pool):
        rows = _run(tier_svc.list_all_user_tiers())
    assert len(rows) == 1
    assert rows[0]["tier"] == "ADMIN"


# ---------------------------------------------------------------------------
# bot/middleware/access_tier.py — decorator
# ---------------------------------------------------------------------------

from projects.polymarket.crusaderbot.bot.middleware import access_tier as at_mw


def test_require_access_tier_allows_when_meets():
    called = []

    async def _handler(update, ctx):
        called.append(True)

    wrapped = at_mw.require_access_tier("PREMIUM")(_handler)
    upd = _update(user_id=10)

    with patch(
        "projects.polymarket.crusaderbot.bot.middleware.access_tier.get_user_tier",
        new=AsyncMock(return_value="PREMIUM"),
    ):
        _run(wrapped(upd, _ctx()))

    assert called == [True]


def test_require_access_tier_blocks_when_below():
    called = []

    async def _handler(update, ctx):
        called.append(True)

    wrapped = at_mw.require_access_tier("PREMIUM")(_handler)
    upd = _update(user_id=11)

    with patch(
        "projects.polymarket.crusaderbot.bot.middleware.access_tier.get_user_tier",
        new=AsyncMock(return_value="FREE"),
    ):
        _run(wrapped(upd, _ctx()))

    assert called == []
    upd.effective_message.reply_text.assert_awaited_once()
    call_kwargs = upd.effective_message.reply_text.await_args[0][0]
    # Tier wording is hidden from users (Chunk N cleanup); message says "not available"
    assert "not available" in call_kwargs


def test_require_access_tier_admin_blocks_premium():
    """ADMIN tier passes when PREMIUM is required (rank >= rank)."""
    called = []

    async def _handler(update, ctx):
        called.append(True)

    wrapped = at_mw.require_access_tier("PREMIUM")(_handler)
    upd = _update(user_id=12)

    with patch(
        "projects.polymarket.crusaderbot.bot.middleware.access_tier.get_user_tier",
        new=AsyncMock(return_value="ADMIN"),
    ):
        _run(wrapped(upd, _ctx()))

    assert called == [True]


def test_require_access_tier_no_user_is_noop():
    called = []

    async def _handler(update, ctx):
        called.append(True)

    wrapped = at_mw.require_access_tier("PREMIUM")(_handler)
    upd = _update()
    upd.effective_user = None

    _run(wrapped(upd, _ctx()))
    assert called == []


def test_require_access_tier_raises_at_decoration_time_on_bad_tier():
    with pytest.raises(ValueError, match="unknown tier"):
        at_mw.require_access_tier("PREMUM")  # typo — caught at decoration, not runtime


def test_require_access_tier_returns_handler_return_value():
    """Wrapper must propagate the handler's return value for ConversationHandler."""
    SENTINEL = object()

    async def _handler(update, ctx):
        return SENTINEL

    wrapped = at_mw.require_access_tier("FREE")(_handler)
    upd = _update(user_id=10)

    with patch(
        "projects.polymarket.crusaderbot.bot.middleware.access_tier.get_user_tier",
        new=AsyncMock(return_value="FREE"),
    ):
        result = _run(wrapped(upd, _ctx()))

    assert result is SENTINEL


# ---------------------------------------------------------------------------
# bot/handlers/admin.py — _is_admin_user
# ---------------------------------------------------------------------------

from projects.polymarket.crusaderbot.bot.handlers import admin as admin_h


def test_is_admin_user_true_for_operator():
    upd = _update(user_id=777)
    settings_mock = MagicMock()
    settings_mock.OPERATOR_CHAT_ID = 777
    with patch(
        "projects.polymarket.crusaderbot.bot.handlers.admin.get_settings",
        return_value=settings_mock,
    ):
        result = _run(admin_h._is_admin_user(upd))
    assert result is True


def test_is_admin_user_true_for_admin_tier():
    upd = _update(user_id=500)
    settings_mock = MagicMock()
    settings_mock.OPERATOR_CHAT_ID = 999  # different from user
    with patch(
        "projects.polymarket.crusaderbot.bot.handlers.admin.get_settings",
        return_value=settings_mock,
    ), patch(
        "projects.polymarket.crusaderbot.bot.handlers.admin.get_user_tier",
        new=AsyncMock(return_value="ADMIN"),
    ):
        result = _run(admin_h._is_admin_user(upd))
    assert result is True


def test_is_admin_user_false_for_free_tier():
    upd = _update(user_id=600)
    settings_mock = MagicMock()
    settings_mock.OPERATOR_CHAT_ID = 999
    with patch(
        "projects.polymarket.crusaderbot.bot.handlers.admin.get_settings",
        return_value=settings_mock,
    ), patch(
        "projects.polymarket.crusaderbot.bot.handlers.admin.get_user_tier",
        new=AsyncMock(return_value="FREE"),
    ):
        result = _run(admin_h._is_admin_user(upd))
    assert result is False


# ---------------------------------------------------------------------------
# bot/handlers/admin.py — admin_root routing
# ---------------------------------------------------------------------------

def _settings_not_operator(user_id: int):
    s = MagicMock()
    s.OPERATOR_CHAT_ID = user_id + 1  # always different
    return s


def test_admin_root_blocks_non_admin_tier_user():
    upd = _update(user_id=42)
    settings_mock = _settings_not_operator(42)
    with patch(
        "projects.polymarket.crusaderbot.bot.handlers.admin.get_settings",
        return_value=settings_mock,
    ), patch(
        "projects.polymarket.crusaderbot.bot.handlers.admin.get_user_tier",
        new=AsyncMock(return_value="FREE"),
    ):
        _run(admin_h.admin_root(upd, _ctx()))

    upd.message.reply_text.assert_awaited_once()
    text = upd.message.reply_text.await_args[0][0]
    assert "Admin access required" in text


def test_admin_root_shows_help_for_admin_tier_no_args():
    upd = _update(user_id=55)
    settings_mock = _settings_not_operator(55)
    with patch(
        "projects.polymarket.crusaderbot.bot.handlers.admin.get_settings",
        return_value=settings_mock,
    ), patch(
        "projects.polymarket.crusaderbot.bot.handlers.admin.get_user_tier",
        new=AsyncMock(return_value="ADMIN"),
    ):
        _run(admin_h.admin_root(upd, _ctx()))

    upd.message.reply_text.assert_awaited_once()
    text = upd.message.reply_text.await_args[0][0]
    assert "Admin panel" in text or "admin panel" in text.lower()


def test_admin_root_routes_users_subcommand():
    upd = _update(user_id=55)
    settings_mock = _settings_not_operator(55)
    with patch(
        "projects.polymarket.crusaderbot.bot.handlers.admin.get_settings",
        return_value=settings_mock,
    ), patch(
        "projects.polymarket.crusaderbot.bot.handlers.admin.get_user_tier",
        new=AsyncMock(return_value="ADMIN"),
    ), patch(
        "projects.polymarket.crusaderbot.bot.handlers.admin.list_all_user_tiers",
        new=AsyncMock(return_value=[]),
    ):
        _run(admin_h.admin_root(upd, _ctx("users")))

    upd.message.reply_text.assert_awaited_once()


def test_admin_root_routes_settier_missing_args():
    upd = _update(user_id=55)
    settings_mock = _settings_not_operator(55)
    with patch(
        "projects.polymarket.crusaderbot.bot.handlers.admin.get_settings",
        return_value=settings_mock,
    ), patch(
        "projects.polymarket.crusaderbot.bot.handlers.admin.get_user_tier",
        new=AsyncMock(return_value="ADMIN"),
    ):
        _run(admin_h.admin_root(upd, _ctx("settier")))

    upd.message.reply_text.assert_awaited_once()
    text = upd.message.reply_text.await_args[0][0]
    assert "Usage" in text


def test_admin_root_settier_invalid_tier():
    upd = _update(user_id=55)
    settings_mock = _settings_not_operator(55)
    with patch(
        "projects.polymarket.crusaderbot.bot.handlers.admin.get_settings",
        return_value=settings_mock,
    ), patch(
        "projects.polymarket.crusaderbot.bot.handlers.admin.get_user_tier",
        new=AsyncMock(return_value="ADMIN"),
    ):
        _run(admin_h.admin_root(upd, _ctx("settier", "12345", "GODMODE")))

    text = upd.message.reply_text.await_args[0][0]
    assert "Invalid tier" in text


def test_admin_root_settier_success():
    upd = _update(user_id=55)
    settings_mock = _settings_not_operator(55)
    with patch(
        "projects.polymarket.crusaderbot.bot.handlers.admin.get_settings",
        return_value=settings_mock,
    ), patch(
        "projects.polymarket.crusaderbot.bot.handlers.admin.get_user_tier",
        new=AsyncMock(return_value="ADMIN"),
    ), patch(
        "projects.polymarket.crusaderbot.bot.handlers.admin.set_user_tier",
        new=AsyncMock(),
    ), patch(
        "projects.polymarket.crusaderbot.bot.handlers.admin.audit.write",
        new=AsyncMock(),
    ):
        _run(admin_h.admin_root(upd, _ctx("settier", "99999", "PREMIUM")))

    text = upd.message.reply_text.await_args[0][0]
    assert "99999" in text
    assert "PREMIUM" in text


def test_admin_root_routes_stats():
    # fetchval call order: total_users, open_positions, paper_pnl, free_n (JOIN), premium_n, admin_n
    upd = _update(user_id=55)
    settings_mock = _settings_not_operator(55)
    pool, conn = _mock_pool()
    conn.fetchval = AsyncMock(side_effect=[5, 3, -12.5, 3, 1, 1])
    with patch(
        "projects.polymarket.crusaderbot.bot.handlers.admin.get_settings",
        return_value=settings_mock,
    ), patch(
        "projects.polymarket.crusaderbot.bot.handlers.admin.get_user_tier",
        new=AsyncMock(return_value="ADMIN"),
    ), patch(
        "projects.polymarket.crusaderbot.bot.handlers.admin.get_pool",
        return_value=pool,
    ):
        _run(admin_h.admin_root(upd, _ctx("stats")))

    text = upd.message.reply_text.await_args[0][0]
    assert "Stats" in text or "stats" in text.lower()
    assert "Total users" in text


def test_admin_root_broadcast_no_args():
    upd = _update(user_id=55)
    settings_mock = _settings_not_operator(55)
    with patch(
        "projects.polymarket.crusaderbot.bot.handlers.admin.get_settings",
        return_value=settings_mock,
    ), patch(
        "projects.polymarket.crusaderbot.bot.handlers.admin.get_user_tier",
        new=AsyncMock(return_value="ADMIN"),
    ):
        _run(admin_h.admin_root(upd, _ctx("broadcast")))

    text = upd.message.reply_text.await_args[0][0]
    assert "Usage" in text


def test_admin_root_broadcast_sends_counts_return_value():
    """sent/failed counts are driven by notifications.send return value, not exceptions."""
    upd = _update(user_id=55)
    settings_mock = _settings_not_operator(55)
    pool, conn = _mock_pool()
    conn.fetch = AsyncMock(return_value=[
        {"telegram_user_id": 100},
        {"telegram_user_id": 200},
        {"telegram_user_id": 300},
    ])
    # First two succeed (True), third fails permanently (False).
    with patch(
        "projects.polymarket.crusaderbot.bot.handlers.admin.get_settings",
        return_value=settings_mock,
    ), patch(
        "projects.polymarket.crusaderbot.bot.handlers.admin.get_user_tier",
        new=AsyncMock(return_value="ADMIN"),
    ), patch(
        "projects.polymarket.crusaderbot.bot.handlers.admin.get_pool",
        return_value=pool,
    ), patch(
        "projects.polymarket.crusaderbot.bot.handlers.admin.notifications.send",
        new=AsyncMock(side_effect=[True, True, False]),
    ):
        _run(admin_h.admin_root(upd, _ctx("broadcast", "Hello", "world")))

    text = upd.message.reply_text.await_args[0][0]
    assert "2 delivered" in text
    assert "1 failed" in text


def test_admin_root_unknown_subcommand_shows_help():
    upd = _update(user_id=55)
    settings_mock = _settings_not_operator(55)
    with patch(
        "projects.polymarket.crusaderbot.bot.handlers.admin.get_settings",
        return_value=settings_mock,
    ), patch(
        "projects.polymarket.crusaderbot.bot.handlers.admin.get_user_tier",
        new=AsyncMock(return_value="ADMIN"),
    ):
        _run(admin_h.admin_root(upd, _ctx("unknown_cmd")))

    text = upd.message.reply_text.await_args[0][0]
    assert "settier" in text or "users" in text
