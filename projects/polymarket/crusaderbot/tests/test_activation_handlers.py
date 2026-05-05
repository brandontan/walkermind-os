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


def test_pending_confirm_arms_when_toggle_on_in_live_mode_and_gates_pass():
    update, msg = _make_update(callback=True)
    ctx = _make_ctx()
    passing = SimpleNamespace(ready_for_live=True)
    with patch.object(activation, "upsert_user",
                      AsyncMock(return_value=USER_ROW_OFF)), \
         patch.object(activation, "get_settings_for",
                      AsyncMock(return_value={"trading_mode": "live"})), \
         patch.object(activation.live_checklist, "evaluate",
                      AsyncMock(return_value=passing)):
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


def test_pending_confirm_refuses_to_arm_when_checklist_fails():
    """Codex P1 regression: a failing checklist must NEVER reach CONFIRM.

    Without this fix a Tier 4 user with a failing 2FA / deposit / etc
    gate could still type CONFIRM and route a real CLOB order, because
    /setup only checks Tier+global flags and the risk gate's live
    selection only checks globals + tier + trading_mode.
    """
    update, msg = _make_update(callback=True)
    ctx = _make_ctx()
    failing = SimpleNamespace(ready_for_live=False)
    with patch.object(activation, "upsert_user",
                      AsyncMock(return_value=USER_ROW_OFF)), \
         patch.object(activation, "get_settings_for",
                      AsyncMock(return_value={"trading_mode": "live"})), \
         patch.object(activation.live_checklist, "evaluate",
                      AsyncMock(return_value=failing)), \
         patch.object(activation.live_checklist, "render_telegram",
                      return_value="🔒 fix list"):
        result = asyncio.run(
            activation.autotrade_toggle_pending_confirm(update, ctx),
        )
    # Toggle is fully consumed by this handler — caller must NOT flip
    # auto_trade_on on its own path.
    assert result is True
    # CONFIRM must NOT have been armed.
    assert activation.AWAITING_KEY not in ctx.user_data
    # The fix list is shown to the user.
    msg.reply_text.assert_awaited_once()
    assert msg.reply_text.call_args[0][0] == "🔒 fix list"


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
    passing = SimpleNamespace(ready_for_live=True)
    with patch.object(activation, "upsert_user",
                      AsyncMock(return_value=USER_ROW_OFF)), \
         patch.object(activation.live_checklist, "evaluate",
                      AsyncMock(return_value=passing)), \
         patch.object(activation, "set_auto_trade",
                      AsyncMock()) as flip:
        consumed = asyncio.run(activation.text_input(update, ctx))
    assert consumed is True
    flip.assert_awaited_once_with(USER_ROW_OFF["id"], True)
    # awaiting flag cleared.
    assert activation.AWAITING_KEY not in ctx.user_data


def test_text_input_confirm_rejects_when_checklist_degraded_between_prompt_and_reply():
    """Codex P1 defense-in-depth: even after CONFIRM is armed, the gate
    state can change before the reply arrives (operator flips
    ENABLE_LIVE_TRADING off, deposit reverted, 2FA revoked). The
    CONFIRM reply must re-run the checklist and refuse the flip.
    """
    update, msg = _make_update(text="CONFIRM")
    ctx = _make_ctx()
    ctx.user_data[activation.AWAITING_KEY] = activation.AWAITING_LIVE_CONFIRM
    failing = SimpleNamespace(ready_for_live=False)
    with patch.object(activation, "upsert_user",
                      AsyncMock(return_value=USER_ROW_OFF)), \
         patch.object(activation.live_checklist, "evaluate",
                      AsyncMock(return_value=failing)), \
         patch.object(activation.live_checklist, "render_telegram",
                      return_value="🔒 fix list"), \
         patch.object(activation, "set_auto_trade",
                      AsyncMock()) as flip:
        consumed = asyncio.run(activation.text_input(update, ctx))
    assert consumed is True
    flip.assert_not_awaited()
    msg.reply_text.assert_awaited_once()
    assert msg.reply_text.call_args[0][0] == "🔒 fix list"


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


