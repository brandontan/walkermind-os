"""SENTINEL — Telegram Callback Router Test Suite.

Verifies end-to-end callback routing, inline keyboard builder correctness,
screen template output, handler return types, and fallback behavior.

Scenarios:
  CB-01  All keyboard builders return action: prefix buttons
  CB-02  build_main_menu layout — 4 buttons, 2 rows
  CB-03  build_status_menu — back_main button present
  CB-04  build_wallet_menu — back_main button present
  CB-05  build_settings_menu — back_main button present
  CB-06  build_control_menu(RUNNING) — pause + stop_confirm + back_main
  CB-07  build_control_menu(PAUSED) — resume + stop_confirm + back_main
  CB-08  build_control_menu(HALTED) — noop + back_main (no stop confirm)
  CB-09  build_strategy_menu — active strategy marked ✅, others ⬜
  CB-10  build_mode_confirm_menu — confirm + cancel buttons
  CB-11  handle_wallet returns (str, list) with wallet_menu
  CB-12  handle_wallet_balance returns (str, list) with wallet_menu
  CB-13  handle_wallet_exposure returns (str, list) with wallet_menu
  CB-14  handle_settings returns (str, list) with settings_menu
  CB-15  handle_mode_confirm_switch PAPER → shows settings menu
  CB-16  handle_mode_confirm_switch unknown mode → error + settings menu
  CB-17  handle_control returns (str, list) with control_menu
  CB-18  handle_pause — pauses system, returns control_menu(PAUSED)
  CB-19  handle_resume — RUNNING state, returns idempotent message
  CB-20  handle_kill — halts system, returns control_menu(HALTED)
  CB-21  CallbackRouter._dispatch back_main → main_screen + main_menu
  CB-22  CallbackRouter._dispatch status → status_screen + status_menu
  CB-23  CallbackRouter._dispatch wallet → wallet_screen + wallet_menu
  CB-24  CallbackRouter._dispatch settings → settings_screen + settings_menu
  CB-25  CallbackRouter._dispatch control → control_screen + control_menu
  CB-26  CallbackRouter._dispatch unknown → fallback + main_menu
  CB-27  CallbackRouter._dispatch noop → empty string (no edit)
  CB-28  CallbackRouter.route ignores non-action: callback_data
  CB-29  error_screen → formatted error string
  CB-30  main_screen → mode and state in output
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from projects.polymarket.polyquantbot.telegram.ui.keyboard import (
    build_main_menu,
    build_status_menu,
    build_wallet_menu,
    build_settings_menu,
    build_control_menu,
    build_strategy_menu,
    build_mode_confirm_menu,
    build_stop_confirm_menu,
)
from projects.polymarket.polyquantbot.telegram.ui.screens import (
    main_screen,
    settings_screen,
    control_screen,
    wallet_screen,
    error_screen,
    noop_screen,
    mode_switched_screen,
    settings_risk_screen,
    settings_notify_screen,
    settings_auto_screen,
    control_paused_screen,
    control_resumed_screen,
    control_halted_screen,
    control_stop_confirm_screen,
)
from projects.polymarket.polyquantbot.telegram.handlers.wallet import (
    handle_wallet,
    handle_wallet_balance,
    handle_wallet_exposure,
)
from projects.polymarket.polyquantbot.telegram.handlers.settings import (
    handle_settings,
    handle_mode_confirm_switch,
    handle_settings_strategy,
)
from projects.polymarket.polyquantbot.telegram.handlers.control import (
    handle_control,
    handle_pause,
    handle_resume,
    handle_kill,
)
from projects.polymarket.polyquantbot.telegram.handlers.callback_router import (
    CallbackRouter,
    ACTION_PREFIX,
)
from projects.polymarket.polyquantbot.core.system_state import (
    SystemStateManager,
    SystemState,
)
from projects.polymarket.polyquantbot.config.runtime_config import ConfigManager


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_state() -> SystemStateManager:
    sm = SystemStateManager()
    return sm


def _make_config() -> ConfigManager:
    return ConfigManager()


def _make_router(state: SystemStateManager | None = None, config: ConfigManager | None = None) -> CallbackRouter:
    sm = state or _make_state()
    cm = config or _make_config()
    cmd_handler = MagicMock()
    cmd_handler._runner = None
    cmd_handler._multi_metrics = None
    cmd_handler._allocator = None
    cmd_handler._risk_guard = None
    return CallbackRouter(
        tg_api="https://api.telegram.org/botTEST",
        cmd_handler=cmd_handler,
        state_manager=sm,
        config_manager=cm,
        mode="PAPER",
    )


def _all_buttons(keyboard: list[list[dict]]) -> list[dict]:
    """Flatten a 2-D inline keyboard into a flat list of buttons."""
    return [btn for row in keyboard for btn in row]


def _callback_data_values(keyboard: list[list[dict]]) -> list[str]:
    return [btn["callback_data"] for btn in _all_buttons(keyboard)]


# ══════════════════════════════════════════════════════════════════════════════
# CB-01  All keyboard builders produce action: prefix
# ══════════════════════════════════════════════════════════════════════════════

class TestCB01ActionPrefix:
    """Every button's callback_data must start with ``action:``."""

    def test_main_menu_all_action_prefix(self) -> None:
        for cd in _callback_data_values(build_main_menu()):
            assert cd.startswith(ACTION_PREFIX), f"Expected action: prefix, got {cd!r}"

    def test_status_menu_all_action_prefix(self) -> None:
        for cd in _callback_data_values(build_status_menu()):
            assert cd.startswith(ACTION_PREFIX)

    def test_wallet_menu_all_action_prefix(self) -> None:
        for cd in _callback_data_values(build_wallet_menu()):
            assert cd.startswith(ACTION_PREFIX)

    def test_settings_menu_all_action_prefix(self) -> None:
        for cd in _callback_data_values(build_settings_menu()):
            assert cd.startswith(ACTION_PREFIX)

    def test_control_menu_all_action_prefix(self) -> None:
        for state in ("RUNNING", "PAUSED", "HALTED"):
            for cd in _callback_data_values(build_control_menu(state)):
                assert cd.startswith(ACTION_PREFIX)

    def test_strategy_menu_all_action_prefix(self) -> None:
        km = build_strategy_menu(["ev_momentum", "mean_reversion"], active="ev_momentum")
        for cd in _callback_data_values(km):
            assert cd.startswith(ACTION_PREFIX)


