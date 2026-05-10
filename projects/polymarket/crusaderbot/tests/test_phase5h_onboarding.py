"""Hermetic tests for Phase 5H first-time onboarding flow.

No real DB, no Telegram API, no network. All external calls are mocked.

Coverage (10 tests):
  Keyboards (no async):
    1  welcome_kb     — has Let's Go and Learn More buttons
    2  faq_kb         — has Got it button
    3  wallet_kb      — has Copy Address and Next buttons
    4  style_picker_kb — has Copy Trade, Auto Trade, Both buttons
    5  deposit_kb     — has Show QR, Copy Address, Skip buttons

  Handler flows (mocked DB + mock Update):
    6  New user /start — shows welcome message, returns ONBOARD_WELCOME
    7  Existing user /start (onboarding_complete=True, ALLOWLISTED)
          — routes to dashboard, returns END
    8  Learn More — shows FAQ, returns ONBOARD_FAQ
    9  Got it from FAQ — re-shows welcome, returns ONBOARD_WELCOME
   10  Let's Go with existing wallet — skips wallet step, goes to ONBOARD_STYLE
   11  Let's Go with no wallet — creates wallet, shows wallet step, returns ONBOARD_WALLET
   12  Copy Address in wallet step — sends address, stays ONBOARD_WALLET
   13  Next in wallet step — shows style picker, returns ONBOARD_STYLE
   14  Style pick (copy_trade) — shows deposit prompt, returns ONBOARD_DEPOSIT
   15  Skip in deposit step — sets onboarding_complete, shows completion, returns END
   16  QR in deposit step — generates QR photo, stays ONBOARD_DEPOSIT
   17  deposit_copy — sends full address, stays ONBOARD_DEPOSIT
   18  Second /start (onboarding_complete=True, BROWSE) — shows welcome back, returns END
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from projects.polymarket.crusaderbot.bot.keyboards.onboarding import (
    deposit_kb,
    faq_kb,
    style_picker_kb,
    wallet_kb,
    welcome_kb,
)
import projects.polymarket.crusaderbot.bot.handlers.onboarding as ob_mod
from projects.polymarket.crusaderbot.bot.handlers.onboarding import (
    ONBOARD_DEPOSIT,
    ONBOARD_FAQ,
    ONBOARD_STYLE,
    ONBOARD_WALLET,
    ONBOARD_WELCOME,
    _entry,
    _deposit_cb,
    _faq_cb,
    _style_cb,
    _wallet_cb,
    _welcome_cb,
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

    async def _reply_photo(photo, **kw):
        replies.append(("photo", photo, kw))

    msg = SimpleNamespace(
        reply_text=AsyncMock(side_effect=_reply_text),
        reply_photo=AsyncMock(side_effect=_reply_photo),
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
    photos: list = []

    async def _reply_text(text, **kw):
        replies.append(("text", text, kw))

    async def _reply_photo(photo, **kw):
        photos.append(photo)
        replies.append(("photo", photo, kw))

    msg = SimpleNamespace(
        reply_text=AsyncMock(side_effect=_reply_text),
        reply_photo=AsyncMock(side_effect=_reply_photo),
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
    ), replies, photos


def _ctx(user_data: dict | None = None):
    ctx = MagicMock()
    ctx.user_data = user_data or {}
    return ctx


# ---------------------------------------------------------------------------
# 1–5: Keyboard purity tests (no async)
# ---------------------------------------------------------------------------

def test_welcome_kb_buttons():
    kb = welcome_kb()
    flat = [btn for row in kb.inline_keyboard for btn in row]
    datas = {b.callback_data for b in flat}
    assert "onboard:lets_go" in datas
    assert "onboard:learn_more" in datas


def test_faq_kb_button():
    kb = faq_kb()
    flat = [btn for row in kb.inline_keyboard for btn in row]
    datas = {b.callback_data for b in flat}
    assert "onboard:got_it" in datas


def test_wallet_kb_buttons():
    kb = wallet_kb()
    flat = [btn for row in kb.inline_keyboard for btn in row]
    datas = {b.callback_data for b in flat}
    assert "onboard:copy_addr" in datas
    assert "onboard:next" in datas


def test_style_picker_kb_buttons():
    kb = style_picker_kb()
    flat = [btn for row in kb.inline_keyboard for btn in row]
    datas = {b.callback_data for b in flat}
    assert "onboard:style:copy_trade" in datas
    assert "onboard:style:auto_trade" in datas
    assert "onboard:style:both" in datas


def test_deposit_kb_buttons():
    kb = deposit_kb()
    flat = [btn for row in kb.inline_keyboard for btn in row]
    datas = {b.callback_data for b in flat}
    assert "onboard:qr" in datas
    assert "onboard:deposit_copy" in datas
    assert "onboard:skip" in datas


# ---------------------------------------------------------------------------
# 6: New user /start shows welcome
# ---------------------------------------------------------------------------

def test_new_user_start_shows_welcome():
    user = _make_user(onboarding_complete=False)
    update, replies = _make_cmd_update()
    ctx = _ctx()

    with (
        patch.object(ob_mod, "upsert_user", AsyncMock(return_value=user)),
        patch.object(ob_mod, "audit") as mock_audit,
        patch.object(ob_mod, "get_wallet", AsyncMock(return_value=None)),
    ):
        mock_audit.write = AsyncMock()
        result = asyncio.run(_entry(update, ctx))

    assert result == ONBOARD_WELCOME
    assert any("Welcome to CrusaderBot" in r[1] for r in replies)
    assert ctx.user_data.get("onboard_user_id") == str(user["id"])


# ---------------------------------------------------------------------------
# 7: Existing user /start (onboarding_complete=True, ALLOWLISTED) → dashboard
# ---------------------------------------------------------------------------

def test_existing_user_start_shows_dashboard():
    user = _make_user(onboarding_complete=True, access_tier=2)
    update, replies = _make_cmd_update()
    ctx = _ctx()

    mock_dashboard = AsyncMock()
    with (
        patch.object(ob_mod, "upsert_user", AsyncMock(return_value=user)),
        patch.object(ob_mod, "audit") as mock_audit,
        patch.object(ob_mod, "get_wallet", AsyncMock(return_value={"deposit_address": "0xABC"})),
        patch("projects.polymarket.crusaderbot.bot.handlers.onboarding.has_tier",
              return_value=True),
        patch("projects.polymarket.crusaderbot.bot.handlers.dashboard.dashboard",
              mock_dashboard),
    ):
        mock_audit.write = AsyncMock()
        # Import dashboard inside the patch context
        import projects.polymarket.crusaderbot.bot.handlers.dashboard as dash_mod
        with patch.object(dash_mod, "dashboard", mock_dashboard):
            result = asyncio.run(_entry(update, ctx))

    assert result == ConversationHandler.END


# ---------------------------------------------------------------------------
# 8: Learn More shows FAQ
# ---------------------------------------------------------------------------

def test_learn_more_shows_faq():
    update, replies, _ = _make_cb_update("onboard:learn_more")
    ctx = _ctx()

    result = asyncio.run(_welcome_cb(update, ctx))

    assert result == ONBOARD_FAQ
    assert any("Frequently Asked Questions" in r[1] for r in replies)


# ---------------------------------------------------------------------------
# 9: Got it from FAQ returns to welcome
# ---------------------------------------------------------------------------

def test_faq_got_it_returns_to_welcome():
    update, replies, _ = _make_cb_update("onboard:got_it")
    ctx = _ctx()

    result = asyncio.run(_faq_cb(update, ctx))

    assert result == ONBOARD_WELCOME
    assert any("Welcome to CrusaderBot" in r[1] for r in replies)


# ---------------------------------------------------------------------------
# 10: Let's Go with existing wallet skips to ONBOARD_STYLE
# ---------------------------------------------------------------------------

def test_lets_go_existing_wallet_skips_to_style():
    uid = uuid4()
    update, replies, _ = _make_cb_update("onboard:lets_go")
    ctx = _ctx({"onboard_user_id": str(uid)})

    with patch.object(ob_mod, "get_wallet",
                      AsyncMock(return_value={"deposit_address": "0xABCD1234EF9"})):
        result = asyncio.run(_welcome_cb(update, ctx))

    assert result == ONBOARD_STYLE
    assert ctx.user_data.get("onboard_addr") == "0xABCD1234EF9"
    assert any("How do you want to trade" in r[1] for r in replies)


# ---------------------------------------------------------------------------
# 11: Let's Go with no wallet creates wallet, shows wallet step
# ---------------------------------------------------------------------------

def test_lets_go_no_wallet_creates_and_shows_wallet_step():
    uid = uuid4()
    addr = "0x45DBabc123cF9"
    update, replies, _ = _make_cb_update("onboard:lets_go")
    ctx = _ctx({"onboard_user_id": str(uid)})

    with (
        patch.object(ob_mod, "get_wallet", AsyncMock(return_value=None)),
        patch.object(ob_mod, "create_wallet_for_user", AsyncMock(return_value=(addr, 1))),
        patch.object(ob_mod, "audit") as mock_audit,
    ):
        mock_audit.write = AsyncMock()
        result = asyncio.run(_welcome_cb(update, ctx))

    assert result == ONBOARD_WALLET
    assert ctx.user_data.get("onboard_addr") == addr
    assert any("Wallet ready" in r[1] for r in replies)


# ---------------------------------------------------------------------------
# 12: Copy Address in wallet step sends address, stays ONBOARD_WALLET
# ---------------------------------------------------------------------------

def test_wallet_copy_address_stays_in_wallet():
    addr = "0x45DBabc123cF9"
    update, replies, _ = _make_cb_update("onboard:copy_addr")
    ctx = _ctx({"onboard_addr": addr})

    result = asyncio.run(_wallet_cb(update, ctx))

    assert result == ONBOARD_WALLET
    assert any(addr in r[1] for r in replies)


# ---------------------------------------------------------------------------
# 13: Next in wallet step goes to ONBOARD_STYLE
# ---------------------------------------------------------------------------

def test_wallet_next_goes_to_style():
    update, replies, _ = _make_cb_update("onboard:next")
    ctx = _ctx({"onboard_addr": "0x45DBabc123cF9"})

    result = asyncio.run(_wallet_cb(update, ctx))

    assert result == ONBOARD_STYLE
    assert any("How do you want to trade" in r[1] for r in replies)


# ---------------------------------------------------------------------------
# 14: Style pick shows deposit prompt, returns ONBOARD_DEPOSIT
# ---------------------------------------------------------------------------

def test_style_pick_shows_deposit_prompt():
    for style in ("copy_trade", "auto_trade", "both"):
        update, replies, _ = _make_cb_update(f"onboard:style:{style}")
        ctx = _ctx({"onboard_addr": "0x45DBabc123cF9", "onboard_user_id": str(uuid4())})

        result = asyncio.run(_style_cb(update, ctx))

        assert result == ONBOARD_DEPOSIT, f"Expected ONBOARD_DEPOSIT for style={style}"
        assert any("Deposit USDC" in r[1] for r in replies)
        assert ctx.user_data.get("onboard_style") == style


# ---------------------------------------------------------------------------
# 15: Skip sets onboarding_complete, shows completion message, returns END
# ---------------------------------------------------------------------------

def test_skip_sets_onboarding_complete_and_ends():
    uid = uuid4()
    update, replies, _ = _make_cb_update("onboard:skip")
    ctx = _ctx({
        "onboard_user_id": str(uid),
        "onboard_style": "copy_trade",
        "onboard_addr": "0x45DBabc123cF9",
    })

    set_mock = AsyncMock()
    with patch.object(ob_mod, "set_onboarding_complete", set_mock):
        result = asyncio.run(_deposit_cb(update, ctx))

    assert result == ConversationHandler.END
    set_mock.assert_awaited_once_with(uid)
    assert any("You're all set" in r[1] for r in replies)


# ---------------------------------------------------------------------------
# 16: Show QR generates photo, stays ONBOARD_DEPOSIT
# ---------------------------------------------------------------------------

def test_show_qr_sends_photo():
    addr = "0x45DBabc123cF9"
    update, replies, photos = _make_cb_update("onboard:qr")
    ctx = _ctx({"onboard_addr": addr, "onboard_user_id": str(uuid4())})

    with patch.object(ob_mod, "_make_qr_bytes", return_value=b"FAKEPNG"):
        result = asyncio.run(_deposit_cb(update, ctx))

    assert result == ONBOARD_DEPOSIT
    assert photos, "Expected a photo to be sent"
    assert photos[0] == b"FAKEPNG"


# ---------------------------------------------------------------------------
# 17: deposit_copy sends full address, stays ONBOARD_DEPOSIT
# ---------------------------------------------------------------------------

def test_deposit_copy_sends_address():
    addr = "0x45DBabc123cF9"
    update, replies, _ = _make_cb_update("onboard:deposit_copy")
    ctx = _ctx({"onboard_addr": addr, "onboard_user_id": str(uuid4())})

    result = asyncio.run(_deposit_cb(update, ctx))

    assert result == ONBOARD_DEPOSIT
    assert any(addr in r[1] for r in replies)


# ---------------------------------------------------------------------------
# 18: Second /start (onboarding_complete=True, BROWSE=1) shows welcome-back
# ---------------------------------------------------------------------------

def test_returning_browse_user_sees_welcome_back():
    user = _make_user(onboarding_complete=True, access_tier=1)
    update, replies = _make_cmd_update()
    ctx = _ctx()

    with (
        patch.object(ob_mod, "upsert_user", AsyncMock(return_value=user)),
        patch.object(ob_mod, "audit") as mock_audit,
        patch.object(ob_mod, "get_wallet",
                     AsyncMock(return_value={"deposit_address": "0xABC"})),
        patch("projects.polymarket.crusaderbot.bot.handlers.onboarding.has_tier",
              return_value=False),
    ):
        mock_audit.write = AsyncMock()
        result = asyncio.run(_entry(update, ctx))

    assert result == ConversationHandler.END
    assert any("Welcome back" in r[1] for r in replies)
