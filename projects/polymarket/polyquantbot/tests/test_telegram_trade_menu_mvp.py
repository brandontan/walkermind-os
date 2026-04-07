from __future__ import annotations

from projects.polymarket.polyquantbot.telegram.ui.keyboard import build_portfolio_menu, build_trade_menu
from projects.polymarket.polyquantbot.telegram.ui.reply_keyboard import REPLY_MENU_MAP


def _callback_values(keyboard: list[list[dict[str, str]]]) -> set[str]:
    return {button["callback_data"] for row in keyboard for button in row}


def test_trade_menu_mvp_root_reply_keyboard_keeps_approved_five_item_contract() -> None:
    assert set(REPLY_MENU_MAP.values()) == {"dashboard", "portfolio", "markets", "settings", "help"}


def test_trade_menu_mvp_portfolio_contains_trade_entry() -> None:
    actions = _callback_values(build_portfolio_menu())
    assert "action:portfolio_trade" in actions


def test_trade_menu_mvp_trade_submenu_contains_only_approved_actions() -> None:
    assert _callback_values(build_trade_menu()) == {
        "action:trade_signal",
        "action:trade_paper_execute",
        "action:trade_kill_switch",
        "action:trade_status",
    }
