"""Hermetic unit tests for Track F — Live Opt-In Gate.

Coverage:
  check_activation_guards:
    - returns all_set=True when all 4 guards are True
    - returns all_set=False + missing list when any guard is False
    - missing list contains only the failing guards

  text_input (live_gate handler):
    - returns False when no awaiting flag is set (non-consuming)
    - returns True and shows Step 3 keyboard when CONFIRM typed correctly
    - returns True and cancels when wrong text typed
    - case-sensitive: 'confirm' (lowercase) is rejected

  live_gate_callback (step 3):
    - CANCEL action sends cancellation message
    - YES action within timeout window writes mode_change_event + updates settings
    - YES action after 10s timeout sends expiry message, no mode change written
    - YES action with no awaiting flag (stale callback) sends restart prompt

  auto-fallback:
    - run_auto_fallback_check does nothing when error_count <= threshold
    - run_auto_fallback_check switches all live users when error_count > threshold
    - run_auto_fallback_check writes mode_change_event for each switched user
    - run_auto_fallback_check notifies operator when fallback fires
"""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from projects.polymarket.crusaderbot.domain.activation.live_opt_in_gate import (
    GUARD_CAPITAL_MODE_CONFIRMED,
    GUARD_ENABLE_LIVE_TRADING,
    GUARD_EXECUTION_PATH_VALIDATED,
    GUARD_RISK_CONTROLS_VALIDATED,
    GuardCheckResult,
    ModeChangeReason,
    check_activation_guards,
)
from projects.polymarket.crusaderbot.bot.handlers import live_gate
from projects.polymarket.crusaderbot.domain.activation import auto_fallback, live_checklist
from projects.polymarket.crusaderbot.domain.activation.auto_fallback import LIVE_ERROR_ACTIONS


# ── helpers ───────────────────────────────────────────────────────────────────


