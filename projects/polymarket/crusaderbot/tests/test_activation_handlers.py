"""Hermetic tests for R12 activation Telegram handlers.

Coverage:

  * /live_checklist routes through LiveChecklist.evaluate + render_telegram
  * /summary_on toggles the opt-in flag ON
  * /summary_off toggles the opt-in flag OFF
  * autotrade_toggle_pending_confirm — armed when toggle ON in live mode
  * autotrade_toggle_pending_confirm — passes through when paper mode
  * autotrade_toggle_pending_confirm — passes through when toggling OFF
  * text_input — typed CONFIRM flips auto_trade_on
  * text_input — wrong reply cancels and clears the awaiting flag
  * text_input — no awaiting flag returns False without side effects
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from projects.polymarket.crusaderbot.bot.handlers import activation


USER_ROW_OFF = {
    "id": uuid4(), "telegram_user_id": 5001, "username": "u",
    "auto_trade_on": False, "access_tier": 4, "paused": False,
}
USER_ROW_ON = {**USER_ROW_OFF, "auto_trade_on": True}


def _make_update(text: str = "", callback: bool = False):
    msg = SimpleNamespace(
        text=text,
        reply_text=AsyncMock(),
    )
    eff_user = SimpleNamespace(id=5001, username="u")
    if callback:
        return SimpleNamespace(
            effective_user=eff_user,
            message=None,
            callback_query=SimpleNamespace(
                message=msg,
                answer=AsyncMock(),
                data="autotrade:toggle",
            ),
        ), msg
    return SimpleNamespace(
        effective_user=eff_user,
        message=msg,
        callback_query=None,
    ), msg


def _make_ctx() -> SimpleNamespace:
    return SimpleNamespace(user_data={})


# ---------- /live_checklist -------------------------------------------------


def test_live_checklist_command_renders_evaluator_result():
    update, msg = _make_update()
    ctx = _make_ctx()

    fake_result = SimpleNamespace(passed=False)
    with patch.object(activation, "upsert_user",
                      AsyncMock(return_value=USER_ROW_OFF)), \
         patch.object(activation.live_checklist, "evaluate",
                      AsyncMock(return_value=fake_result)) as eva, \
         patch.object(activation.live_checklist, "render_telegram",
                      return_value="🔒 not ready") as render:
        asyncio.run(activation.live_checklist_command(update, ctx))
    eva.assert_awaited_once_with(USER_ROW_OFF["id"])
    render.assert_called_once_with(fake_result)
    msg.reply_text.assert_awaited_once()
    args, kwargs = msg.reply_text.call_args
    assert args[0] == "🔒 not ready"


# ---------- /summary_on /summary_off ----------------------------------------


def test_summary_on_command_persists_enabled():
    update, msg = _make_update()
    ctx = _make_ctx()
    with patch.object(activation, "upsert_user",
                      AsyncMock(return_value=USER_ROW_OFF)), \
         patch.object(activation.daily_pnl_summary, "set_summary_enabled",
                      AsyncMock()) as set_flag:
        asyncio.run(activation.summary_on_command(update, ctx))
    set_flag.assert_awaited_once_with(USER_ROW_OFF["id"], True)
    msg.reply_text.assert_awaited_once()


def test_summary_off_command_persists_disabled():
    update, msg = _make_update()
    ctx = _make_ctx()
    with patch.object(activation, "upsert_user",
                      AsyncMock(return_value=USER_ROW_OFF)), \
         patch.object(activation.daily_pnl_summary, "set_summary_enabled",
                      AsyncMock()) as set_flag:
        asyncio.run(activation.summary_off_command(update, ctx))
    set_flag.assert_awaited_once_with(USER_ROW_OFF["id"], False)
    msg.reply_text.assert_awaited_once()


# ---------- autotrade_toggle_pending_confirm --------------------------------


def test_pending_confirm_arms_when_toggle_on_in_live_mode():
    update, msg = _make_update(callback=True)
    ctx = _make_ctx()
    with patch.object(activation, "upsert_user",
                      AsyncMock(return_value=USER_ROW_OFF)), \
         patch.object(activation, "get_settings_for",
                      AsyncMock(return_value={"trading_mode": "live"})):
        result = asyncio.run(
            activation.autotrade_toggle_pending_confirm(update, ctx),
        )
    assert result is True
    assert ctx.user_data == {
        activation.AWAITING_KEY: activation.AWAITING_LIVE_CONFIRM,
    }
    msg.reply_text.assert_awaited_once()
    sent_text = msg.reply_text.call_args[0][0]
    assert "CONFIRM" in sent_text


def test_pending_confirm_passes_through_when_paper_mode():
    update, _msg = _make_update(callback=True)
    ctx = _make_ctx()
    with patch.object(activation, "upsert_user",
                      AsyncMock(return_value=USER_ROW_OFF)), \
         patch.object(activation, "get_settings_for",
                      AsyncMock(return_value={"trading_mode": "paper"})):
        result = asyncio.run(
            activation.autotrade_toggle_pending_confirm(update, ctx),
        )
    assert result is False
    assert activation.AWAITING_KEY not in ctx.user_data


def test_pending_confirm_passes_through_when_toggling_off():
    update, _msg = _make_update(callback=True)
    ctx = _make_ctx()
    with patch.object(activation, "upsert_user",
                      AsyncMock(return_value=USER_ROW_ON)), \
         patch.object(activation, "get_settings_for",
                      AsyncMock(return_value={"trading_mode": "live"})):
        # auto_trade_on already True → toggle moves to OFF, no CONFIRM
        # gate.
        result = asyncio.run(
            activation.autotrade_toggle_pending_confirm(update, ctx),
        )
    assert result is False


# ---------- text_input (CONFIRM reply) --------------------------------------


def test_text_input_confirm_flips_auto_trade_on():
    update, msg = _make_update(text="CONFIRM")
    ctx = _make_ctx()
    ctx.user_data[activation.AWAITING_KEY] = activation.AWAITING_LIVE_CONFIRM
    with patch.object(activation, "upsert_user",
                      AsyncMock(return_value=USER_ROW_OFF)), \
         patch.object(activation, "set_auto_trade",
                      AsyncMock()) as flip:
        consumed = asyncio.run(activation.text_input(update, ctx))
    assert consumed is True
    flip.assert_awaited_once_with(USER_ROW_OFF["id"], True)
    # awaiting flag cleared.
    assert activation.AWAITING_KEY not in ctx.user_data


def test_text_input_wrong_reply_cancels_and_clears():
    update, msg = _make_update(text="cancel")
    ctx = _make_ctx()
    ctx.user_data[activation.AWAITING_KEY] = activation.AWAITING_LIVE_CONFIRM
    with patch.object(activation, "set_auto_trade",
                      AsyncMock()) as flip:
        consumed = asyncio.run(activation.text_input(update, ctx))
    assert consumed is True
    flip.assert_not_awaited()
    msg.reply_text.assert_awaited_once()
    assert "Cancelled" in msg.reply_text.call_args[0][0]
    assert activation.AWAITING_KEY not in ctx.user_data


def test_text_input_returns_false_when_no_awaiting():
    update, _msg = _make_update(text="any text")
    ctx = _make_ctx()
    consumed = asyncio.run(activation.text_input(update, ctx))
    assert consumed is False


def test_text_input_lowercase_confirm_does_not_match():
    """CONFIRM is case-sensitive — typing 'confirm' must NOT enable live."""
    update, msg = _make_update(text="confirm")
    ctx = _make_ctx()
    ctx.user_data[activation.AWAITING_KEY] = activation.AWAITING_LIVE_CONFIRM
    with patch.object(activation, "set_auto_trade",
                      AsyncMock()) as flip:
        consumed = asyncio.run(activation.text_input(update, ctx))
    assert consumed is True
    flip.assert_not_awaited()
