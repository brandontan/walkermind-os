"""Hermetic tests for Phase 5F Copy Trade wizard + per-task edit.

No real DB, no Telegram API calls, no network.

Coverage:
  Keyboard purity (no async):
    1  wizard_amount_mode_kb — has Fixed and % Mirror buttons
    2  wizard_step1_fixed_kb — has $1/$5/$10/$25 presets + Custom
    3  wizard_step1_pct_kb  — has 5%/10%/25%/50% presets + Custom
    4  wizard_step2_kb      — has Keep Defaults and Edit
    5  wizard_step2_edit_kb — renders TP/SL values in button labels
    6  wizard_step3_kb      — has Start Copying and Back
    7  wizard_success_kb    — has Copy Trade and Dashboard nav buttons
    8  edit_task_main_kb    — shows Pause for active task
    9  edit_task_main_kb    — shows Resume for paused task
   10  edit_delete_confirm_kb — has Yes Delete and Cancel

  Repository (mocked DB):
   11  create_task  — returns CopyTradeTask with status active
   12  get_task     — returns None when no row found
   13  update_task  — raises ValueError for unknown fields
   14  delete_task  — returns True when row deleted
   15  toggle_pause — active → paused

  Handler wizard flow (mocked DB + mock Update):
   16  wizard_enter_copy     — renders step 1, returns COPY_AMOUNT
   17  step1_mode_select     — fixed mode shows fixed kb, stays COPY_AMOUNT
   18  step1_fixed_select    — stores amount, goes to COPY_RISK
   19  step1_pct_select      — stores pct, goes to COPY_RISK
   20  step1_custom          — enters COPY_CUSTOM
   21  step2_keep            — goes to COPY_CONFIRM
   22  step2_edit            — shows risk edit grid, stays COPY_RISK
   23  step3_confirm         — calls create_task, returns END
   24  wizard_cancel         — shows add wallet screen, returns END
   25  wizard_enter_edit     — fetches task, shows edit screen, returns COPY_EDIT
   26  edit_pause            — toggles pause, stays COPY_EDIT
   27  edit_delete_ask       — shows confirm dialog, stays COPY_EDIT
   28  edit_delete_confirm   — deletes task, returns END
   29  edit_delete_cancel    — fetches task, shows edit screen, stays COPY_EDIT
   30  custom_input_handler  — valid amount → advances to COPY_RISK
   31  custom_input_handler  — invalid text → shows error, stays COPY_CUSTOM
   32  wizard_fallback_text  — unknown text shows hint, keeps state (returns None)
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

# ── keyboard imports ──────────────────────────────────────────────────────────

from projects.polymarket.crusaderbot.bot.keyboards.copy_trade import (
    edit_delete_confirm_kb,
    edit_task_main_kb,
    wizard_amount_mode_kb,
    wizard_step1_fixed_kb,
    wizard_step1_pct_kb,
    wizard_step2_edit_kb,
    wizard_step2_kb,
    wizard_step3_kb,
    wizard_success_kb,
)

# ── handler + state imports ───────────────────────────────────────────────────

import projects.polymarket.crusaderbot.bot.handlers.copy_trade as ct_mod
from projects.polymarket.crusaderbot.bot.handlers.copy_trade import (
    COPY_AMOUNT,
    COPY_CONFIRM,
    COPY_CUSTOM,
    COPY_EDIT,
    COPY_RISK,
    _init_wizard,
    build_wizard_handler,
    custom_input_handler,
    edit_delete_ask,
    edit_delete_cancel,
    edit_delete_confirm,
    edit_pause,
    step1_custom,
    step1_fixed_select,
    step1_mode_select,
    step1_pct_select,
    step2_edit,
    step2_keep,
    step3_confirm,
    wizard_cancel,
    wizard_enter_copy,
    wizard_enter_edit,
    wizard_fallback_text,
)

# ── repository import ─────────────────────────────────────────────────────────

import projects.polymarket.crusaderbot.domain.copy_trade.repository as repo_mod
from projects.polymarket.crusaderbot.domain.copy_trade.models import CopyTradeTask

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures and factories
# ─────────────────────────────────────────────────────────────────────────────

_FAKE_USER_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
_FAKE_TASK_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
_FAKE_WALLET = "0xabcdef1234567890abcdef1234567890abcdef12"


def _make_task(**overrides) -> CopyTradeTask:
    from datetime import datetime, timezone
    now = datetime(2026, 5, 10, 12, 0, 0, tzinfo=timezone.utc)
    defaults = dict(
        id=_FAKE_TASK_ID,
        user_id=_FAKE_USER_ID,
        wallet_address=_FAKE_WALLET,
        task_name="Copy 0xabcdef…ef12",
        status="active",
        copy_mode="fixed",
        copy_amount=Decimal("5.00"),
        copy_pct=None,
        tp_pct=Decimal("0.20"),
        sl_pct=Decimal("0.10"),
        max_daily_spend=Decimal("100.00"),
        slippage_pct=Decimal("0.05"),
        min_trade_size=Decimal("0.50"),
        reverse_copy=False,
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    return CopyTradeTask(**defaults)


def _make_query(data: str) -> MagicMock:
    q = MagicMock()
    q.data = data
    q.answer = AsyncMock()
    q.message = MagicMock()
    q.message.edit_text = AsyncMock()
    q.message.reply_text = AsyncMock()
    return q


def _make_update(callback_data: str | None = None, text: str | None = None):
    update = MagicMock()
    if callback_data is not None:
        q = _make_query(callback_data)
        update.callback_query = q
        update.message = None
    else:
        update.callback_query = None
        msg = MagicMock()
        msg.text = text
        msg.reply_text = AsyncMock()
        update.message = msg
    update.effective_user = MagicMock()
    update.effective_user.id = 999
    update.effective_user.username = "testuser"
    return update


def _make_ctx(wizard: dict | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.user_data = {}
    if wizard is not None:
        ctx.user_data["wizard"] = wizard
    ctx.args = []
    return ctx


def _mock_resolve_user(ok: bool = True):
    fake_user = {"id": _FAKE_USER_ID, "access_tier": 2}
    return patch.object(
        ct_mod, "_resolve_user", new=AsyncMock(return_value=(fake_user, ok)),
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1–10: Keyboard tests (pure, synchronous)
# ─────────────────────────────────────────────────────────────────────────────


def _all_cbs(kb) -> set[str]:
    return {b.callback_data for row in kb.inline_keyboard for b in row}


def _all_labels(kb) -> list[str]:
    return [b.text for row in kb.inline_keyboard for b in row]


def test_01_wizard_amount_mode_has_fixed_and_pct():
    kb = wizard_amount_mode_kb()
    cbs = _all_cbs(kb)
    assert "wizard:mode:fixed" in cbs
    assert "wizard:mode:pct" in cbs


def test_02_wizard_step1_fixed_has_presets_and_custom():
    kb = wizard_step1_fixed_kb()
    cbs = _all_cbs(kb)
    assert "wizard:fixed:1" in cbs
    assert "wizard:fixed:5" in cbs
    assert "wizard:fixed:10" in cbs
    assert "wizard:fixed:25" in cbs
    assert "wizard:custom:amount" in cbs


def test_03_wizard_step1_pct_has_presets_and_custom():
    kb = wizard_step1_pct_kb()
    cbs = _all_cbs(kb)
    assert "wizard:pct:5" in cbs
    assert "wizard:pct:10" in cbs
    assert "wizard:pct:25" in cbs
    assert "wizard:pct:50" in cbs
    assert "wizard:custom:pct" in cbs


def test_04_wizard_step2_has_keep_and_edit():
    kb = wizard_step2_kb()
    cbs = _all_cbs(kb)
    assert "wizard:keep" in cbs
    assert "wizard:risk:edit" in cbs
    assert "wizard:back:step1" in cbs


def test_05_wizard_step2_edit_shows_values_in_labels():
    kb = wizard_step2_edit_kb("+20%", "-10%", "$100", "5%", "$0.50")
    labels = _all_labels(kb)
    assert any("+20%" in l for l in labels)
    assert any("-10%" in l for l in labels)
    assert any("$100" in l for l in labels)


def test_06_wizard_step3_has_start_and_back():
    kb = wizard_step3_kb()
    cbs = _all_cbs(kb)
    assert "wizard:confirm" in cbs
    assert "wizard:back:step2" in cbs


def test_07_wizard_success_has_nav_buttons():
    kb = wizard_success_kb()
    cbs = _all_cbs(kb)
    assert "copytrade:dashboard" in cbs
    assert "dashboard:main" in cbs


def test_08_edit_task_main_shows_pause_for_active():
    task = _make_task(status="active")
    kb = edit_task_main_kb(task)
    labels = _all_labels(kb)
    assert any("Pause" in l for l in labels)
    assert not any("Resume" in l for l in labels)


def test_09_edit_task_main_shows_resume_for_paused():
    task = _make_task(status="paused")
    kb = edit_task_main_kb(task)
    labels = _all_labels(kb)
    assert any("Resume" in l for l in labels)


def test_10_edit_delete_confirm_has_yes_and_cancel():
    kb = edit_delete_confirm_kb(str(_FAKE_TASK_ID))
    cbs = _all_cbs(kb)
    assert any("yes" in cb for cb in cbs)
    assert any("no" in cb for cb in cbs)


# ─────────────────────────────────────────────────────────────────────────────
# 11–15: Repository tests (mocked DB)
# ─────────────────────────────────────────────────────────────────────────────


def _mock_pool(fetchrow_return=None, execute_return=None):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow_return)
    conn.execute = AsyncMock(return_value=execute_return)
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    return pool, conn


def _fake_db_row(**overrides) -> MagicMock:
    from datetime import datetime, timezone
    now = datetime(2026, 5, 10, 12, 0, 0, tzinfo=timezone.utc)
    row = MagicMock()
    row.__getitem__ = MagicMock(side_effect=lambda k: {
        "id": _FAKE_TASK_ID,
        "user_id": _FAKE_USER_ID,
        "wallet_address": _FAKE_WALLET,
        "task_name": "Copy 0xabcdef…ef12",
        "status": "active",
        "copy_mode": "fixed",
        "copy_amount": Decimal("5.00"),
        "copy_pct": None,
        "tp_pct": Decimal("0.20"),
        "sl_pct": Decimal("0.10"),
        "max_daily_spend": Decimal("100.00"),
        "slippage_pct": Decimal("0.05"),
        "min_trade_size": Decimal("0.50"),
        "reverse_copy": False,
        "created_at": now,
        "updated_at": now,
        **overrides,
    }[k])
    return row


def test_11_create_task_returns_copy_trade_task():
    row = _fake_db_row()
    pool, _conn = _mock_pool(fetchrow_return=row)
    with patch.object(repo_mod, "get_pool", return_value=pool):
        task = asyncio.run(
            repo_mod.create_task(
                user_id=_FAKE_USER_ID,
                wallet_address=_FAKE_WALLET,
                task_name="Test",
                copy_mode="fixed",
                copy_amount=Decimal("5.00"),
            )
        )
    assert isinstance(task, CopyTradeTask)
    assert task.status == "active"


def test_12_get_task_returns_none_when_not_found():
    pool, _conn = _mock_pool(fetchrow_return=None)
    with patch.object(repo_mod, "get_pool", return_value=pool):
        result = asyncio.run(
            repo_mod.get_task(_FAKE_TASK_ID, _FAKE_USER_ID)
        )
    assert result is None


def test_13_update_task_raises_for_unknown_field():
    pool, _conn = _mock_pool()
    with patch.object(repo_mod, "get_pool", return_value=pool):
        with pytest.raises(ValueError, match="Unknown fields"):
            asyncio.run(
                repo_mod.update_task(
                    _FAKE_TASK_ID, _FAKE_USER_ID, nonexistent_field="x",
                )
            )


def test_14_delete_task_returns_true_when_deleted():
    fake_row = MagicMock()
    pool, _conn = _mock_pool(fetchrow_return=fake_row)
    with patch.object(repo_mod, "get_pool", return_value=pool):
        result = asyncio.run(
            repo_mod.delete_task(_FAKE_TASK_ID, _FAKE_USER_ID)
        )
    assert result is True


def test_15_toggle_pause_active_becomes_paused():
    status_row = MagicMock()
    status_row.__getitem__ = MagicMock(return_value="active")
    pool, conn = _mock_pool(fetchrow_return=status_row)
    conn.execute = AsyncMock()
    with patch.object(repo_mod, "get_pool", return_value=pool):
        result = asyncio.run(
            repo_mod.toggle_pause(_FAKE_TASK_ID, _FAKE_USER_ID)
        )
    assert result == "paused"


# ─────────────────────────────────────────────────────────────────────────────
# 16–32: Handler tests (mocked DB + mock Update)
# ─────────────────────────────────────────────────────────────────────────────


def run(coro):
    return asyncio.run(coro)


def test_16_wizard_enter_copy_renders_step1():
    update = _make_update(callback_data=f"copytrade:copy:{_FAKE_WALLET}")
    ctx = _make_ctx()
    with _mock_resolve_user():
        state = run(wizard_enter_copy(update, ctx))
    assert state == COPY_AMOUNT
    update.callback_query.message.edit_text.assert_called_once()
    assert "wizard" in ctx.user_data
    assert ctx.user_data["wizard"]["wallet_addr"] == _FAKE_WALLET


def test_17_step1_mode_select_fixed_shows_fixed_kb():
    wz = _init_wizard(_FAKE_WALLET)
    update = _make_update(callback_data="wizard:mode:fixed")
    ctx = _make_ctx(wizard=wz)
    state = run(step1_mode_select(update, ctx))
    assert state == COPY_AMOUNT
    update.callback_query.message.edit_text.assert_called_once()
    _, kwargs = update.callback_query.message.edit_text.call_args
    # The keyboard passed should contain wizard:fixed:* callbacks
    from projects.polymarket.crusaderbot.bot.keyboards.copy_trade import (
        wizard_step1_fixed_kb as _fkb,
    )
    expected_cbs = _all_cbs(_fkb())
    actual_cbs = _all_cbs(kwargs["reply_markup"])
    assert expected_cbs == actual_cbs


def test_18_step1_fixed_select_stores_amount_goes_to_risk():
    wz = _init_wizard(_FAKE_WALLET)
    update = _make_update(callback_data="wizard:fixed:10")
    ctx = _make_ctx(wizard=wz)
    state = run(step1_fixed_select(update, ctx))
    assert state == COPY_RISK
    assert ctx.user_data["wizard"]["copy_amount"] == Decimal("10")
    assert ctx.user_data["wizard"]["copy_mode"] == "fixed"


def test_19_step1_pct_select_stores_pct_goes_to_risk():
    wz = _init_wizard(_FAKE_WALLET)
    update = _make_update(callback_data="wizard:pct:25")
    ctx = _make_ctx(wizard=wz)
    state = run(step1_pct_select(update, ctx))
    assert state == COPY_RISK
    assert ctx.user_data["wizard"]["copy_pct"] == Decimal("0.25")
    assert ctx.user_data["wizard"]["copy_mode"] == "proportional"


def test_20_step1_custom_enters_copy_custom():
    wz = _init_wizard(_FAKE_WALLET)
    update = _make_update(callback_data="wizard:custom:amount")
    ctx = _make_ctx(wizard=wz)
    state = run(step1_custom(update, ctx))
    assert state == COPY_CUSTOM
    assert ctx.user_data["wizard"]["custom_field"] == "amount"


def test_21_step2_keep_goes_to_confirm():
    wz = _init_wizard(_FAKE_WALLET)
    update = _make_update(callback_data="wizard:keep")
    ctx = _make_ctx(wizard=wz)
    state = run(step2_keep(update, ctx))
    assert state == COPY_CONFIRM
    update.callback_query.message.edit_text.assert_called_once()


def test_22_step2_edit_shows_risk_grid_stays_risk():
    wz = _init_wizard(_FAKE_WALLET)
    update = _make_update(callback_data="wizard:risk:edit")
    ctx = _make_ctx(wizard=wz)
    state = run(step2_edit(update, ctx))
    assert state == COPY_RISK
    update.callback_query.message.edit_text.assert_called_once()


def test_23_step3_confirm_creates_task_returns_end():
    from telegram.ext import ConversationHandler
    wz = _init_wizard(_FAKE_WALLET)
    wz["copy_amount"] = Decimal("5.00")
    update = _make_update(callback_data="wizard:confirm")
    ctx = _make_ctx(wizard=wz)
    fake_task = _make_task()
    with _mock_resolve_user(), \
         patch.object(ct_mod.repo, "create_task", new=AsyncMock(return_value=fake_task)):
        state = run(step3_confirm(update, ctx))
    assert state == ConversationHandler.END
    assert "wizard" not in ctx.user_data


def test_24_wizard_cancel_returns_end():
    from telegram.ext import ConversationHandler
    wz = _init_wizard(_FAKE_WALLET)
    update = _make_update(callback_data="wizard:cancel")
    ctx = _make_ctx(wizard=wz)
    state = run(wizard_cancel(update, ctx))
    assert state == ConversationHandler.END
    assert "wizard" not in ctx.user_data


def test_25_wizard_enter_edit_shows_edit_screen():
    task = _make_task()
    update = _make_update(callback_data=f"copytrade:edit:{_FAKE_TASK_ID}")
    ctx = _make_ctx()
    with _mock_resolve_user(), \
         patch.object(ct_mod.repo, "get_task", new=AsyncMock(return_value=task)):
        state = run(wizard_enter_edit(update, ctx))
    assert state == COPY_EDIT
    update.callback_query.message.edit_text.assert_called_once()


def test_26_edit_pause_toggles_and_stays_copy_edit():
    task = _make_task(status="paused")
    update = _make_update(callback_data=f"wizard:epause:{_FAKE_TASK_ID}")
    ctx = _make_ctx(wizard={"edit_task_id": str(_FAKE_TASK_ID)})
    with _mock_resolve_user(), \
         patch.object(ct_mod.repo, "toggle_pause", new=AsyncMock(return_value="active")), \
         patch.object(ct_mod.repo, "get_task", new=AsyncMock(return_value=task)):
        state = run(edit_pause(update, ctx))
    assert state == COPY_EDIT


def test_27_edit_delete_ask_shows_confirm_stays_edit():
    update = _make_update(callback_data=f"wizard:edel:ask:{_FAKE_TASK_ID}")
    ctx = _make_ctx()
    state = run(edit_delete_ask(update, ctx))
    assert state == COPY_EDIT
    update.callback_query.message.edit_text.assert_called_once()


def test_28_edit_delete_confirm_deletes_returns_end():
    from telegram.ext import ConversationHandler
    update = _make_update(callback_data=f"wizard:edel:yes:{_FAKE_TASK_ID}")
    ctx = _make_ctx()
    with _mock_resolve_user(), \
         patch.object(ct_mod.repo, "delete_task", new=AsyncMock(return_value=True)):
        state = run(edit_delete_confirm(update, ctx))
    assert state == ConversationHandler.END


def test_29_edit_delete_cancel_returns_edit_screen():
    task = _make_task()
    update = _make_update(callback_data=f"wizard:edel:no:{_FAKE_TASK_ID}")
    ctx = _make_ctx()
    with _mock_resolve_user(), \
         patch.object(ct_mod.repo, "get_task", new=AsyncMock(return_value=task)):
        state = run(edit_delete_cancel(update, ctx))
    assert state == COPY_EDIT
    update.callback_query.message.edit_text.assert_called_once()


def test_30_custom_input_valid_amount_advances_to_risk():
    wz = _init_wizard(_FAKE_WALLET)
    wz["custom_field"] = "amount"
    wz["custom_context"] = "step1"
    wz["return_state"] = COPY_AMOUNT
    update = _make_update(text="15")
    ctx = _make_ctx(wizard=wz)
    state = run(custom_input_handler(update, ctx))
    assert state == COPY_RISK
    assert ctx.user_data["wizard"]["copy_amount"] == Decimal("15")


def test_31_custom_input_invalid_text_stays_custom():
    wz = _init_wizard(_FAKE_WALLET)
    wz["custom_field"] = "amount"
    wz["custom_context"] = "step1"
    update = _make_update(text="notanumber")
    ctx = _make_ctx(wizard=wz)
    state = run(custom_input_handler(update, ctx))
    assert state == COPY_CUSTOM
    update.message.reply_text.assert_called_once()
    args = update.message.reply_text.call_args[0]
    assert "Invalid" in args[0]


def test_32_wizard_fallback_text_shows_hint():
    update = _make_update(text="random gibberish")
    ctx = _make_ctx()
    state = run(wizard_fallback_text(update, ctx))
    assert state is None
    update.message.reply_text.assert_called_once()
    args = update.message.reply_text.call_args[0]
    assert "button" in args[0].lower() or "menu" in args[0].lower()


def test_33_build_wizard_handler_returns_conversation_handler():
    from telegram.ext import ConversationHandler
    handler = build_wizard_handler()
    assert isinstance(handler, ConversationHandler)