# ══════════════════════════════════════════════════════════════════════════════
# CB-02  build_main_menu layout
# ══════════════════════════════════════════════════════════════════════════════

class TestCB02MainMenuLayout:
    """Main menu must have exactly 2 rows and 4 buttons total."""

    def test_two_rows(self) -> None:
        km = build_main_menu()
        assert len(km) == 2

    def test_four_buttons_total(self) -> None:
        km = build_main_menu()
        assert sum(len(row) for row in km) == 4

    def test_all_four_actions_present(self) -> None:
        cds = _callback_data_values(build_main_menu())
        assert "action:status" in cds
        assert "action:wallet" in cds
        assert "action:settings" in cds
        assert "action:control" in cds


# ══════════════════════════════════════════════════════════════════════════════
# CB-03  build_status_menu — back_main present
# ══════════════════════════════════════════════════════════════════════════════

class TestCB03StatusMenu:
    def test_back_main_present(self) -> None:
        cds = _callback_data_values(build_status_menu())
        assert "action:back_main" in cds

    def test_legacy_buttons_removed(self) -> None:
        # Health and Strategies legacy buttons remain removed.
        # Performance has been restored as a valid status menu action.
        cds = _callback_data_values(build_status_menu())
        assert "action:refresh" in cds
        assert "action:performance" in cds
        assert "action:health" not in cds
        assert "action:strategies" not in cds


# ══════════════════════════════════════════════════════════════════════════════
# CB-04  build_wallet_menu — back_main present
# ══════════════════════════════════════════════════════════════════════════════

class TestCB04WalletMenu:
    def test_back_main_present(self) -> None:
        cds = _callback_data_values(build_wallet_menu())
        assert "action:back_main" in cds

    def test_balance_and_exposure_present(self) -> None:
        cds = _callback_data_values(build_wallet_menu())
        assert "action:wallet_balance" in cds
        assert "action:wallet_exposure" in cds


# ══════════════════════════════════════════════════════════════════════════════
# CB-05  build_settings_menu — back_main present
# ══════════════════════════════════════════════════════════════════════════════

class TestCB05SettingsMenu:
    def test_back_main_present(self) -> None:
        cds = _callback_data_values(build_settings_menu())
        assert "action:back_main" in cds

    def test_all_settings_options_present(self) -> None:
        cds = _callback_data_values(build_settings_menu())
        assert "action:settings_risk" in cds
        assert "action:settings_mode" in cds
        assert "action:settings_strategy" in cds


