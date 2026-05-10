"""Hermetic tests for Phase 5J emergency menu redesign.

No DB, no Telegram network calls. Handler modules are exercised by patching
``users`` helpers, ``audit``, ``notifications``, and position-registry so each
scenario verifies both the user-visible flow and the persistence calls.

Coverage (13 tests):
  1-2.  Keyboards: emergency_confirm + emergency_feedback callback shapes
  3-5.  Confirmation dialog rendered for all 3 actions (pause / pause_close / lock)
  6.    Cancel/back returns to emergency intro menu
  7.    Confirm lock calls set_locked(True) and set_paused(True)
  8.    Confirm pause calls set_paused(True) only — set_locked NOT called
  9.    Locked user blocked from preset:resume
  10.   Locked user blocked from preset:activate
  11.   Operator /unlock clears locked flag and notifies user
  12.   Non-operator /unlock silently rejected — set_locked never called
  13.   /unlock returns "not found" for unknown username
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from projects.polymarket.crusaderbot.bot.handlers import admin as admin_h
from projects.polymarket.crusaderbot.bot.handlers import emergency as emg_h
from projects.polymarket.crusaderbot.bot.handlers import presets as presets_h
from projects.polymarket.crusaderbot.bot.keyboards import (
    emergency_confirm,
    emergency_feedback,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_user(uid=None, *, locked=False, auto_trade_on=False, paused=False,
               access_tier=2):
    return {
        "id": uid or uuid4(),
        "telegram_user_id": 99,
        "username": "tester",
        "access_tier": access_tier,
        "auto_trade_on": auto_trade_on,
        "paused": paused,
        "locked": locked,
    }


def _make_cb_update(callback_data: str):
    """Build an Update-like namespace wired for an inline callback."""
    edits: list[tuple] = []
    replies: list[str] = []

    async def _edit(text, **kw):
        edits.append((text, kw))

    async def _reply_txt(text, **kw):
        replies.append(text)

    msg = SimpleNamespace(reply_text=AsyncMock(side_effect=_reply_txt))
    cq = SimpleNamespace(
        data=callback_data,
        answer=AsyncMock(),
        message=msg,
        edit_message_text=AsyncMock(side_effect=_edit),
    )
    update = SimpleNamespace(
        message=None,
        callback_query=cq,
        effective_user=SimpleNamespace(id=99, username="tester"),
    )
    return update, edits, replies


def _make_cmd_update():
    """Build an Update-like namespace wired for a /command."""
    replies: list[str] = []

    async def _reply_txt(text, **kw):
        replies.append(text)

    msg = SimpleNamespace(reply_text=AsyncMock(side_effect=_reply_txt))
    update = SimpleNamespace(
        message=msg,
        callback_query=None,
        effective_user=SimpleNamespace(id=99, username="operator"),
    )
    return update, replies


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# 1-2. Keyboard shapes
# ---------------------------------------------------------------------------

def test_emergency_confirm_callback_data():
    kb = emergency_confirm("pause")
    all_data = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "emergency:confirm:pause" in all_data
    assert "emergency:cancel" in all_data


def test_emergency_feedback_callback_data():
    kb = emergency_feedback()
    all_data = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "dashboard:main" in all_data
    assert "dashboard:autotrade" in all_data


# ---------------------------------------------------------------------------
# 3-5. Confirmation dialog renders for each action
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("action", ["pause", "pause_close", "lock"])
def test_confirm_dialog_shown_for_action(action):
    update, edits, _ = _make_cb_update(f"emergency:{action}")
    _run(emg_h.emergency_callback(update, ctx=SimpleNamespace()))
    assert len(edits) == 1, "edit_message_text must be called exactly once"
    _, kw = edits[0]
    kb = kw.get("reply_markup")
    assert kb is not None
    all_data = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert f"emergency:confirm:{action}" in all_data
    assert "emergency:cancel" in all_data


# ---------------------------------------------------------------------------
# 6. Cancel returns to emergency intro menu
# ---------------------------------------------------------------------------

def test_cancel_returns_to_emergency_menu():
    update, edits, _ = _make_cb_update("emergency:cancel")
    _run(emg_h.emergency_callback(update, ctx=SimpleNamespace()))
    assert len(edits) == 1
    _, kw = edits[0]
    kb = kw.get("reply_markup")
    assert kb is not None
    all_data = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "emergency:pause" in all_data
    assert "emergency:back" in all_data


# ---------------------------------------------------------------------------
# 7. Confirm lock → set_paused(True) AND set_locked(True)
# ---------------------------------------------------------------------------

def test_confirm_lock_sets_both_paused_and_locked(monkeypatch):
    uid = uuid4()
    user = _make_user(uid)
    monkeypatch.setattr(emg_h, "upsert_user", AsyncMock(return_value=user))
    set_paused = AsyncMock()
    set_locked = AsyncMock()
    audit_write = AsyncMock()
    monkeypatch.setattr(emg_h, "set_paused", set_paused)
    monkeypatch.setattr(emg_h, "set_locked", set_locked)
    monkeypatch.setattr(emg_h.audit, "write", audit_write)

    update, edits, _ = _make_cb_update("emergency:confirm:lock")
    _run(emg_h.emergency_callback(update, ctx=SimpleNamespace()))

    set_paused.assert_awaited_once_with(uid, True)
    set_locked.assert_awaited_once_with(uid, True)
    audit_write.assert_awaited_once()
    assert audit_write.call_args.kwargs["action"] == "self_lock_account"
    assert len(edits) == 1


# ---------------------------------------------------------------------------
# 8. Confirm pause → set_paused only; set_locked NOT called
# ---------------------------------------------------------------------------

def test_confirm_pause_does_not_touch_locked(monkeypatch):
    uid = uuid4()
    user = _make_user(uid)
    monkeypatch.setattr(emg_h, "upsert_user", AsyncMock(return_value=user))
    set_paused = AsyncMock()
    set_locked = AsyncMock()
    audit_write = AsyncMock()
    monkeypatch.setattr(emg_h, "set_paused", set_paused)
    monkeypatch.setattr(emg_h, "set_locked", set_locked)
    monkeypatch.setattr(emg_h.audit, "write", audit_write)

    update, edits, _ = _make_cb_update("emergency:confirm:pause")
    _run(emg_h.emergency_callback(update, ctx=SimpleNamespace()))

    set_paused.assert_awaited_once_with(uid, True)
    set_locked.assert_not_awaited()


# ---------------------------------------------------------------------------
# 9. Locked user blocked from preset:resume
# ---------------------------------------------------------------------------

def test_locked_user_blocked_from_preset_resume(monkeypatch):
    uid = uuid4()
    user = _make_user(uid, locked=True, paused=True)
    monkeypatch.setattr(presets_h, "upsert_user", AsyncMock(return_value=user))
    set_paused = AsyncMock()
    monkeypatch.setattr(presets_h, "set_paused", set_paused)

    update, edits, replies = _make_cb_update("preset:resume")
    _run(presets_h.preset_callback(update, ctx=SimpleNamespace(user_data={})))

    set_paused.assert_not_awaited()
    assert any("locked" in r.lower() for r in replies), (
        "Expected a 'locked' message in replies"
    )


# ---------------------------------------------------------------------------
# 10. Locked user blocked from preset:activate
# ---------------------------------------------------------------------------

def test_locked_user_blocked_from_preset_activate(monkeypatch):
    uid = uuid4()
    user = _make_user(uid, locked=True)
    monkeypatch.setattr(presets_h, "upsert_user", AsyncMock(return_value=user))
    update_settings = AsyncMock()
    set_auto_trade = AsyncMock()
    set_paused = AsyncMock()
    monkeypatch.setattr(presets_h, "update_settings", update_settings)
    monkeypatch.setattr(presets_h, "set_auto_trade", set_auto_trade)
    monkeypatch.setattr(presets_h, "set_paused", set_paused)
    monkeypatch.setattr(presets_h, "get_settings_for", AsyncMock(return_value={
        "active_preset": None, "trading_mode": "paper",
    }))

    update, edits, replies = _make_cb_update("preset:activate:signal_sniper")
    _run(presets_h.preset_callback(update, ctx=SimpleNamespace(user_data={})))

    update_settings.assert_not_awaited()
    set_auto_trade.assert_not_awaited()
    set_paused.assert_not_awaited()
    assert any("locked" in r.lower() for r in replies), (
        "Expected a 'locked' message in replies"
    )


# ---------------------------------------------------------------------------
# 11. Operator /unlock clears locked flag + notifies user
# ---------------------------------------------------------------------------

def test_operator_unlock_clears_locked_flag(monkeypatch):
    uid = uuid4()
    user = _make_user(uid, locked=True)
    monkeypatch.setattr(admin_h, "get_user_by_username", AsyncMock(return_value=user))
    audit_write = AsyncMock()
    notify = AsyncMock()
    monkeypatch.setattr(admin_h.audit, "write", audit_write)
    monkeypatch.setattr(admin_h.notifications, "send", notify)

    update, replies = _make_cmd_update()
    ctx = SimpleNamespace(args=["@tester"])

    with patch.object(admin_h, "_is_operator", return_value=True), \
         patch("projects.polymarket.crusaderbot.users.set_locked",
               AsyncMock()) as mock_sl:
        _run(admin_h.unlock_command(update, ctx))

    mock_sl.assert_awaited_once_with(uid, False)
    audit_write.assert_awaited_once()
    assert audit_write.call_args.kwargs["action"] == "operator_unlock"
    notify.assert_awaited_once()
    assert any("unlock" in r.lower() for r in replies)


# ---------------------------------------------------------------------------
# 12. Non-operator /unlock silently rejected
# ---------------------------------------------------------------------------

def test_non_operator_unlock_silently_rejected(monkeypatch):
    update = SimpleNamespace(
        message=None,
        callback_query=None,
        effective_user=SimpleNamespace(id=12345, username="hacker"),
    )
    ctx = SimpleNamespace(args=["@tester"])

    with patch.object(admin_h, "_is_operator", return_value=False), \
         patch("projects.polymarket.crusaderbot.users.set_locked",
               AsyncMock()) as mock_sl:
        _run(admin_h.unlock_command(update, ctx))

    mock_sl.assert_not_awaited()


# ---------------------------------------------------------------------------
# 13. /unlock returns "not found" for unknown user
# ---------------------------------------------------------------------------

def test_unlock_user_not_found(monkeypatch):
    monkeypatch.setattr(admin_h, "get_user_by_username", AsyncMock(return_value=None))

    update, replies = _make_cmd_update()
    ctx = SimpleNamespace(args=["@nobody"])

    with patch.object(admin_h, "_is_operator", return_value=True):
        _run(admin_h.unlock_command(update, ctx))

    assert any("not found" in r.lower() for r in replies)