def _fake_settings(**overrides: bool) -> SimpleNamespace:
    defaults = dict(
        ENABLE_LIVE_TRADING=True,
        EXECUTION_PATH_VALIDATED=True,
        CAPITAL_MODE_CONFIRMED=True,
        RISK_CONTROLS_VALIDATED=True,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


USER_ROW = {
    "id": uuid4(),
    "telegram_user_id": 9001,
    "username": "tester",
    "auto_trade_on": False,
    "access_tier": 4,
    "paused": False,
    "locked": False,
}

SETTINGS_ROW = {"trading_mode": "paper"}
CHECKLIST_PASS = SimpleNamespace(ready_for_live=True, passed=True, failed_gates=[], outcomes=[])
CHECKLIST_FAIL = SimpleNamespace(ready_for_live=False, passed=False, failed_gates=["ENABLE_LIVE_TRADING"], outcomes=[])


def _make_msg_update(text: str = "") -> tuple[SimpleNamespace, AsyncMock]:
    reply = AsyncMock()
    msg = SimpleNamespace(text=text, reply_text=reply)
    update = SimpleNamespace(
        message=msg,
        effective_user=SimpleNamespace(id=9001, username="tester"),
        callback_query=None,
    )
    return update, reply


def _make_cb_update(data: str) -> tuple[SimpleNamespace, AsyncMock]:
    answer = AsyncMock()
    reply = AsyncMock()
    cb_msg = SimpleNamespace(reply_text=reply)
    cb = SimpleNamespace(data=data, answer=answer, message=cb_msg)
    update = SimpleNamespace(
        callback_query=cb,
        effective_user=SimpleNamespace(id=9001, username="tester"),
        message=None,
    )
    return update, reply


def _make_ctx(data: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(user_data=data if data is not None else {})


# ── check_activation_guards ───────────────────────────────────────────────────


def test_all_guards_set_returns_all_set_true():
    result = check_activation_guards(_fake_settings())
    assert result.all_set is True
    assert result.missing == []


def test_missing_one_guard_returns_all_set_false():
    result = check_activation_guards(
        _fake_settings(ENABLE_LIVE_TRADING=False)
    )
    assert result.all_set is False
    assert GUARD_ENABLE_LIVE_TRADING in result.missing


def test_missing_multiple_guards_listed():
    result = check_activation_guards(
        _fake_settings(EXECUTION_PATH_VALIDATED=False, RISK_CONTROLS_VALIDATED=False)
    )
    assert result.all_set is False
    assert GUARD_EXECUTION_PATH_VALIDATED in result.missing
    assert GUARD_RISK_CONTROLS_VALIDATED in result.missing
    assert len(result.missing) == 2


def test_passing_guards_not_in_missing():
    result = check_activation_guards(
        _fake_settings(CAPITAL_MODE_CONFIRMED=False)
    )
    assert GUARD_CAPITAL_MODE_CONFIRMED in result.missing
    assert GUARD_ENABLE_LIVE_TRADING not in result.missing
    assert GUARD_EXECUTION_PATH_VALIDATED not in result.missing
    assert GUARD_RISK_CONTROLS_VALIDATED not in result.missing


def test_all_guards_false_all_missing():
    result = check_activation_guards(
        _fake_settings(
            ENABLE_LIVE_TRADING=False,
            EXECUTION_PATH_VALIDATED=False,
            CAPITAL_MODE_CONFIRMED=False,
            RISK_CONTROLS_VALIDATED=False,
        )
    )
    assert result.all_set is False
    assert len(result.missing) == 4


# ── text_input — not consuming when no awaiting ───────────────────────────────


def test_text_input_no_awaiting_returns_false():
    update, _ = _make_msg_update("CONFIRM")
    ctx = _make_ctx({})
    result = asyncio.run(live_gate.text_input(update, ctx))
    assert result is False


def test_text_input_wrong_awaiting_returns_false():
    update, _ = _make_msg_update("CONFIRM")
    ctx = _make_ctx({"awaiting": "some_other_flow"})
    result = asyncio.run(live_gate.text_input(update, ctx))
    assert result is False


# ── text_input — CONFIRM accepted (case-sensitive) ────────────────────────────


def test_text_input_confirm_exact_advances_to_step3():
    update, reply = _make_msg_update("CONFIRM")
    ctx = _make_ctx({"awaiting": live_gate.AWAITING_STEP1})

    result = asyncio.run(live_gate.text_input(update, ctx))

    assert result is True
    # Step 3 keyboard was shown
    reply.assert_awaited_once()
    _, kwargs = reply.call_args
    assert kwargs.get("reply_markup") is not None
    # awaiting advanced to step2
    assert ctx.user_data.get("awaiting") == live_gate.AWAITING_STEP2
    # timestamp stored
    assert live_gate.GATE_TS_KEY in ctx.user_data


def test_text_input_lowercase_confirm_rejected():
    update, reply = _make_msg_update("confirm")
    ctx = _make_ctx({"awaiting": live_gate.AWAITING_STEP1})

    result = asyncio.run(live_gate.text_input(update, ctx))

    assert result is True
    reply.assert_awaited_once()
    # awaiting cleared, no step2 armed
    assert ctx.user_data.get("awaiting") is None


def test_text_input_wrong_text_cancels():
    update, reply = _make_msg_update("yes")
    ctx = _make_ctx({"awaiting": live_gate.AWAITING_STEP1})

    result = asyncio.run(live_gate.text_input(update, ctx))

    assert result is True
    reply.assert_awaited_once()
    assert ctx.user_data.get("awaiting") is None


# ── live_gate_callback — CANCEL ───────────────────────────────────────────────


def test_callback_cancel_sends_cancel_message():
    update, reply = _make_cb_update("live_gate:cancel")
    ctx = _make_ctx({"awaiting": live_gate.AWAITING_STEP2})

    asyncio.run(live_gate.live_gate_callback(update, ctx))

    reply.assert_awaited_once()
    assert ctx.user_data.get("awaiting") is None


# ── live_gate_callback — YES within timeout ───────────────────────────────────


def test_callback_yes_within_timeout_enables_live():
    update, reply = _make_cb_update("live_gate:yes")
    ctx = _make_ctx({
        "awaiting": live_gate.AWAITING_STEP2,
        live_gate.GATE_TS_KEY: time.monotonic(),  # just now
    })

    with patch.object(live_gate, "upsert_user", AsyncMock(return_value=USER_ROW)), \
         patch.object(live_gate.live_checklist, "evaluate",
                      AsyncMock(return_value=CHECKLIST_PASS)), \
         patch.object(live_gate, "get_settings_for", AsyncMock(return_value=SETTINGS_ROW)), \
         patch.object(live_gate, "update_settings", AsyncMock()) as mock_update, \
         patch.object(live_gate, "write_mode_change_event", AsyncMock()) as mock_audit:
        asyncio.run(live_gate.live_gate_callback(update, ctx))

    mock_update.assert_awaited_once_with(USER_ROW["id"], trading_mode="live")
    mock_audit.assert_awaited_once_with(
        user_id=USER_ROW["id"],
        from_mode="paper",
        to_mode="live",
        reason=ModeChangeReason.USER_CONFIRMED,
    )
    reply.assert_awaited_once()


def test_callback_yes_checklist_fail_blocks_mode_change():
    update, reply = _make_cb_update("live_gate:yes")
    ctx = _make_ctx({
        "awaiting": live_gate.AWAITING_STEP2,
        live_gate.GATE_TS_KEY: time.monotonic(),
    })

    with patch.object(live_gate, "upsert_user", AsyncMock(return_value=USER_ROW)), \
         patch.object(live_gate.live_checklist, "evaluate",
                      AsyncMock(return_value=CHECKLIST_FAIL)), \
         patch.object(live_gate.live_checklist, "render_telegram",
                      return_value="🔒 not ready"), \
         patch.object(live_gate, "update_settings", AsyncMock()) as mock_update, \
         patch.object(live_gate, "write_mode_change_event", AsyncMock()) as mock_audit:
        asyncio.run(live_gate.live_gate_callback(update, ctx))

    mock_update.assert_not_awaited()
    mock_audit.assert_not_awaited()
    reply.assert_awaited_once()


# ── live_gate_callback — YES after timeout ────────────────────────────────────


def test_callback_yes_after_timeout_rejected():
    update, reply = _make_cb_update("live_gate:yes")
    expired_ts = time.monotonic() - 15.0  # 15 seconds ago
    ctx = _make_ctx({
        "awaiting": live_gate.AWAITING_STEP2,
        live_gate.GATE_TS_KEY: expired_ts,
    })

    with patch.object(live_gate, "update_settings", AsyncMock()) as mock_update, \
         patch.object(live_gate, "write_mode_change_event", AsyncMock()) as mock_audit:
        asyncio.run(live_gate.live_gate_callback(update, ctx))

    mock_update.assert_not_awaited()
    mock_audit.assert_not_awaited()
    reply.assert_awaited_once()
    # Timeout message sent
    args, _ = reply.call_args
    assert "expired" in args[0].lower() or "expired" in str(reply.call_args).lower()


# ── live_gate_callback — stale callback (no awaiting) ────────────────────────


def test_callback_yes_no_awaiting_prompts_restart():
    update, reply = _make_cb_update("live_gate:yes")
    ctx = _make_ctx({})

    asyncio.run(live_gate.live_gate_callback(update, ctx))

    reply.assert_awaited_once()


# ── auto_fallback — below threshold ──────────────────────────────────────────


def test_auto_fallback_no_action_below_threshold():
    with patch.object(auto_fallback, "get_recent_error_count",
                      AsyncMock(return_value=3)), \
         patch.object(auto_fallback, "get_live_mode_users",
                      AsyncMock(return_value=[])) as mock_users:
        asyncio.run(auto_fallback.run_auto_fallback_check())

    mock_users.assert_not_awaited()


def test_auto_fallback_no_action_at_threshold():
    with patch.object(auto_fallback, "get_recent_error_count",
                      AsyncMock(return_value=auto_fallback.ERROR_THRESHOLD)), \
         patch.object(auto_fallback, "get_live_mode_users",
                      AsyncMock(return_value=[])) as mock_users:
        asyncio.run(auto_fallback.run_auto_fallback_check())

    mock_users.assert_not_awaited()


# ── auto_fallback — above threshold ──────────────────────────────────────────


def test_auto_fallback_switches_live_users():
    uid = uuid4()
    live_users = [{"user_id": uid, "telegram_user_id": 9002}]

    with patch.object(auto_fallback, "get_recent_error_count",
                      AsyncMock(return_value=auto_fallback.ERROR_THRESHOLD + 1)), \
         patch.object(auto_fallback, "get_live_mode_users",
                      AsyncMock(return_value=live_users)), \
         patch.object(auto_fallback, "_switch_user_to_paper", AsyncMock()) as mock_switch, \
         patch.object(auto_fallback, "write_mode_change_event", AsyncMock()) as mock_audit, \
         patch.object(auto_fallback.notifications, "notify_operator", AsyncMock()):
        asyncio.run(auto_fallback.run_auto_fallback_check())

    mock_switch.assert_awaited_once_with(uid)
    mock_audit.assert_awaited_once_with(
        user_id=uid,
        from_mode="live",
        to_mode="paper",
        reason=ModeChangeReason.AUTO_FALLBACK,
    )


def test_auto_fallback_notifies_operator():
    uid = uuid4()
    live_users = [{"user_id": uid, "telegram_user_id": 9003}]

    with patch.object(auto_fallback, "get_recent_error_count",
                      AsyncMock(return_value=10)), \
         patch.object(auto_fallback, "get_live_mode_users",
                      AsyncMock(return_value=live_users)), \
         patch.object(auto_fallback, "_switch_user_to_paper", AsyncMock()), \
         patch.object(auto_fallback, "write_mode_change_event", AsyncMock()), \
         patch.object(auto_fallback.notifications, "notify_operator",
                      AsyncMock()) as mock_notify:
        asyncio.run(auto_fallback.run_auto_fallback_check())

    mock_notify.assert_awaited_once()
    msg = mock_notify.call_args[0][0]
    assert "AUTO-FALLBACK" in msg
    assert "1" in msg  # switched count


def test_auto_fallback_no_live_users_no_switch():
    with patch.object(auto_fallback, "get_recent_error_count",
                      AsyncMock(return_value=10)), \
         patch.object(auto_fallback, "get_live_mode_users",
                      AsyncMock(return_value=[])), \
         patch.object(auto_fallback, "_switch_user_to_paper",
                      AsyncMock()) as mock_switch:
        asyncio.run(auto_fallback.run_auto_fallback_check())

    mock_switch.assert_not_awaited()