# ══════════════════════════════════════════════════════════════════════════════
# CB-06  build_control_menu(RUNNING)
# ══════════════════════════════════════════════════════════════════════════════

class TestCB06ControlMenuRunning:
    def test_pause_present(self) -> None:
        cds = _callback_data_values(build_control_menu("RUNNING"))
        assert "action:control_pause" in cds

    def test_stop_confirm_present(self) -> None:
        cds = _callback_data_values(build_control_menu("RUNNING"))
        assert "action:control_stop_confirm" in cds

    def test_back_main_present(self) -> None:
        cds = _callback_data_values(build_control_menu("RUNNING"))
        assert "action:back_main" in cds

    def test_no_resume_when_running(self) -> None:
        cds = _callback_data_values(build_control_menu("RUNNING"))
        assert "action:control_resume" not in cds


# ══════════════════════════════════════════════════════════════════════════════
# CB-07  build_control_menu(PAUSED)
# ══════════════════════════════════════════════════════════════════════════════

class TestCB07ControlMenuPaused:
    def test_resume_present(self) -> None:
        cds = _callback_data_values(build_control_menu("PAUSED"))
        assert "action:control_resume" in cds

    def test_no_pause_when_paused(self) -> None:
        cds = _callback_data_values(build_control_menu("PAUSED"))
        assert "action:control_pause" not in cds


# ══════════════════════════════════════════════════════════════════════════════
# CB-08  build_control_menu(HALTED) — no stop confirm
# ══════════════════════════════════════════════════════════════════════════════

class TestCB08ControlMenuHalted:
    def test_noop_when_halted(self) -> None:
        cds = _callback_data_values(build_control_menu("HALTED"))
        assert "action:noop" in cds

    def test_no_stop_confirm_when_halted(self) -> None:
        cds = _callback_data_values(build_control_menu("HALTED"))
        assert "action:control_stop_confirm" not in cds

    def test_back_main_present(self) -> None:
        cds = _callback_data_values(build_control_menu("HALTED"))
        assert "action:back_main" in cds


# ══════════════════════════════════════════════════════════════════════════════
# CB-09  build_strategy_menu — active strategy marked
# ══════════════════════════════════════════════════════════════════════════════

class TestCB09StrategyMenu:
    def test_active_strategy_marked(self) -> None:
        strategies = ["ev_momentum", "mean_reversion", "liquidity_edge"]
        km = build_strategy_menu(strategies, active="ev_momentum")
        active_btn = [btn for row in km for btn in row if "ev_momentum" in btn["callback_data"]]
        assert len(active_btn) == 1
        assert "✅" in active_btn[0]["text"]

    def test_inactive_strategies_unchecked(self) -> None:
        strategies = ["ev_momentum", "mean_reversion"]
        km = build_strategy_menu(strategies, active="ev_momentum")
        inactive_btns = [btn for row in km for btn in row if "mean_reversion" in btn["callback_data"]]
        assert len(inactive_btns) == 1
        assert "⬜" in inactive_btns[0]["text"]

    def test_toggle_prefix_in_callback(self) -> None:
        km = build_strategy_menu(["ev_momentum"])
        cds = _callback_data_values(km)
        assert any("strategy_toggle_ev_momentum" in cd for cd in cds)

    def test_back_main_present(self) -> None:
        km = build_strategy_menu(["ev_momentum"])
        cds = _callback_data_values(km)
        assert "action:back_main" in cds


# ══════════════════════════════════════════════════════════════════════════════
# CB-10  build_mode_confirm_menu
# ══════════════════════════════════════════════════════════════════════════════

class TestCB10ModeConfirmMenu:
    def test_confirm_button_has_mode(self) -> None:
        km = build_mode_confirm_menu("LIVE")
        cds = _callback_data_values(km)
        assert any("mode_confirm_live" in cd for cd in cds)

    def test_cancel_button_returns_to_settings(self) -> None:
        km = build_mode_confirm_menu("LIVE")
        cds = _callback_data_values(km)
        assert "action:settings" in cds


# ══════════════════════════════════════════════════════════════════════════════
# CB-11  handle_wallet
# ══════════════════════════════════════════════════════════════════════════════

class TestCB11HandleWallet:
    async def test_returns_tuple(self) -> None:
        text, kb = await handle_wallet(mode="PAPER")
        assert isinstance(text, str)
        assert isinstance(kb, list)

    async def test_text_contains_wallet(self) -> None:
        text, _ = await handle_wallet(mode="PAPER")
        assert "WALLET" in text.upper()

    async def test_keyboard_is_wallet_menu(self) -> None:
        _, kb = await handle_wallet(mode="PAPER")
        cds = _callback_data_values(kb)
        assert "action:wallet_balance" in cds
        assert "action:wallet_exposure" in cds
        assert "action:back_main" in cds