# ---------- /setup paper→live mode switch (Codex P1 follow-up) ---------------


def test_trading_mode_live_pending_confirm_arms_when_checklist_passes():
    """Codex P1 regression: switching trading_mode to live via /setup is
    itself a live-activation event for users with auto_trade_on=true.
    The picker must run the full checklist and arm CONFIRM rather than
    silently writing trading_mode='live'.
    """
    update, msg = _make_update(callback=True)
    ctx = _make_ctx()
    passing = SimpleNamespace(ready_for_live=True)
    with patch.object(activation, "upsert_user",
                      AsyncMock(return_value=USER_ROW_OFF)), \
         patch.object(activation.live_checklist, "evaluate",
                      AsyncMock(return_value=passing)):
        result = asyncio.run(
            activation.trading_mode_live_pending_confirm(update, ctx),
        )
    assert result is True
    assert ctx.user_data == {
        activation.AWAITING_KEY:
            activation.AWAITING_TRADING_MODE_LIVE_CONFIRM,
    }
    msg.reply_text.assert_awaited_once()
    sent_text = msg.reply_text.call_args[0][0]
    assert "CONFIRM" in sent_text
    assert "LIVE" in sent_text


def test_trading_mode_live_pending_confirm_refuses_when_checklist_fails():
    """If any activation gate fails, the /setup live picker must NOT
    arm CONFIRM and must NOT write trading_mode='live'. Show the fix
    list instead.
    """
    update, msg = _make_update(callback=True)
    ctx = _make_ctx()
    failing = SimpleNamespace(ready_for_live=False)
    with patch.object(activation, "upsert_user",
                      AsyncMock(return_value=USER_ROW_OFF)), \
         patch.object(activation.live_checklist, "evaluate",
                      AsyncMock(return_value=failing)), \
         patch.object(activation.live_checklist, "render_telegram",
                      return_value="🔒 fix list"):
        result = asyncio.run(
            activation.trading_mode_live_pending_confirm(update, ctx),
        )
    # Picker is fully consumed, no CONFIRM armed.
    assert result is True
    assert activation.AWAITING_KEY not in ctx.user_data
    msg.reply_text.assert_awaited_once()
    assert msg.reply_text.call_args[0][0] == "🔒 fix list"


def test_text_input_confirm_for_trading_mode_writes_live():
    update, msg = _make_update(text="CONFIRM")
    ctx = _make_ctx()
    ctx.user_data[activation.AWAITING_KEY] = (
        activation.AWAITING_TRADING_MODE_LIVE_CONFIRM
    )
    passing = SimpleNamespace(ready_for_live=True)
    with patch.object(activation, "upsert_user",
                      AsyncMock(return_value=USER_ROW_OFF)), \
         patch.object(activation.live_checklist, "evaluate",
                      AsyncMock(return_value=passing)), \
         patch.object(activation, "update_settings",
                      AsyncMock()) as upd, \
         patch.object(activation, "set_auto_trade",
                      AsyncMock()) as flip:
        consumed = asyncio.run(activation.text_input(update, ctx))
    assert consumed is True
    upd.assert_awaited_once_with(USER_ROW_OFF["id"], trading_mode="live")
    # The trading-mode CONFIRM path must NOT also flip auto_trade_on —
    # mode and engagement are separate user actions.
    flip.assert_not_awaited()
    assert activation.AWAITING_KEY not in ctx.user_data


