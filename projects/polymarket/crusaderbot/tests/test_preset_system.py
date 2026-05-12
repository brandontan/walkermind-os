"""Hermetic tests for the Phase 5C/5D strategy preset system.

No DB, no Telegram. The handler module is exercised by patching ``users``
helpers, ``get_settings_for``, and ledger reads so each scenario verifies
the user-visible flow plus the persistence calls that follow.

Coverage:
  * Preset definitions: count, ordering, hard-cap compliance, recommended
  * Keyboards: picker / confirm / status / switch / stop callback wiring
  * setup_root routing: preset-active vs preset-not-set
  * Activation: writes config + flips auto_trade_on, paper-only guard
  * Pause / Resume / Stop / Switch: persistence + UI follow-up
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from projects.polymarket.crusaderbot.bot.handlers import presets as presets_h
from projects.polymarket.crusaderbot.bot.handlers import setup as setup_h
from projects.polymarket.crusaderbot.bot.keyboards.presets import (
    preset_confirm, preset_picker, preset_status, preset_stop_confirm,
    preset_switch_confirm,
)
from projects.polymarket.crusaderbot.domain.preset import (
    PRESETS, PRESET_ORDER, RECOMMENDED_PRESET, get_preset, list_presets,
)
from projects.polymarket.crusaderbot.domain.risk.constants import MAX_POSITION_PCT


# ---------- Preset definitions ----------------------------------------------

def test_three_presets_defined():
    assert len(PRESETS) == 3
    assert set(PRESET_ORDER) == set(PRESETS.keys())


def test_preset_order_matches_spec():
    assert PRESET_ORDER == ("signal_sniper", "value_hunter", "full_auto")


def test_recommended_is_signal_sniper():
    assert RECOMMENDED_PRESET == "signal_sniper"


def test_whale_mirror_and_hybrid_removed():
    assert "whale_mirror" not in PRESETS
    assert "hybrid" not in PRESETS


def test_presets_obey_hard_position_cap():
    # CLAUDE.md hard rule: no preset can exceed MAX_POSITION_PCT (=0.10).
    for p in list_presets():
        assert p.max_position_pct <= MAX_POSITION_PCT, p.key


def test_presets_capital_under_full_kelly():
    # No preset may use 100% capital — full Kelly is forbidden.
    for p in list_presets():
        assert 0 < p.capital_pct < 1.0, p.key


def test_get_preset_unknown_returns_none():
    assert get_preset("nope") is None
    assert get_preset("") is None
    assert get_preset("whale_mirror") is None
    assert get_preset("hybrid") is None


def test_preset_strategies_use_canonical_keys():
    allowed = {"copy_trade", "signal", "value"}
    for p in list_presets():
        assert set(p.strategies) <= allowed, p.key


def test_full_auto_excludes_copy_trade_strategy():
    # Phase 5D: copy_trade strategy belongs to Copy Trade surface, not Auto-Trade.
    p = get_preset("full_auto")
    assert p is not None
    assert "copy_trade" not in p.strategies


def test_preset_validation_rejects_oversize_capital():
    from projects.polymarket.crusaderbot.domain.preset.presets import (
        Preset, PresetBadge,
    )
    with pytest.raises(ValueError):
        Preset(
            key="bad", emoji="x", name="Bad", strategies=("signal",),
            capital_pct=1.5, tp_pct=0.1, sl_pct=0.05,
            max_position_pct=0.05, badge=PresetBadge.SAFE, description="bad",
        )


def test_preset_validation_rejects_position_over_cap():
    from projects.polymarket.crusaderbot.domain.preset.presets import (
        Preset, PresetBadge,
    )
    with pytest.raises(ValueError):
        Preset(
            key="bad", emoji="x", name="Bad", strategies=("signal",),
            capital_pct=0.5, tp_pct=0.1, sl_pct=0.05,
            max_position_pct=0.5,  # > MAX_POSITION_PCT
            badge=PresetBadge.SAFE, description="bad",
        )


# ---------- Keyboards --------------------------------------------------------

def test_picker_keyboard_has_two_col_grid_layout():
    kb = preset_picker()
    # 3 presets in 2-col grid → 2 rows (row 0 has 2, row 1 has 1)
    assert len(kb.inline_keyboard) == 2
    assert len(kb.inline_keyboard[0]) == 2
    assert len(kb.inline_keyboard[1]) == 1


def test_picker_keyboard_recommended_marked_and_first():
    kb = preset_picker()
    # Signal Sniper is recommended — first button in first row has ⭐
    first_btn = kb.inline_keyboard[0][0]
    assert "⭐" in first_btn.text
    assert first_btn.callback_data == "preset:pick:signal_sniper"


def test_picker_keyboard_all_preset_callbacks_present():
    kb = preset_picker()
    all_cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert all_cbs == [f"preset:pick:{k}" for k in PRESET_ORDER]


def test_confirm_keyboard_carries_preset_key():
    kb = preset_confirm("signal_sniper")
    cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert cbs == [
        "preset:activate:signal_sniper",
        "preset:customize:signal_sniper",
        "preset:picker",
    ]


def test_confirm_keyboard_is_two_col():
    kb = preset_confirm("value_hunter")
    # 3 buttons → row 0 has 2, row 1 has 1
    assert len(kb.inline_keyboard[0]) == 2
    assert len(kb.inline_keyboard[1]) == 1


def test_status_keyboard_swaps_pause_resume():
    cbs_running = [b.callback_data for row in preset_status(False).inline_keyboard
                   for b in row]
    cbs_paused = [b.callback_data for row in preset_status(True).inline_keyboard
                  for b in row]
    assert "preset:pause" in cbs_running
    assert "preset:resume" not in cbs_running
    assert "preset:resume" in cbs_paused
    assert "preset:pause" not in cbs_paused


def test_switch_and_stop_confirm_kb_back_target():
    sw = [b.callback_data for row in preset_switch_confirm().inline_keyboard
          for b in row]
    st = [b.callback_data for row in preset_stop_confirm().inline_keyboard
          for b in row]
    assert sw == ["preset:switch_yes", "preset:status"]
    assert st == ["preset:stop_yes", "preset:status"]


def test_switch_confirm_is_two_col():
    kb = preset_switch_confirm()
    # 2 buttons → 1 row of 2
    assert len(kb.inline_keyboard) == 1
    assert len(kb.inline_keyboard[0]) == 2


# ---------- Test doubles -----------------------------------------------------

def _make_update(*, message_text=None, callback_data=None):
    """Build a minimal Update with a recording reply_text."""
    replies = []
    sent_kw = []

    async def _capture(text, **kw):
        replies.append(text)
        sent_kw.append(kw)

    msg = SimpleNamespace(reply_text=AsyncMock(side_effect=_capture))
    if callback_data is not None:
        cq = SimpleNamespace(
            data=callback_data,
            answer=AsyncMock(),
            message=msg,
        )
        update = SimpleNamespace(
            message=None,
            callback_query=cq,
            effective_user=SimpleNamespace(id=99, username="tester"),
        )
    else:
        update = SimpleNamespace(
            message=msg if message_text is not None else None,
            callback_query=None,
            effective_user=SimpleNamespace(id=99, username="tester"),
        )
        if message_text is not None:
            msg.text = message_text
    return update, replies, sent_kw


def _patch_tier(monkeypatch, user_id, *, tier_ok=True, paused=False,
                auto_trade_on=False):
    """Patch the tier-gated helpers in the presets handler module."""
    user = {
        "id": user_id, "telegram_user_id": 99, "username": "tester",
        "access_tier": 2, "auto_trade_on": auto_trade_on, "paused": paused,
    }
    upsert = AsyncMock(return_value=user)
    monkeypatch.setattr(presets_h, "upsert_user", upsert)
    return user, upsert


def _patch_settings(monkeypatch, settings):
    monkeypatch.setattr(presets_h, "get_settings_for",
                        AsyncMock(return_value=settings))


def _patch_writes(monkeypatch):
    update_settings = AsyncMock()
    set_auto_trade = AsyncMock()
    set_paused = AsyncMock()
    monkeypatch.setattr(presets_h, "update_settings", update_settings)
    monkeypatch.setattr(presets_h, "set_auto_trade", set_auto_trade)
    monkeypatch.setattr(presets_h, "set_paused", set_paused)
    return update_settings, set_auto_trade, set_paused


def _patch_ledger(monkeypatch, balance=100.0, pnl=0.0):
    monkeypatch.setattr(presets_h, "get_balance",
                        AsyncMock(return_value=balance))
    monkeypatch.setattr(presets_h, "daily_pnl",
                        AsyncMock(return_value=pnl))


class _FakePool:
    def __init__(self, open_count=0):
        self._count = open_count

    def acquire(self):
        pool = self

        class _Cm:
            async def __aenter__(self_inner):
                class _Conn:
                    async def fetchval(self_, q, *a):
                        return pool._count
                return _Conn()

            async def __aexit__(self_inner, *exc):
                return False

        return _Cm()


def _patch_pool(monkeypatch, open_count=0):
    monkeypatch.setattr(presets_h, "get_pool",
                        lambda: _FakePool(open_count=open_count))


# ---------- show_preset_picker ----------------------------------------------

def test_show_preset_picker_renders_all_three(monkeypatch):
    uid = uuid4()
    _patch_tier(monkeypatch, uid)
    update, replies, kws = _make_update(message_text="🤖 Auto-Trade")
    asyncio.run(presets_h.show_preset_picker(
        update, ctx=SimpleNamespace(user_data={}),
    ))
    assert len(replies) == 1
    text = replies[0]
    for p in list_presets():
        assert p.name in text
    # Recommended marker in first button of first row.
    kb = kws[0]["reply_markup"]
    assert "⭐" in kb.inline_keyboard[0][0].text


def test_show_preset_picker_clears_awaiting(monkeypatch):
    uid = uuid4()
    _patch_tier(monkeypatch, uid)
    update, _replies, _kws = _make_update(message_text="🤖 Auto-Trade")
    ctx = SimpleNamespace(user_data={"awaiting": "capital_pct"})
    asyncio.run(presets_h.show_preset_picker(update, ctx=ctx))
    assert "awaiting" not in ctx.user_data


# ---------- show_preset_status ----------------------------------------------

def test_show_preset_status_falls_back_to_picker_when_no_preset(monkeypatch):
    uid = uuid4()
    _patch_tier(monkeypatch, uid)
    _patch_settings(monkeypatch, {"active_preset": None})
    update, replies, _kws = _make_update(message_text="🤖 Auto-Trade")
    asyncio.run(presets_h.show_preset_status(
        update, ctx=SimpleNamespace(user_data={}),
    ))
    # The picker text leads with "Auto-Trade Preset".
    assert "Auto-Trade Preset" in replies[0]


def test_show_preset_status_renders_running_card(monkeypatch):
    uid = uuid4()
    _patch_tier(monkeypatch, uid, auto_trade_on=True, paused=False)
    _patch_settings(monkeypatch, {"active_preset": "signal_sniper"})
    _patch_ledger(monkeypatch, balance=250.0, pnl=12.5)
    _patch_pool(monkeypatch, open_count=2)
    update, replies, kws = _make_update(message_text="🤖 Auto-Trade")
    asyncio.run(presets_h.show_preset_status(
        update, ctx=SimpleNamespace(user_data={}),
    ))
    text = replies[0]
    assert "Signal Sniper" in text
    assert "RUNNING" in text
    assert "$250.00" in text
    assert "$+12.50" in text
    assert "Open positions : `2`" in text
    cbs = [b.callback_data for row in kws[0]["reply_markup"].inline_keyboard
           for b in row]
    assert "preset:pause" in cbs


def test_show_preset_status_renders_paused_card(monkeypatch):
    uid = uuid4()
    _patch_tier(monkeypatch, uid, auto_trade_on=True, paused=True)
    _patch_settings(monkeypatch, {"active_preset": "value_hunter"})
    _patch_ledger(monkeypatch, balance=10.0, pnl=-1.0)
    _patch_pool(monkeypatch, open_count=0)
    update, replies, kws = _make_update(message_text="🤖 Auto-Trade")
    asyncio.run(presets_h.show_preset_status(
        update, ctx=SimpleNamespace(user_data={}),
    ))
    assert "PAUSED" in replies[0]
    cbs = [b.callback_data for row in kws[0]["reply_markup"].inline_keyboard
           for b in row]
    assert "preset:resume" in cbs


# ---------- _on_pick (confirmation card) -------------------------------------

def test_pick_renders_confirmation_with_all_values(monkeypatch):
    uid = uuid4()
    _patch_tier(monkeypatch, uid)
    update, replies, kws = _make_update(callback_data="preset:pick:value_hunter")
    ctx = SimpleNamespace(user_data={})
    asyncio.run(presets_h.preset_callback(update, ctx))
    text = replies[0]
    p = get_preset("value_hunter")
    assert p.name in text
    assert "40%" in text  # capital
    assert "+25%" in text  # TP
    assert "-12%" in text  # SL
    assert "8%" in text   # max position
    cbs = [b.callback_data for row in kws[0]["reply_markup"].inline_keyboard
           for b in row]
    assert cbs == [
        "preset:activate:value_hunter",
        "preset:customize:value_hunter",
        "preset:picker",
    ]


def test_pick_unknown_preset_replies_error(monkeypatch):
    uid = uuid4()
    _patch_tier(monkeypatch, uid)
    update, replies, _kws = _make_update(callback_data="preset:pick:nope")
    asyncio.run(presets_h.preset_callback(
        update, ctx=SimpleNamespace(user_data={}),
    ))
    assert "Unknown preset" in replies[0]


def test_pick_whale_mirror_returns_error(monkeypatch):
    uid = uuid4()
    _patch_tier(monkeypatch, uid)
    update, replies, _kws = _make_update(callback_data="preset:pick:whale_mirror")
    asyncio.run(presets_h.preset_callback(
        update, ctx=SimpleNamespace(user_data={}),
    ))
    assert "Unknown preset" in replies[0]


# ---------- _on_activate (paper) --------------------------------------------

def test_activate_paper_writes_full_config_and_turns_on(monkeypatch):
    uid = uuid4()
    _patch_tier(monkeypatch, uid, auto_trade_on=False, paused=False)
    _patch_settings(monkeypatch, {"trading_mode": "paper",
                                  "active_preset": None})
    upd_settings, set_auto, set_p = _patch_writes(monkeypatch)
    _patch_ledger(monkeypatch, balance=500.0, pnl=0.0)
    _patch_pool(monkeypatch, open_count=0)

    update, replies, _kws = _make_update(
        callback_data="preset:activate:signal_sniper",
    )
    asyncio.run(presets_h.preset_callback(
        update, ctx=SimpleNamespace(user_data={}),
    ))

    p = get_preset("signal_sniper")
    upd_settings.assert_awaited_once()
    args, kwargs = upd_settings.await_args
    assert args[0] == uid
    assert kwargs["active_preset"] == "signal_sniper"
    assert kwargs["strategy_types"] == list(p.strategies)
    assert kwargs["capital_alloc_pct"] == p.capital_pct
    assert kwargs["tp_pct"] == p.tp_pct
    assert kwargs["sl_pct"] == p.sl_pct
    assert kwargs["max_position_pct"] == p.max_position_pct
    set_auto.assert_awaited_once_with(uid, True)
    set_p.assert_awaited_once_with(uid, False)
    assert any("activated" in r for r in replies)


def test_activate_blocked_in_live_mode(monkeypatch):
    uid = uuid4()
    _patch_tier(monkeypatch, uid)
    _patch_settings(monkeypatch, {"trading_mode": "live",
                                  "active_preset": None})
    upd_settings, set_auto, set_p = _patch_writes(monkeypatch)
    update, replies, _kws = _make_update(
        callback_data="preset:activate:signal_sniper",
    )
    asyncio.run(presets_h.preset_callback(
        update, ctx=SimpleNamespace(user_data={}),
    ))
    upd_settings.assert_not_awaited()
    set_auto.assert_not_awaited()
    set_p.assert_not_awaited()
    assert any("Live trading" in r for r in replies)


# ---------- Pause / Resume / Stop / Switch -----------------------------------

def test_pause_persists_and_renders_paused_card(monkeypatch):
    uid = uuid4()
    _patch_tier(monkeypatch, uid, auto_trade_on=True, paused=False)
    _patch_settings(monkeypatch, {"active_preset": "signal_sniper"})
    upd_settings, set_auto, set_p = _patch_writes(monkeypatch)
    _patch_ledger(monkeypatch)
    _patch_pool(monkeypatch)
    update, replies, kws = _make_update(callback_data="preset:pause")
    asyncio.run(presets_h.preset_callback(
        update, ctx=SimpleNamespace(user_data={}),
    ))
    set_p.assert_awaited_with(uid, True)
    assert any("paused" in r.lower() for r in replies)


def test_resume_persists_and_renders_running_card(monkeypatch):
    uid = uuid4()
    _patch_tier(monkeypatch, uid, auto_trade_on=True, paused=True)
    _patch_settings(monkeypatch, {"active_preset": "signal_sniper"})
    upd_settings, set_auto, set_p = _patch_writes(monkeypatch)
    _patch_ledger(monkeypatch)
    _patch_pool(monkeypatch)
    update, replies, _kws = _make_update(callback_data="preset:resume")
    asyncio.run(presets_h.preset_callback(
        update, ctx=SimpleNamespace(user_data={}),
    ))
    set_p.assert_awaited_with(uid, False)
    assert any("resumed" in r.lower() for r in replies)


def test_stop_yes_clears_preset_and_stops(monkeypatch):
    uid = uuid4()
    _patch_tier(monkeypatch, uid, auto_trade_on=True, paused=False)
    _patch_settings(monkeypatch, {"active_preset": "signal_sniper"})
    upd_settings, set_auto, set_p = _patch_writes(monkeypatch)
    update, replies, _kws = _make_update(callback_data="preset:stop_yes")
    asyncio.run(presets_h.preset_callback(
        update, ctx=SimpleNamespace(user_data={}),
    ))
    upd_settings.assert_awaited_once_with(
        uid, active_preset=None, max_position_pct=None,
    )
    set_auto.assert_awaited_once_with(uid, False)
    set_p.assert_awaited_once_with(uid, False)
    assert any("stopped" in r.lower() for r in replies)


def test_switch_yes_clears_preset_and_shows_picker(monkeypatch):
    uid = uuid4()
    _patch_tier(monkeypatch, uid, auto_trade_on=True, paused=False)
    upd_settings, set_auto, set_p = _patch_writes(monkeypatch)
    update, replies, _kws = _make_update(callback_data="preset:switch_yes")
    asyncio.run(presets_h.preset_callback(
        update, ctx=SimpleNamespace(user_data={}),
    ))
    upd_settings.assert_awaited_once_with(
        uid, active_preset=None, max_position_pct=None,
    )
    set_auto.assert_awaited_once_with(uid, False)
    set_p.assert_awaited_once_with(uid, False)
    # Picker text was rendered after the switch.
    assert any("Auto-Trade Preset" in r for r in replies)


def test_stop_intent_shows_confirmation(monkeypatch):
    uid = uuid4()
    _patch_tier(monkeypatch, uid)
    update, replies, kws = _make_update(callback_data="preset:stop")
    asyncio.run(presets_h.preset_callback(
        update, ctx=SimpleNamespace(user_data={}),
    ))
    cbs = [b.callback_data for row in kws[0]["reply_markup"].inline_keyboard
           for b in row]
    assert "preset:stop_yes" in cbs


def test_switch_intent_shows_confirmation(monkeypatch):
    uid = uuid4()
    _patch_tier(monkeypatch, uid)
    update, replies, kws = _make_update(callback_data="preset:switch")
    asyncio.run(presets_h.preset_callback(
        update, ctx=SimpleNamespace(user_data={}),
    ))
    cbs = [b.callback_data for row in kws[0]["reply_markup"].inline_keyboard
           for b in row]
    assert "preset:switch_yes" in cbs


# ---------- setup.setup_root routing ----------------------------------------

def test_setup_root_routes_to_picker_when_no_preset(monkeypatch):
    # UX Overhaul: setup_root always shows the strategy card regardless of preset.
    uid = uuid4()
    user = {"id": uid, "access_tier": 2}
    monkeypatch.setattr(setup_h, "upsert_user",
                        AsyncMock(return_value=user))
    update, replies, kws = _make_update(message_text="🤖 Auto-Trade")
    asyncio.run(setup_h.setup_root(update, ctx=SimpleNamespace(user_data={})))
    assert replies, "setup_root must send a message"
    assert "Auto-Trade" in replies[0] or "Strategy" in replies[0]
    cbs = [b.callback_data for row in kws[0]["reply_markup"].inline_keyboard
           for b in row]
    assert any(c.startswith("strategy:") for c in cbs)


def test_setup_root_routes_to_status_when_preset_active(monkeypatch):
    # UX Overhaul: setup_root always shows the strategy card regardless of preset.
    uid = uuid4()
    user = {"id": uid, "access_tier": 2}
    monkeypatch.setattr(setup_h, "upsert_user",
                        AsyncMock(return_value=user))
    update, replies, kws = _make_update(message_text="🤖 Auto-Trade")
    asyncio.run(setup_h.setup_root(update, ctx=SimpleNamespace(user_data={})))
    assert replies, "setup_root must send a message"
    cbs = [b.callback_data for row in kws[0]["reply_markup"].inline_keyboard
           for b in row]
    assert any(c.startswith("strategy:") for c in cbs)