# ══════════════════════════════════════════════════════════════════════════════
# CB-12  handle_wallet_balance
# ══════════════════════════════════════════════════════════════════════════════

class TestCB12HandleWalletBalance:
    async def test_returns_tuple(self) -> None:
        text, kb = await handle_wallet_balance()
        assert isinstance(text, str)
        assert isinstance(kb, list)

    async def test_keyboard_has_back_main(self) -> None:
        _, kb = await handle_wallet_balance()
        assert "action:back_main" in _callback_data_values(kb)


# ══════════════════════════════════════════════════════════════════════════════
# CB-13  handle_wallet_exposure
# ══════════════════════════════════════════════════════════════════════════════

class TestCB13HandleWalletExposure:
    async def test_returns_tuple(self) -> None:
        text, kb = await handle_wallet_exposure()
        assert isinstance(text, str)
        assert isinstance(kb, list)


# ══════════════════════════════════════════════════════════════════════════════
# CB-14  handle_settings
# ══════════════════════════════════════════════════════════════════════════════

class TestCB14HandleSettings:
    async def test_returns_settings_text(self) -> None:
        cm = _make_config()
        text, kb = await handle_settings(config_manager=cm, mode="PAPER")
        assert "SETTINGS" in text.upper()

    async def test_keyboard_has_back_main(self) -> None:
        cm = _make_config()
        _, kb = await handle_settings(config_manager=cm, mode="PAPER")
        assert "action:back_main" in _callback_data_values(kb)

    async def test_risk_multiplier_shown(self) -> None:
        cm = _make_config()
        text, _ = await handle_settings(config_manager=cm, mode="PAPER")
        assert "Risk" in text or "risk" in text.lower()


# ══════════════════════════════════════════════════════════════════════════════
# CB-15  handle_mode_confirm_switch PAPER
# ══════════════════════════════════════════════════════════════════════════════

class TestCB15ModeConfirmSwitch:
    async def test_switch_to_paper_succeeds(self) -> None:
        cm = _make_config()
        text, kb = await handle_mode_confirm_switch(new_mode="PAPER", config_manager=cm)
        assert "PAPER" in text
        assert isinstance(kb, list)

    async def test_switch_to_live_blocked_without_env(self) -> None:
        import os
        cm = _make_config()
        env_without_live = {k: v for k, v in os.environ.items() if k != "ENABLE_LIVE_TRADING"}
        with patch.dict(os.environ, env_without_live, clear=True):
            text, kb = await handle_mode_confirm_switch(new_mode="LIVE", config_manager=cm)
        assert "❌" in text or "Cannot" in text

    async def test_keyboard_returns_settings_menu(self) -> None:
        cm = _make_config()
        _, kb = await handle_mode_confirm_switch(new_mode="PAPER", config_manager=cm)
        cds = _callback_data_values(kb)
        assert "action:back_main" in cds


# ══════════════════════════════════════════════════════════════════════════════
# CB-16  handle_mode_confirm_switch unknown mode
# ══════════════════════════════════════════════════════════════════════════════

class TestCB16ModeConfirmUnknown:
    async def test_unknown_mode_returns_error(self) -> None:
        cm = _make_config()
        text, kb = await handle_mode_confirm_switch(new_mode="INVALID", config_manager=cm)
        assert "❌" in text or "Unknown" in text
        assert isinstance(kb, list)


# ══════════════════════════════════════════════════════════════════════════════
# CB-17  handle_control
# ══════════════════════════════════════════════════════════════════════════════

class TestCB17HandleControl:
    async def test_returns_control_screen(self) -> None:
        sm = _make_state()
        text, kb = await handle_control(state_manager=sm)
        assert "CONTROL" in text.upper()

    async def test_keyboard_is_control_menu(self) -> None:
        sm = _make_state()
        _, kb = await handle_control(state_manager=sm)
        cds = _callback_data_values(kb)
        assert "action:back_main" in cds


# ══════════════════════════════════════════════════════════════════════════════
# CB-18  handle_pause
# ══════════════════════════════════════════════════════════════════════════════

