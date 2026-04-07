from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from projects.polymarket.polyquantbot.telegram.ui.keyboard import build_paper_wallet_menu


def _callback_values(keyboard: list[list[dict[str, str]]]) -> set[str]:
    return {button["callback_data"] for row in keyboard for button in row}


def test_trade_menu_mvp_contains_expected_trade_actions() -> None:
    """Phase-0 guard: ensure the paper wallet trade menu contract is present."""
    assert _callback_values(build_paper_wallet_menu()) == {
        "action:trade",
        "action:exposure",
        "action:wallet",
        "action:back_main",
    }
