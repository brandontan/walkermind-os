"""Hermetic tests for onboarding polish — Track L.

No real DB, no Telegram API, no network. All external calls are mocked.

Coverage (12 tests):
  Keyboards (no async):
    1  get_started_kb    — has Get Started button
    2  mode_select_kb    — has Paper Trading and Live Trading buttons
    3  paper_complete_kb — has View Dashboard button

  Handler flows (mocked DB + mock Update):
    4  New user /start   — shows welcome text, returns ONBOARD_WELCOME
    5  Returning user /start (onboarding_complete) — routes to dashboard, returns END
    6  Returning user /start any tier — goes to dashboard, returns END
    7  Get Started callback — seeds wallet, shows wallet text, returns ONBOARD_WALLET
    8  view_dashboard_cb — delegates to dashboard handler

  /help (V6 static help message):
    9  /help shows navigation items (Auto Trade, Portfolio, Settings, Insights)
   10  /help shows Stop Bot item
   11  /help shows /start hint
   12  /help static text (no operator distinction in V6)
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from projects.polymarket.crusaderbot.bot.keyboards.onboarding import (
    get_started_kb,
    mode_select_kb,
    paper_complete_kb,
)
import projects.polymarket.crusaderbot.bot.handlers.onboarding as ob_mod
from projects.polymarket.crusaderbot.bot.handlers.onboarding import (
    ONBOARD_WELCOME,
    ONBOARD_WALLET,
    _entry,
    _start_cb,
    view_dashboard_cb,
    help_handler,
)
from telegram.ext import ConversationHandler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(uid=None, *, access_tier=1, onboarding_complete=False):
    return {
        "id": uid or uuid4(),
        "telegram_user_id": 12345,
        "username": "testuser",
        "access_tier": access_tier,
        "auto_trade_on": False,
        "onboarding_complete": onboarding_complete,
    }


def _make_cmd_update(tg_user_id=12345, username="testuser"):
    replies: list = []

    async def _reply_text(text, **kw):
        replies.append(("text", text, kw))
        # Return a fake Message so onboarding can store msg.message_id
        return SimpleNamespace(message_id=999)

    msg = SimpleNamespace(
        reply_text=AsyncMock(side_effect=_reply_text),
    )
    tg_user = SimpleNamespace(id=tg_user_id, username=username, first_name="Test")
    return SimpleNamespace(
        message=msg,
        callback_query=None,
        effective_user=tg_user,
        effective_message=msg,
    ), replies


def _make_cb_update(callback_data: str, tg_user_id=12345, username="testuser"):
    replies: list = []

    async def _reply_text(text, **kw):
        replies.append(("text", text, kw))
        return SimpleNamespace(message_id=998)

    async def _edit_message_text(text, **kw):
        replies.append(("edit", text, kw))

    msg = SimpleNamespace(
        reply_text=AsyncMock(side_effect=_reply_text),
        edit_message_text=AsyncMock(side_effect=_edit_message_text),
    )
    cq = SimpleNamespace(
        data=callback_data,
        answer=AsyncMock(),
        message=msg,
        from_user=SimpleNamespace(id=tg_user_id, username=username),
        edit_message_text=AsyncMock(side_effect=_edit_message_text),
    )
    tg_user = SimpleNamespace(id=tg_user_id, username=username, first_name="Test")
    return SimpleNamespace(
        message=None,
        callback_query=cq,
        effective_user=tg_user,
        effective_message=msg,
    ), replies


def _ctx(user_data: dict | None = None):
    ctx = MagicMock()
    ctx.args = []
    ctx.user_data = user_data or {}
    return ctx


# ---------------------------------------------------------------------------
# 1–3: Keyboard purity tests (no async)
# ---------------------------------------------------------------------------

def test_get_started_kb_button():
    kb = get_started_kb()
    flat = [btn for row in kb.inline_keyboard for btn in row]
    datas = {b.callback_data for b in flat}
    assert "onboard:get_started" in datas


def test_mode_select_kb_buttons():
    kb = mode_select_kb()
    flat = [btn for row in kb.inline_keyboard for btn in row]
    datas = {b.callback_data for b in flat}
    assert "onboard:mode_paper" in datas
    assert "onboard:mode_live" in datas


def test_paper_complete_kb_button():
    kb = paper_complete_kb()
    flat = [btn for row in kb.inline_keyboard for btn in row]
    datas = {b.callback_data for b in flat}
    assert "onboard:view_dashboard" in datas


# ---------------------------------------------------------------------------
# 4: New user /start shows welcome
# ---------------------------------------------------------------------------

def test_new_user_start_shows_welcome():
    user = _make_user(onboarding_complete=False)
    update, replies = _make_cmd_update()
    ctx = _ctx()

    with (
        patch.object(ob_mod, "upsert_user", AsyncMock(return_value=user)),
        patch.object(ob_mod, "audit") as mock_audit,
        patch.object(ob_mod, "get_or_create_referral_code", AsyncMock()),
        patch.object(ob_mod, "parse_ref_param", return_value=None),
    ):
        mock_audit.write = AsyncMock()
        result = asyncio.run(_entry(update, ctx))

    assert result == ONBOARD_WELCOME
    assert any("Polymarket trading copilot" in r[1] for r in replies)


# ---------------------------------------------------------------------------
# 5: Returning user /start (onboarding_complete) → dashboard
# ---------------------------------------------------------------------------

def test_existing_user_start_routes_to_dashboard():
    """V6: any returning user (onboarding_complete=True) goes to dashboard."""
    user = _make_user(onboarding_complete=True, access_tier=2)
    update, replies = _make_cmd_update()
    ctx = _ctx()

    mock_dashboard = AsyncMock()
    import projects.polymarket.crusaderbot.bot.handlers.dashboard as dash_mod

    with (
        patch.object(ob_mod, "upsert_user", AsyncMock(return_value=user)),
        patch.object(ob_mod, "audit") as mock_audit,
        patch.object(ob_mod, "get_or_create_referral_code", AsyncMock()),
        patch.object(ob_mod, "parse_ref_param", return_value=None),
        patch.object(dash_mod, "dashboard", mock_dashboard),
    ):
        mock_audit.write = AsyncMock()
        result = asyncio.run(_entry(update, ctx))

    assert result == ConversationHandler.END
    mock_dashboard.assert_awaited_once()


# ---------------------------------------------------------------------------
# 6: Returning user any tier /start — also goes to dashboard
# ---------------------------------------------------------------------------

def test_returning_any_tier_user_routes_to_dashboard():
    """V6: tier is not checked — all returning users go directly to dashboard."""
    user = _make_user(onboarding_complete=True, access_tier=1)
    update, replies = _make_cmd_update()
    ctx = _ctx()

    mock_dashboard = AsyncMock()
    import projects.polymarket.crusaderbot.bot.handlers.dashboard as dash_mod

    with (
        patch.object(ob_mod, "upsert_user", AsyncMock(return_value=user)),
        patch.object(ob_mod, "audit") as mock_audit,
        patch.object(ob_mod, "get_or_create_referral_code", AsyncMock()),
        patch.object(ob_mod, "parse_ref_param", return_value=None),
        patch.object(dash_mod, "dashboard", mock_dashboard),
    ):
        mock_audit.write = AsyncMock()
        result = asyncio.run(_entry(update, ctx))

    assert result == ConversationHandler.END
    mock_dashboard.assert_awaited_once()


# ---------------------------------------------------------------------------
# 7: Get Started callback — seeds wallet, shows wallet text, returns ONBOARD_WALLET
# ---------------------------------------------------------------------------

def test_get_started_moves_to_wallet_step():
    """V6: _start_cb handles onboard:get_started, shows wallet text, returns ONBOARD_WALLET."""
    update, replies = _make_cb_update("onboard:get_started")
    ctx = _ctx()
    mock_user = _make_user()

    with patch.object(ob_mod, "upsert_user", AsyncMock(return_value=mock_user)):
        result = asyncio.run(_start_cb(update, ctx))

    assert result == ONBOARD_WALLET
    assert len(replies) == 1


# ---------------------------------------------------------------------------
# 8: view_dashboard_cb delegates to dashboard handler
# ---------------------------------------------------------------------------

def test_view_dashboard_cb_calls_dashboard():
    """V6: view_dashboard_cb calls dashboard() (not show_dashboard_for_cb)."""
    update, replies = _make_cb_update("onboard:view_dashboard")
    ctx = _ctx()

    mock_dashboard = AsyncMock()
    import projects.polymarket.crusaderbot.bot.handlers.dashboard as dash_mod

    with patch.object(dash_mod, "dashboard", mock_dashboard):
        asyncio.run(view_dashboard_cb(update, ctx))

    mock_dashboard.assert_awaited_once()


# ---------------------------------------------------------------------------
# 9–12: /help — V6 static navigation message (no operator distinction)
# ---------------------------------------------------------------------------

def test_help_shows_navigation_items():
    """MVP help_handler shows navigation button labels, no operator distinction."""
    update, replies = _make_cmd_update()
    ctx = _ctx()
    asyncio.run(help_handler(update, ctx))
    text = " ".join(r[1] for r in replies)
    # MVP UX: label is "Auto-Trade" (hyphenated); "Auto" and "Trade" are both present
    assert "Auto" in text
    assert "Portfolio" in text
    assert "Settings" in text
    # Insights moved off main menu; Emergency replaces Stop Bot
    assert "Emergency" in text


def test_help_shows_emergency_item():
    # MVP UX: Emergency replaces Stop Bot in the main menu
    update, replies = _make_cmd_update()
    ctx = _ctx()
    asyncio.run(help_handler(update, ctx))
    text = " ".join(r[1] for r in replies)
    assert "Emergency" in text


def test_help_shows_start_hint():
    update, replies = _make_cmd_update()
    ctx = _ctx()
    asyncio.run(help_handler(update, ctx))
    text = " ".join(r[1] for r in replies)
    assert "/start" in text


def test_help_sends_exactly_one_message():
    """V6 help_handler is a single static reply."""
    update, replies = _make_cmd_update()
    ctx = _ctx()
    asyncio.run(help_handler(update, ctx))
    assert len(replies) == 1