class TestCB18HandlePause:
    async def test_pause_running_system(self) -> None:
        sm = _make_state()
        assert sm.state == SystemState.RUNNING
        text, kb = await handle_pause(state_manager=sm)
        assert sm.state == SystemState.PAUSED
        assert "PAUSE" in text.upper()

    async def test_pause_idempotent(self) -> None:
        sm = _make_state()
        await handle_pause(state_manager=sm)
        assert sm.state == SystemState.PAUSED
        # Pause again — must not raise and must stay PAUSED
        text, kb = await handle_pause(state_manager=sm)
        assert sm.state == SystemState.PAUSED
        assert "already PAUSED" in text

    async def test_pause_returns_paused_control_menu(self) -> None:
        sm = _make_state()
        _, kb = await handle_pause(state_manager=sm)
        cds = _callback_data_values(kb)
        assert "action:control_resume" in cds


# ══════════════════════════════════════════════════════════════════════════════
# CB-19  handle_resume
# ══════════════════════════════════════════════════════════════════════════════

class TestCB19HandleResume:
    async def test_resume_when_already_running(self) -> None:
        sm = _make_state()
        text, kb = await handle_resume(state_manager=sm)
        assert "RUNNING" in text.upper() or "already" in text.lower()

    async def test_resume_paused_system(self) -> None:
        sm = _make_state()
        await sm.pause(reason="test")
        text, kb = await handle_resume(state_manager=sm)
        assert sm.state == SystemState.RUNNING


# ══════════════════════════════════════════════════════════════════════════════
# CB-20  handle_kill
# ══════════════════════════════════════════════════════════════════════════════

class TestCB20HandleKill:
    async def test_kill_halts_system(self) -> None:
        sm = _make_state()
        text, kb = await handle_kill(state_manager=sm)
        assert sm.state == SystemState.HALTED

    async def test_kill_text_contains_halt(self) -> None:
        sm = _make_state()
        text, _ = await handle_kill(state_manager=sm)
        assert "HALT" in text.upper() or "STOP" in text.upper()

    async def test_kill_returns_halted_control_menu(self) -> None:
        sm = _make_state()
        _, kb = await handle_kill(state_manager=sm)
        cds = _callback_data_values(kb)
        # Halted menu has noop, not pause/resume
        assert "action:back_main" in cds


# ══════════════════════════════════════════════════════════════════════════════
# CB-21  CallbackRouter._dispatch back_main
# ══════════════════════════════════════════════════════════════════════════════

class TestCB21DispatchBackMain:
    async def test_back_main_returns_main_screen(self) -> None:
        router = _make_router()
        for action in ("back_main", "start", "menu"):
            text, kb = await router._dispatch(action)
            assert "KrusaderBot" in text or "PAPER" in text
            assert "action:status" in _callback_data_values(kb)


# ══════════════════════════════════════════════════════════════════════════════
# CB-22  CallbackRouter._dispatch status
# ══════════════════════════════════════════════════════════════════════════════

class TestCB22DispatchStatus:
    async def test_status_action(self) -> None:
        router = _make_router()
        text, kb = await router._dispatch("status")
        assert "STATUS" in text.upper()
        assert "action:back_main" in _callback_data_values(kb)


# ══════════════════════════════════════════════════════════════════════════════
# CB-23  CallbackRouter._dispatch wallet
# ══════════════════════════════════════════════════════════════════════════════

class TestCB23DispatchWallet:
    async def test_wallet_action(self) -> None:
        router = _make_router()
        text, kb = await router._dispatch("wallet")
        assert "WALLET" in text.upper()
        assert "action:back_main" in _callback_data_values(kb)

    async def test_wallet_balance_action(self) -> None:
        router = _make_router()
        text, kb = await router._dispatch("wallet_balance")
        assert isinstance(text, str)

    async def test_wallet_exposure_action(self) -> None:
        router = _make_router()
        text, kb = await router._dispatch("wallet_exposure")
        assert isinstance(text, str)


# ══════════════════════════════════════════════════════════════════════════════
# CB-24  CallbackRouter._dispatch settings
# ══════════════════════════════════════════════════════════════════════════════

