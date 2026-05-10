"""Hermetic tests for Phase 5G: Auto-Trade customize wizard.

No DB, no Telegram network. Handler functions are exercised directly using
SimpleNamespace fakes and AsyncMock patches.

Coverage:
  1.  Step 1 capital selection stores value and advances to CUSTOM_TP
  2.  Step 2 TP preset selection stores value and advances to CUSTOM_SL
  3.  Step 2 TP custom input valid — stores value and advances to CUSTOM_SL
  4.  Step 2 TP custom input invalid — rejected, stays in CUSTOM_INPUT
  5.  Step 3 SL preset selection stores value and advances to CUSTOM_REVIEW
  6.  Step 3 SL custom input valid — stores value and advances to CUSTOM_REVIEW
  7.  Step 4 auto-skipped — SL selection goes directly to CUSTOM_REVIEW
  8.  Step 5 review text contains correct hierarchy values
  9.  Save (new activation) writes correct columns to DB + flips auto_trade_on
  10. Back at Step 2 returns to CUSTOM_CAPITAL
  11. Cancel clears customize_wz and returns ConversationHandler.END
  12. Global /menu during wizard exits and calls menu handler
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from projects.polymarket.crusaderbot.bot.handlers import presets as h
from projects.polymarket.crusaderbot.bot.handlers.presets import (
    CUSTOM_CAPITAL, CUSTOM_INPUT, CUSTOM_REVIEW, CUSTOM_SL, CUSTOM_TP,
    _step5_text,
)
from projects.polymarket.crusaderbot.bot.keyboards.presets import (
    wizard_capital_kb, wizard_custom_input_kb, wizard_done_kb,
    wizard_review_kb, wizard_sl_kb, wizard_tp_kb,
)
from projects.polymarket.crusaderbot.domain.preset import get_preset
from telegram.ext import ConversationHandler


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

def _make_cq_update(callback_data: str):
    """Build a minimal callback-query Update."""
    msg = SimpleNamespace(
        edit_text=AsyncMock(),
        reply_text=AsyncMock(),
    )
    cq = SimpleNamespace(
        data=callback_data,
        answer=AsyncMock(),
        message=msg,
    )
    return SimpleNamespace(
        message=None,
        callback_query=cq,
        effective_user=SimpleNamespace(id=1, username="tester"),
    )


def _make_text_update(text: str):
    """Build a minimal text-message Update."""
    msg = SimpleNamespace(
        text=text,
        reply_text=AsyncMock(),
    )
    return SimpleNamespace(
        message=msg,
        callback_query=None,
        effective_user=SimpleNamespace(id=1, username="tester"),
    )


def _make_ctx(wz: dict | None = None) -> SimpleNamespace:
    user_data: dict = {}
    if wz is not None:
        user_data["customize_wz"] = wz
    return SimpleNamespace(user_data=user_data)


def _patch_tier(monkeypatch, uid, *, locked: bool = False):
    user = {
        "id": uid, "telegram_user_id": 1, "username": "tester",
        "access_tier": 2, "auto_trade_on": False, "paused": False,
        "locked": locked,
    }
    monkeypatch.setattr(h, "upsert_user", AsyncMock(return_value=user))
    return user


def _patch_writes(monkeypatch):
    update_settings = AsyncMock()
    set_auto_trade = AsyncMock()
    set_paused = AsyncMock()
    monkeypatch.setattr(h, "update_settings", update_settings)
    monkeypatch.setattr(h, "set_auto_trade", set_auto_trade)
    monkeypatch.setattr(h, "set_paused", set_paused)
    return update_settings, set_auto_trade, set_paused


# ---------------------------------------------------------------------------
# 1. Step 1: capital selection stores value + advances to CUSTOM_TP
# ---------------------------------------------------------------------------

def test_capital_selection_stores_value_and_advances(monkeypatch):
    wz = {
        "preset_key": "signal_sniper", "is_new_activation": True,
        "capital_pct": 0.50, "tp_pct": 0.15, "sl_pct": 0.08,
        "custom_field": None,
    }
    update = _make_cq_update("customize:capital:75")
    ctx = _make_ctx(wz)

    result = asyncio.run(h.step1_capital_select(update, ctx))

    assert result == CUSTOM_TP
    assert ctx.user_data["customize_wz"]["capital_pct"] == pytest.approx(0.75)
    update.callback_query.message.edit_text.assert_awaited_once()


# ---------------------------------------------------------------------------
# 2. Step 2: TP preset selection stores value + advances to CUSTOM_SL
# ---------------------------------------------------------------------------

def test_tp_preset_selection_stores_value_and_advances(monkeypatch):
    wz = {
        "preset_key": "signal_sniper", "is_new_activation": True,
        "capital_pct": 0.75, "tp_pct": 0.15, "sl_pct": 0.08,
        "custom_field": None,
    }
    update = _make_cq_update("customize:tp:20")
    ctx = _make_ctx(wz)

    result = asyncio.run(h.step2_tp_select(update, ctx))

    assert result == CUSTOM_SL
    assert ctx.user_data["customize_wz"]["tp_pct"] == pytest.approx(0.20)
    update.callback_query.message.edit_text.assert_awaited_once()


# ---------------------------------------------------------------------------
# 3. Step 2: TP custom input valid — stores and advances to CUSTOM_SL
# ---------------------------------------------------------------------------

def test_tp_custom_input_valid(monkeypatch):
    wz = {
        "preset_key": "signal_sniper", "is_new_activation": True,
        "capital_pct": 0.75, "tp_pct": 0.15, "sl_pct": 0.08,
        "custom_field": "tp",
    }
    update = _make_text_update("25")
    ctx = _make_ctx(wz)

    result = asyncio.run(h.custom_input_handler(update, ctx))

    assert result == CUSTOM_SL
    assert ctx.user_data["customize_wz"]["tp_pct"] == pytest.approx(0.25)
    assert ctx.user_data["customize_wz"]["custom_field"] is None
    update.message.reply_text.assert_awaited_once()


# ---------------------------------------------------------------------------
# 4. Step 2: TP custom input invalid — rejected, stays in CUSTOM_INPUT
# ---------------------------------------------------------------------------

def test_tp_custom_input_non_numeric_rejected(monkeypatch):
    wz = {
        "preset_key": "signal_sniper", "is_new_activation": True,
        "capital_pct": 0.75, "tp_pct": 0.15, "sl_pct": 0.08,
        "custom_field": "tp",
    }
    update = _make_text_update("abc")
    ctx = _make_ctx(wz)

    result = asyncio.run(h.custom_input_handler(update, ctx))

    assert result == CUSTOM_INPUT
    # tp_pct must be unchanged
    assert ctx.user_data["customize_wz"]["tp_pct"] == pytest.approx(0.15)
    update.message.reply_text.assert_awaited_once()
    error_msg = update.message.reply_text.call_args[0][0]
    assert "number" in error_msg.lower()


def test_tp_custom_input_out_of_range_rejected(monkeypatch):
    wz = {
        "preset_key": "signal_sniper", "is_new_activation": True,
        "capital_pct": 0.75, "tp_pct": 0.15, "sl_pct": 0.08,
        "custom_field": "tp",
    }
    update = _make_text_update("999")
    ctx = _make_ctx(wz)

    result = asyncio.run(h.custom_input_handler(update, ctx))

    assert result == CUSTOM_INPUT
    assert ctx.user_data["customize_wz"]["tp_pct"] == pytest.approx(0.15)


# ---------------------------------------------------------------------------
# 5. Step 3: SL preset selection stores value + advances to CUSTOM_REVIEW
# ---------------------------------------------------------------------------

def test_sl_preset_selection_stores_value_and_advances(monkeypatch):
    wz = {
        "preset_key": "signal_sniper", "is_new_activation": True,
        "capital_pct": 0.75, "tp_pct": 0.20, "sl_pct": 0.08,
        "custom_field": None,
    }
    update = _make_cq_update("customize:sl:10")
    ctx = _make_ctx(wz)

    result = asyncio.run(h.step3_sl_select(update, ctx))

    assert result == CUSTOM_REVIEW
    assert ctx.user_data["customize_wz"]["sl_pct"] == pytest.approx(0.10)
    update.callback_query.message.edit_text.assert_awaited_once()


# ---------------------------------------------------------------------------
# 6. Step 3: SL custom input valid — stores and advances to CUSTOM_REVIEW
# ---------------------------------------------------------------------------

def test_sl_custom_input_valid(monkeypatch):
    wz = {
        "preset_key": "value_hunter", "is_new_activation": True,
        "capital_pct": 0.50, "tp_pct": 0.20, "sl_pct": 0.12,
        "custom_field": "sl",
    }
    update = _make_text_update("7")
    ctx = _make_ctx(wz)

    result = asyncio.run(h.custom_input_handler(update, ctx))

    assert result == CUSTOM_REVIEW
    assert ctx.user_data["customize_wz"]["sl_pct"] == pytest.approx(0.07)
    assert ctx.user_data["customize_wz"]["custom_field"] is None
    update.message.reply_text.assert_awaited_once()


# ---------------------------------------------------------------------------
# 7. Step 4 auto-skipped — SL selection lands directly on CUSTOM_REVIEW
#    (no CUSTOM_COPY_TARGETS state exists; state after SL is always review)
# ---------------------------------------------------------------------------

def test_step4_is_skipped_for_all_current_presets(monkeypatch):
    """After SL selection the next state is CUSTOM_REVIEW, not a step-4 state."""
    for preset_key in ("signal_sniper", "value_hunter", "full_auto"):
        wz = {
            "preset_key": preset_key, "is_new_activation": True,
            "capital_pct": 0.50, "tp_pct": 0.15, "sl_pct": 0.08,
            "custom_field": None,
        }
        update = _make_cq_update("customize:sl:5")
        ctx = _make_ctx(wz)

        result = asyncio.run(h.step3_sl_select(update, ctx))

        assert result == CUSTOM_REVIEW, (
            f"Expected CUSTOM_REVIEW for preset {preset_key}, got {result}"
        )


# ---------------------------------------------------------------------------
# 8. Step 5: review text contains correct hierarchy values
# ---------------------------------------------------------------------------

def test_review_text_contains_correct_values():
    p = get_preset("signal_sniper")
    wz = {
        "preset_key": "signal_sniper",
        "capital_pct": 0.75,
        "tp_pct": 0.20,
        "sl_pct": 0.05,
    }
    text = _step5_text(wz, p)

    assert "Signal Sniper" in text
    assert "75%" in text
    assert "+20%" in text
    assert "-5%" in text
    assert "Paper" in text
    # Tree hierarchy characters present
    assert "├" in text
    assert "└" in text


# ---------------------------------------------------------------------------
# 9. Save (new activation) writes correct columns to DB
# ---------------------------------------------------------------------------

def test_save_new_activation_writes_db(monkeypatch):
    uid = uuid4()
    _patch_tier(monkeypatch, uid)
    update_settings, set_auto_trade, set_paused = _patch_writes(monkeypatch)
    monkeypatch.setattr(
        h, "get_settings_for",
        AsyncMock(return_value={"trading_mode": "paper"}),
    )

    wz = {
        "preset_key": "signal_sniper", "is_new_activation": True,
        "capital_pct": 0.75, "tp_pct": 0.20, "sl_pct": 0.05,
        "custom_field": None,
    }
    update = _make_cq_update("customize:save")
    ctx = _make_ctx(wz)

    result = asyncio.run(h.step_save(update, ctx))

    assert result == ConversationHandler.END
    # update_settings must be called with the wizard values
    update_settings.assert_awaited_once()
    call_kw = update_settings.call_args[1]
    assert call_kw["capital_alloc_pct"] == pytest.approx(0.75)
    assert call_kw["tp_pct"] == pytest.approx(0.20)
    assert call_kw["sl_pct"] == pytest.approx(0.05)
    assert call_kw["active_preset"] == "signal_sniper"
    # auto_trade flipped ON
    set_auto_trade.assert_awaited_once_with(uid, True)
    set_paused.assert_awaited_once_with(uid, False)
    # wizard state cleared
    assert "customize_wz" not in ctx.user_data


def test_save_new_activation_blocked_in_live_mode(monkeypatch):
    uid = uuid4()
    _patch_tier(monkeypatch, uid)
    update_settings, set_auto_trade, _ = _patch_writes(monkeypatch)
    monkeypatch.setattr(
        h, "get_settings_for",
        AsyncMock(return_value={"trading_mode": "live"}),
    )

    wz = {
        "preset_key": "signal_sniper", "is_new_activation": True,
        "capital_pct": 0.50, "tp_pct": 0.15, "sl_pct": 0.08,
        "custom_field": None,
    }
    update = _make_cq_update("customize:save")
    ctx = _make_ctx(wz)

    result = asyncio.run(h.step_save(update, ctx))

    assert result == ConversationHandler.END
    # Must NOT activate auto-trade in live mode
    set_auto_trade.assert_not_awaited()
    update_settings.assert_not_awaited()
    # Error message shown
    update.callback_query.message.reply_text.assert_awaited_once()
    msg = update.callback_query.message.reply_text.call_args[0][0]
    assert "live" in msg.lower()


def test_save_edit_only_writes_settings_not_activation(monkeypatch):
    uid = uuid4()
    _patch_tier(monkeypatch, uid)
    update_settings, set_auto_trade, set_paused = _patch_writes(monkeypatch)

    wz = {
        "preset_key": "signal_sniper", "is_new_activation": False,
        "capital_pct": 0.50, "tp_pct": 0.15, "sl_pct": 0.08,
        "custom_field": None,
    }
    update = _make_cq_update("customize:save")
    ctx = _make_ctx(wz)

    result = asyncio.run(h.step_save(update, ctx))

    assert result == ConversationHandler.END
    update_settings.assert_awaited_once()
    call_kw = update_settings.call_args[1]
    assert "active_preset" not in call_kw
    # auto_trade NOT touched for edit-only path
    set_auto_trade.assert_not_awaited()


# ---------------------------------------------------------------------------
# 10. Back at Step 2 returns to CUSTOM_CAPITAL
# ---------------------------------------------------------------------------

def test_back_at_tp_returns_to_capital(monkeypatch):
    wz = {
        "preset_key": "signal_sniper", "is_new_activation": True,
        "capital_pct": 0.50, "tp_pct": 0.15, "sl_pct": 0.08,
        "custom_field": None,
    }
    update = _make_cq_update("customize:back:capital")
    ctx = _make_ctx(wz)

    result = asyncio.run(h.step_back_to_capital(update, ctx))

    assert result == CUSTOM_CAPITAL
    update.callback_query.message.edit_text.assert_awaited_once()


def test_back_at_sl_returns_to_tp(monkeypatch):
    wz = {
        "preset_key": "signal_sniper", "is_new_activation": True,
        "capital_pct": 0.50, "tp_pct": 0.15, "sl_pct": 0.08,
        "custom_field": None,
    }
    update = _make_cq_update("customize:back:tp")
    ctx = _make_ctx(wz)

    result = asyncio.run(h.step_back_to_tp(update, ctx))

    assert result == CUSTOM_TP
    update.callback_query.message.edit_text.assert_awaited_once()


def test_back_at_review_returns_to_sl(monkeypatch):
    wz = {
        "preset_key": "signal_sniper", "is_new_activation": True,
        "capital_pct": 0.50, "tp_pct": 0.15, "sl_pct": 0.08,
        "custom_field": None,
    }
    update = _make_cq_update("customize:back:sl")
    ctx = _make_ctx(wz)

    result = asyncio.run(h.step_back_to_sl(update, ctx))

    assert result == CUSTOM_SL
    update.callback_query.message.edit_text.assert_awaited_once()


# ---------------------------------------------------------------------------
# 11. Cancel clears wizard state and returns END
# ---------------------------------------------------------------------------

def test_cancel_exits_clean(monkeypatch):
    wz = {
        "preset_key": "signal_sniper", "is_new_activation": True,
        "capital_pct": 0.50, "tp_pct": 0.15, "sl_pct": 0.08,
        "custom_field": None,
    }
    update = _make_cq_update("customize:cancel")
    ctx = _make_ctx(wz)

    result = asyncio.run(h.wizard_cancel(update, ctx))

    assert result == ConversationHandler.END
    assert "customize_wz" not in ctx.user_data
    update.callback_query.message.edit_text.assert_awaited_once()
    cancelled_text = update.callback_query.message.edit_text.call_args[0][0]
    assert "cancelled" in cancelled_text.lower()


# ---------------------------------------------------------------------------
# 12. Global /menu during wizard exits and calls menu handler
# ---------------------------------------------------------------------------

def test_global_menu_exits_wizard(monkeypatch):
    import sys

    called = []

    async def _fake_menu(update, ctx):
        called.append(True)

    fake_onboarding = MagicMock()
    fake_onboarding.menu_handler = _fake_menu

    wz = {
        "preset_key": "signal_sniper", "is_new_activation": True,
        "capital_pct": 0.50, "tp_pct": 0.15, "sl_pct": 0.08,
        "custom_field": None,
    }
    update = SimpleNamespace(
        message=SimpleNamespace(text="/menu", reply_text=AsyncMock()),
        callback_query=None,
        effective_user=SimpleNamespace(id=1, username="tester"),
    )
    ctx = _make_ctx(wz)

    onboarding_key = (
        "projects.polymarket.crusaderbot.bot.handlers.onboarding"
    )
    original = sys.modules.get(onboarding_key)
    sys.modules[onboarding_key] = fake_onboarding
    try:
        result = asyncio.run(h.wizard_fallback_menu(update, ctx))
    finally:
        if original is None:
            sys.modules.pop(onboarding_key, None)
        else:
            sys.modules[onboarding_key] = original

    assert result == ConversationHandler.END
    assert "customize_wz" not in ctx.user_data
    assert called, "menu_handler was not called"


# ---------------------------------------------------------------------------
# Keyboard structure sanity checks
# ---------------------------------------------------------------------------

def test_capital_kb_has_four_pct_buttons_and_cancel():
    kb = wizard_capital_kb()
    all_cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "customize:capital:25" in all_cbs
    assert "customize:capital:50" in all_cbs
    assert "customize:capital:75" in all_cbs
    assert "customize:capital:100" in all_cbs
    assert "customize:cancel" in all_cbs


def test_tp_kb_has_four_pct_buttons_custom_and_back():
    kb = wizard_tp_kb()
    all_cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "customize:tp:10" in all_cbs
    assert "customize:tp:15" in all_cbs
    assert "customize:tp:20" in all_cbs
    assert "customize:tp:30" in all_cbs
    assert "customize:tp:custom" in all_cbs
    assert "customize:back:capital" in all_cbs


def test_sl_kb_has_four_pct_buttons_custom_and_back():
    kb = wizard_sl_kb()
    all_cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "customize:sl:5" in all_cbs
    assert "customize:sl:8" in all_cbs
    assert "customize:sl:10" in all_cbs
    assert "customize:sl:15" in all_cbs
    assert "customize:sl:custom" in all_cbs
    assert "customize:back:tp" in all_cbs


def test_review_kb_has_save_and_back():
    kb = wizard_review_kb()
    all_cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "customize:save" in all_cbs
    assert "customize:back:sl" in all_cbs


def test_done_kb_has_dashboard_and_autotrade():
    kb = wizard_done_kb()
    all_cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "dashboard:main" in all_cbs
    assert "preset:status" in all_cbs


def test_capital_kb_is_two_col_grid():
    kb = wizard_capital_kb()
    # 4 pct buttons → 2 rows of 2; then 1 cancel row
    assert len(kb.inline_keyboard[0]) == 2
    assert len(kb.inline_keyboard[1]) == 2
