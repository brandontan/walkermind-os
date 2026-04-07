from __future__ import annotations

from projects.polymarket.polyquantbot.telegram.ui.keyboard import (
    build_dashboard_menu,
    build_help_menu,
    build_main_menu,
    build_markets_menu,
    build_portfolio_menu,
    build_portfolio_trade_menu,
    build_settings_menu,
)
from projects.polymarket.polyquantbot.telegram.ui.reply_keyboard import REPLY_MENU_MAP


def _callback_values(keyboard: list[list[dict[str, str]]]) -> set[str]:
    return {btn["callback_data"] for row in keyboard for btn in row}


def test_reply_keyboard_is_authoritative_five_root_sections() -> None:
    assert set(REPLY_MENU_MAP.values()) == {"dashboard", "portfolio", "markets", "settings", "help"}


def test_main_menu_alias_returns_dashboard_context_only() -> None:
    assert _callback_values(build_main_menu()) == {
        "action:dashboard_home",
        "action:dashboard_system",
        "action:dashboard_refresh_all",
    }


def test_portfolio_menu_has_only_contextual_actions() -> None:
    assert _callback_values(build_portfolio_menu()) == {
        "action:portfolio_wallet",
        "action:portfolio_positions",
        "action:portfolio_exposure",
        "action:portfolio_pnl",
        "action:portfolio_performance",
        "action:portfolio_trade",
    }


def test_portfolio_trade_menu_mvp_actions_only() -> None:
    assert _callback_values(build_portfolio_trade_menu()) == {
        "action:trade_signal",
        "action:trade_paper_execute",
        "action:trade_kill_switch",
        "action:trade_status",
        "action:portfolio",
    }


def test_markets_menu_keeps_scope_controls_without_root_duplication() -> None:
    actions = _callback_values(build_markets_menu(all_markets_enabled=True))
    assert actions == {
        "action:markets_overview",
        "action:markets_all_toggle",
        "action:markets_categories",
        "action:markets_active_scope",
        "action:markets_refresh_all",
    }


def test_settings_and_help_menus_are_contextual_only() -> None:
    assert "action:back_main" not in _callback_values(build_settings_menu())
    assert "action:back_main" not in _callback_values(build_help_menu())
