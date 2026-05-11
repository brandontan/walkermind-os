"""Hermetic tests for onboarding polish — Track L.

No real DB, no Telegram API, no network. All external calls are mocked.

Coverage (15 tests):
  Keyboards (no async):
    1  get_started_kb    — has Get Started button
    2  mode_select_kb    — has Paper Trading and Live Trading buttons
    3  paper_complete_kb — has View Dashboard button

  Handler flows (mocked DB + mock Update):
    4  New user /start   — shows welcome text, returns ONBOARD_WELCOME
    5  Existing user /start (ALLOWLISTED) — routes to dashboard, returns END
    6  Returning BROWSE user /start — shows welcome back, returns END
    7  Get Started callback — shows mode selection, returns ONBOARD_MODE
    8  Paper mode selected — marks onboarding_complete, shows paper confirmation, END
    9  Paper mode selected without user_id in ctx — still shows confirmation, END
   10  Live mode selected  — shows live redirect text, END
   11  view_dashboard_cb   — delegates to dashboard handler

  /help (mocked operator check):
   12  /help non-operator — shows TRADING, PORTFOLIO, SETTINGS; no ADMIN section
   13  /help operator     — shows TRADING, PORTFOLIO, SETTINGS, ADMIN section
   14  /help TRADING category — contains /scan, /positions, /close, /pnl
   15  /help PORTFOLIO category — contains /chart, /insights, /trades
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
    ONBOARD_MODE,
    ONBOARD_WELCOME,
    _entry,
    _get_started_cb,
    _mode_cb,
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

    msg = SimpleNamespace(
        reply_text=AsyncMock(side_effect=_reply_text),
    )
    cq = SimpleNamespace(
        data=callback_data,
        answer=AsyncMock(),
        message=msg,
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
    assert any("Welcome to CrusaderBot" in r[1] for r in replies)
    assert ctx.user_data.get("onboard_user_id") == str(user["id"])


# ---------------------------------------------------------------------------
# 5: Existing user /start (ALLOWLISTED) → dashboard
# ---------------------------------------------------------------------------

def test_existing_user_start_routes_to_dashboard():
    user = _make_user(onboarding_complete=True, access_tier=2)
    update, replies = _make_cmd_update()
    ctx = _ctx()

    mock_dashboard = AsyncMock()
    import projects.polymarket.crusaderbot.bot.handlers.dashboard as dash_mod

    with (
        patch.object(ob_mod, "upsert_user", AsyncMock(return_value=user)),
        patch.object(ob_mod, "audit") as mock_audit,
        patch.object(ob_mod, "get_wallet", AsyncMock(return_value=None)),
        patch.object(ob_mod, "get_or_create_referral_code", AsyncMock()),
        patch.object(ob_mod, "parse_ref_param", return_value=None),
        patch.object(ob_mod, "has_tier", return_value=True),
        patch.object(dash_mod, "dashboard", mock_dashboard),
    ):
        mock_audit.write = AsyncMock()
        result = asyncio.run(_entry(update, ctx))

    assert result == ConversationHandler.END


# ---------------------------------------------------------------------------
# 6: Returning BROWSE user /start shows welcome back
# ---------------------------------------------------------------------------

def test_returning_browse_user_sees_welcome_back():
    user = _make_user(onboarding_complete=True, access_tier=1)
    update, replies = _make_cmd_update()
    ctx = _ctx()

    with (
        patch.object(ob_mod, "upsert_user", AsyncMock(return_value=user)),
        patch.object(ob_mod, "audit") as mock_audit,
        patch.object(ob_mod, "get_wallet", AsyncMock(return_value=None)),
        patch.object(ob_mod, "get_or_create_referral_code", AsyncMock()),
        patch.object(ob_mod, "parse_ref_param", return_value=None),
        patch.object(ob_mod, "has_tier", return_value=False),
    ):
        mock_audit.write = AsyncMock()
        result = asyncio.run(_entry(update, ctx))

    assert result == ConversationHandler.END
    assert any("Welcome back" in r[1] for r in replies)


# ---------------------------------------------------------------------------
# 7: Get Started callback shows mode selection
# ---------------------------------------------------------------------------

def test_get_started_shows_mode_selection():
    update, replies = _make_cb_update("onboard:get_started")
    ctx = _ctx()

    result = asyncio.run(_get_started_cb(update, ctx))

    assert result == ONBOARD_MODE
    assert any("Choose your trading mode" in r[1] for r in replies)


# ---------------------------------------------------------------------------
# 8: Paper mode selected — marks complete, shows confirmation, END
# ---------------------------------------------------------------------------

def test_mode_paper_marks_complete_and_shows_confirmation():
    uid = uuid4()
    update, replies = _make_cb_update("onboard:mode_paper")
    ctx = _ctx({"onboard_user_id": str(uid)})

    set_mock = AsyncMock()
    with patch.object(ob_mod, "set_onboarding_complete", set_mock):
        result = asyncio.run(_mode_cb(update, ctx))

    assert result == ConversationHandler.END
    set_mock.assert_awaited_once_with(uid)
    assert any("Paper mode activated" in r[1] for r in replies)


# ---------------------------------------------------------------------------
# 9: Paper mode without user_id in ctx — still shows confirmation, END
# ---------------------------------------------------------------------------

def test_mode_paper_without_user_id_still_shows_confirmation():
    update, replies = _make_cb_update("onboard:mode_paper")
    ctx = _ctx()  # no onboard_user_id

    result = asyncio.run(_mode_cb(update, ctx))

    assert result == ConversationHandler.END
    assert any("Paper mode activated" in r[1] for r in replies)


# ---------------------------------------------------------------------------
# 10: Live mode selected — shows redirect, END
# ---------------------------------------------------------------------------

def test_mode_live_shows_redirect_and_ends():
    update, replies = _make_cb_update("onboard:mode_live")
    ctx = _ctx()

    result = asyncio.run(_mode_cb(update, ctx))

    assert result == ConversationHandler.END
    assert any("enable_live" in r[1] or "Live Trading" in r[1] for r in replies)


# ---------------------------------------------------------------------------
# 11: view_dashboard_cb delegates to dashboard handler
# ---------------------------------------------------------------------------

def test_view_dashboard_cb_calls_show_dashboard_for_cb():
    update, replies = _make_cb_update("onboard:view_dashboard")
    ctx = _ctx()

    mock_show = AsyncMock()
    import projects.polymarket.crusaderbot.bot.handlers.dashboard as dash_mod

    with patch.object(dash_mod, "show_dashboard_for_cb", mock_show):
        asyncio.run(view_dashboard_cb(update, ctx))

    mock_show.assert_awaited_once()


# ---------------------------------------------------------------------------
# 12: /help non-operator — no ADMIN section
# ---------------------------------------------------------------------------

def test_help_non_operator_hides_admin():
    update, replies = _make_cmd_update(tg_user_id=99999)
    ctx = _ctx()

    mock_settings = MagicMock()
    mock_settings.OPERATOR_CHAT_ID = 11111  # different from tg_user_id

    with patch.object(ob_mod, "get_settings", return_value=mock_settings):
        asyncio.run(help_handler(update, ctx))

    text = " ".join(r[1] for r in replies)
    assert "TRADING" in text
    assert "PORTFOLIO" in text
    assert "SETTINGS" in text
    assert "ADMIN" not in text


# ---------------------------------------------------------------------------
# 13: /help operator — shows ADMIN section
# ---------------------------------------------------------------------------

def test_help_operator_shows_admin():
    op_id = 11111
    update, replies = _make_cmd_update(tg_user_id=op_id)
    ctx = _ctx()

    mock_settings = MagicMock()
    mock_settings.OPERATOR_CHAT_ID = op_id

    with patch.object(ob_mod, "get_settings", return_value=mock_settings):
        asyncio.run(help_handler(update, ctx))

    text = " ".join(r[1] for r in replies)
    assert "ADMIN" in text
    assert "/admin" in text


# ---------------------------------------------------------------------------
# 14: /help TRADING category contains expected commands
# ---------------------------------------------------------------------------

def test_help_trading_category_commands():
    update, replies = _make_cmd_update()
    ctx = _ctx()

    mock_settings = MagicMock()
    mock_settings.OPERATOR_CHAT_ID = 99999  # non-operator

    with patch.object(ob_mod, "get_settings", return_value=mock_settings):
        asyncio.run(help_handler(update, ctx))

    text = " ".join(r[1] for r in replies)
    assert "/scan" in text
    assert "/positions" in text
    assert "/close" in text
    assert "/pnl" in text


# ---------------------------------------------------------------------------
# 15: /help PORTFOLIO category contains expected commands
# ---------------------------------------------------------------------------

def test_help_portfolio_category_commands():
    update, replies = _make_cmd_update()
    ctx = _ctx()

    mock_settings = MagicMock()
    mock_settings.OPERATOR_CHAT_ID = 99999

    with patch.object(ob_mod, "get_settings", return_value=mock_settings):
        asyncio.run(help_handler(update, ctx))

    text = " ".join(r[1] for r in replies)
    assert "/chart" in text
    assert "/insights" in text
    assert "/trades" in text