class TestCB24DispatchSettings:
    async def test_settings_action(self) -> None:
        router = _make_router()
        text, kb = await router._dispatch("settings")
        assert "SETTINGS" in text.upper()
        assert "action:back_main" in _callback_data_values(kb)

    async def test_settings_risk_action(self) -> None:
        router = _make_router()
        text, kb = await router._dispatch("settings_risk")
        assert "Risk" in text or "risk" in text.lower()
        assert isinstance(kb, list)

    async def test_settings_notify_action(self) -> None:
        router = _make_router()
        text, kb = await router._dispatch("settings_notify")
        assert "Notif" in text or "notif" in text.lower()

    async def test_settings_auto_action(self) -> None:
        router = _make_router()
        text, kb = await router._dispatch("settings_auto")
        assert "Auto" in text or "auto" in text.lower()

    async def test_settings_mode_action_paper(self) -> None:
        """settings_mode from PAPER mode shows LIVE as the new mode."""
        router = _make_router()
        router._mode = "PAPER"
        text, kb = await router._dispatch("settings_mode")
        assert "LIVE" in text  # shows what we'll switch to
        # Confirm button present
        cds = _callback_data_values(kb)
        assert any("mode_confirm_live" in cd for cd in cds)

    async def test_mode_confirm_paper_action(self) -> None:
        router = _make_router()
        text, kb = await router._dispatch("mode_confirm_paper")
        assert "PAPER" in text


# ══════════════════════════════════════════════════════════════════════════════
# CB-25  CallbackRouter._dispatch control
# ══════════════════════════════════════════════════════════════════════════════

class TestCB25DispatchControl:
    async def test_control_action(self) -> None:
        router = _make_router()
        text, kb = await router._dispatch("control")
        assert "CONTROL" in text.upper()
        assert "action:back_main" in _callback_data_values(kb)

    async def test_control_pause_action(self) -> None:
        router = _make_router()
        text, kb = await router._dispatch("control_pause")
        assert isinstance(text, str)
        assert isinstance(kb, list)

    async def test_control_stop_confirm_action(self) -> None:
        router = _make_router()
        text, kb = await router._dispatch("control_stop_confirm")
        cds = _callback_data_values(kb)
        assert "action:control_stop_execute" in cds


# ══════════════════════════════════════════════════════════════════════════════
# CB-26  CallbackRouter._dispatch unknown action
# ══════════════════════════════════════════════════════════════════════════════

class TestCB26DispatchUnknown:
    async def test_unknown_action_returns_main_menu(self) -> None:
        router = _make_router()
        text, kb = await router._dispatch("totally_unknown_xyz")
        assert "Unknown" in text or "action" in text.lower()
        # Falls back to main menu
        cds = _callback_data_values(kb)
        assert "action:status" in cds


# ══════════════════════════════════════════════════════════════════════════════
# CB-27  CallbackRouter._dispatch noop → empty string
# ══════════════════════════════════════════════════════════════════════════════

class TestCB27DispatchNoop:
    async def test_noop_returns_empty_string(self) -> None:
        router = _make_router()
        text, kb = await router._dispatch("noop")
        assert text == ""  # No message update


# ══════════════════════════════════════════════════════════════════════════════
# CB-28  CallbackRouter.route ignores non-action: data
# ══════════════════════════════════════════════════════════════════════════════

class TestCB28RouteIgnoresLegacyFormat:
    async def test_non_action_prefix_no_dispatch(self) -> None:
        """callback_data not starting with action: must not trigger dispatch."""
        router = _make_router()
        session = AsyncMock()

        cq = {
            "id": "cq123",
            "data": "status",  # Legacy format — no action: prefix
            "from": {"id": 999},
            "message": {"chat": {"id": 100}, "message_id": 42},
        }

        # _answer_callback is called, but _dispatch should NOT be invoked
        with patch.object(router, "_dispatch", new=AsyncMock()) as mock_dispatch, \
             patch.object(router, "_answer_callback", new=AsyncMock()):
            await router.route(session, cq)

        mock_dispatch.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# CB-29  error_screen
# ══════════════════════════════════════════════════════════════════════════════

class TestCB29ErrorScreen:
    def test_error_screen_contains_context(self) -> None:
        text = error_screen(context="wallet", error="connection timeout")
        assert "wallet" in text
        assert "connection timeout" in text

    def test_error_screen_is_string(self) -> None:
        assert isinstance(error_screen(context="test", error="oops"), str)


# ══════════════════════════════════════════════════════════════════════════════
# CB-30  main_screen
# ══════════════════════════════════════════════════════════════════════════════

class TestCB30MainScreen:
    def test_main_screen_contains_mode(self) -> None:
        text = main_screen(mode="PAPER", state="RUNNING")
        assert "PAPER" in text

    def test_main_screen_contains_state(self) -> None:
        text = main_screen(mode="PAPER", state="PAUSED")
        assert "PAUSED" in text

    def test_main_screen_contains_bot_name(self) -> None:
        text = main_screen(mode="LIVE", state="RUNNING")
        assert "KrusaderBot" in text