def test_text_input_trading_mode_confirm_re_checks_checklist_before_writing():
    """Defense-in-depth: a guard could have degraded between the picker
    and the CONFIRM reply (operator flips ENABLE_LIVE_TRADING off, etc).
    update_settings must NOT be called when the re-check fails.
    """
    update, msg = _make_update(text="CONFIRM")
    ctx = _make_ctx()
    ctx.user_data[activation.AWAITING_KEY] = (
        activation.AWAITING_TRADING_MODE_LIVE_CONFIRM
    )
    failing = SimpleNamespace(ready_for_live=False)
    with patch.object(activation, "upsert_user",
                      AsyncMock(return_value=USER_ROW_OFF)), \
         patch.object(activation.live_checklist, "evaluate",
                      AsyncMock(return_value=failing)), \
         patch.object(activation.live_checklist, "render_telegram",
                      return_value="🔒 fix list"), \
         patch.object(activation, "update_settings",
                      AsyncMock()) as upd:
        consumed = asyncio.run(activation.text_input(update, ctx))
    assert consumed is True
    upd.assert_not_awaited()
    msg.reply_text.assert_awaited_once()
    assert msg.reply_text.call_args[0][0] == "🔒 fix list"


def test_dispatcher_routes_activation_confirm_before_setup():
    """Codex P1 regression: the dispatcher's _text_router must invoke
    activation.text_input BEFORE setup.text_input so the CONFIRM reply
    reaches activation. Setup.text_input pops unknown awaiting values
    when it returns False — if it ran first, the live-activation
    awaiting flag would be cleared before activation sees it and the
    auto_trade_on / trading_mode flip would be lost.
    """
    import asyncio as _asyncio

    from projects.polymarket.crusaderbot.bot import dispatcher

    update, msg = _make_update(text="CONFIRM")
    ctx = _make_ctx()
    ctx.user_data[activation.AWAITING_KEY] = activation.AWAITING_LIVE_CONFIRM

    passing = SimpleNamespace(ready_for_live=True)
    with patch.object(activation, "upsert_user",
                      AsyncMock(return_value=USER_ROW_OFF)), \
         patch.object(activation.live_checklist, "evaluate",
                      AsyncMock(return_value=passing)), \
         patch.object(activation, "set_auto_trade",
                      AsyncMock()) as flip:
        _asyncio.run(dispatcher._text_router(update, ctx))
    flip.assert_awaited_once_with(USER_ROW_OFF["id"], True)
    assert activation.AWAITING_KEY not in ctx.user_data


def test_setup_text_input_does_not_pop_activation_awaiting():
    """Codex P1 defense-in-depth: even if setup.text_input is called
    with an activation awaiting value (e.g. by another future consumer),
    it must NOT pop the value from ctx.user_data — that would silently
    swallow a live-activation CONFIRM reply.
    """
    import asyncio as _asyncio

    from projects.polymarket.crusaderbot.bot.handlers import setup

    update, msg = _make_update(text="CONFIRM")
    ctx = _make_ctx()
    ctx.user_data["awaiting"] = activation.AWAITING_LIVE_CONFIRM

    with patch.object(setup, "upsert_user",
                      AsyncMock(return_value=USER_ROW_OFF)):
        consumed = _asyncio.run(setup.text_input(update, ctx))
    assert consumed is False
    # The activation awaiting flag must survive setup.text_input so the
    # next consumer in the dispatcher chain can see it.
    assert ctx.user_data["awaiting"] == activation.AWAITING_LIVE_CONFIRM


def test_text_input_trading_mode_wrong_reply_cancels():
    update, msg = _make_update(text="cancel")
    ctx = _make_ctx()
    ctx.user_data[activation.AWAITING_KEY] = (
        activation.AWAITING_TRADING_MODE_LIVE_CONFIRM
    )
    with patch.object(activation, "update_settings",
                      AsyncMock()) as upd:
        consumed = asyncio.run(activation.text_input(update, ctx))
    assert consumed is True
    upd.assert_not_awaited()
    msg.reply_text.assert_awaited_once()
    body = msg.reply_text.call_args[0][0]
    assert "Cancelled" in body
    assert "Trading mode unchanged" in body
    assert activation.AWAITING_KEY not in ctx.user_data
