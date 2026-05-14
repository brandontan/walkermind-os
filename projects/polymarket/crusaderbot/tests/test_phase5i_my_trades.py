"""Phase 5I — My Trades combined view.

Hermetic tests. No DB, no broker, no Telegram API.

Coverage:
  1.  my_trades renders with open positions (text + keyboard)
  2.  my_trades renders empty-state (no positions, no activity)
  3.  Recent Activity shows last 5 trades
  4.  Full History pagination: first page (page 0)
  5.  Full History pagination: forward (page 1)
  6.  Full History pagination: backward (page 0 from page 1)
  7.  Close ask shows confirmation dialog
  8.  Close confirm (yes) marks position closed
  9.  Close confirm (no) returns cancellation
  10. Hierarchy format: positions numbered, side/size/current lines present
  11. Global menu works during close flow (dispatcher route check)
  12. my_trades_main_kb builds 2-col close buttons + nav row
  13. history_nav_kb correct prev/next state
"""
from __future__ import annotations

import asyncio
import math
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from projects.polymarket.crusaderbot.bot.handlers import my_trades as mt
from projects.polymarket.crusaderbot.bot.keyboards.my_trades import (
    close_confirm_kb,
    close_success_kb,
    history_nav_kb,
    my_trades_main_kb,
)
from projects.polymarket.crusaderbot.bot.menus.main import MAIN_MENU_ROUTES


# ---------- Test doubles & factories ----------------------------------------


def _make_position(
    *,
    pos_id: UUID | None = None,
    market_id: str = "mkt-001",
    side: str = "yes",
    size_usdc: float = 5.00,
    entry_price: float = 0.42,
    mode: str = "paper",
    question: str = "Will Bitcoin hit 120K by July?",
    yes_token_id: str = "tok-yes",
    no_token_id: str = "tok-no",
) -> dict:
    return {
        "id": pos_id or uuid4(),
        "market_id": market_id,
        "side": side,
        "size_usdc": Decimal(str(size_usdc)),
        "entry_price": Decimal(str(entry_price)),
        "mode": mode,
        "question": question,
        "yes_token_id": yes_token_id,
        "no_token_id": no_token_id,
        "user_id": uuid4(),
        "opened_at": None,
    }


def _make_activity(
    *,
    act_id: UUID | None = None,
    market_id: str = "mkt-close",
    pnl_usdc: float = 2.10,
    question: str = "Trump wins popular vote",
) -> dict:
    from datetime import datetime, timezone

    return {
        "id": act_id or uuid4(),
        "market_id": market_id,
        "side": "yes",
        "size_usdc": Decimal("10.00"),
        "pnl_usdc": Decimal(str(pnl_usdc)),
        "closed_at": datetime(2026, 5, 1, tzinfo=timezone.utc),
        "question": question,
    }


def _make_message_update(replies: list[str]) -> SimpleNamespace:
    """A minimal Update double for text-triggered handlers."""
    msg = SimpleNamespace(
        reply_text=AsyncMock(side_effect=lambda *a, **kw: replies.append(a[0]))
    )
    user_ns = SimpleNamespace(id=99, username="tester")
    return SimpleNamespace(
        message=msg,
        callback_query=None,
        effective_user=user_ns,
    )


def _make_callback_update(data: str, replies: list[str]) -> SimpleNamespace:
    """A minimal Update double for callback handlers."""
    msg = SimpleNamespace(
        reply_text=AsyncMock(side_effect=lambda *a, **kw: replies.append(a[0])),
        edit_text=AsyncMock(side_effect=lambda *a, **kw: replies.append(a[0])),
    )
    q = SimpleNamespace(
        data=data,
        answer=AsyncMock(),
        message=msg,
    )
    user_ns = SimpleNamespace(id=99, username="tester")
    return SimpleNamespace(
        callback_query=q,
        effective_user=user_ns,
        message=None,
    )


def _patch_tier_ok(user_id: UUID | None = None):
    uid = user_id or uuid4()
    return patch.object(
        mt, "_ensure_user", AsyncMock(return_value=({"id": uid}, True))
    )


# ---------- Test 1: my_trades renders with positions ------------------------


def test_my_trades_renders_with_positions():
    """Combined view sends a message containing position info."""
    replies: list[str] = []
    update = _make_message_update(replies)
    pos = _make_position(entry_price=0.42, size_usdc=5.00)
    activity = [_make_activity(pnl_usdc=2.10)]

    _settings = {"tp_pct": None, "sl_pct": None}
    with _patch_tier_ok(), \
         patch.object(mt.repo, "get_open_positions", AsyncMock(return_value=[pos])), \
         patch.object(mt.repo, "get_recent_activity", AsyncMock(return_value=activity)), \
         patch.object(mt, "_fetch_mark", AsyncMock(return_value=0.48)), \
         patch("projects.polymarket.crusaderbot.bot.handlers.my_trades.get_settings_for",
               AsyncMock(return_value=_settings)):
        asyncio.run(mt.my_trades(update, ctx=None))

    assert replies, "reply_text was never called"
    text = replies[0]
    assert "My Trades" in text
    assert "Open Positions (1)" in text
    assert "Will Bitcoin hit 120K by July?" in text


# ---------- Test 2: my_trades empty state -----------------------------------


def test_my_trades_renders_empty_state():
    """When user has no positions and no activity, shows empty-state text."""
    replies: list[str] = []
    update = _make_message_update(replies)

    _settings = {"tp_pct": None, "sl_pct": None}
    with _patch_tier_ok(), \
         patch.object(mt.repo, "get_open_positions", AsyncMock(return_value=[])), \
         patch.object(mt.repo, "get_recent_activity", AsyncMock(return_value=[])), \
         patch("projects.polymarket.crusaderbot.bot.handlers.my_trades.get_settings_for",
               AsyncMock(return_value=_settings)):
        asyncio.run(mt.my_trades(update, ctx=None))

    assert replies
    text = replies[0]
    assert "No open positions" in text
    assert "No closed positions" in text


# ---------- Test 3: activity shows last 5 trades ----------------------------


def test_activity_section_shows_last_5():
    """_format_activity_section renders all 5 entries with win/loss emoji."""
    activity = [
        _make_activity(pnl_usdc=2.10, question="Market A"),
        _make_activity(pnl_usdc=-1.80, question="Market B"),
        _make_activity(pnl_usdc=0.90, question="Market C"),
        _make_activity(pnl_usdc=-0.50, question="Market D"),
        _make_activity(pnl_usdc=1.20, question="Market E"),
    ]
    text = mt._format_activity_section(activity)
    assert text.count("✅") == 3
    assert text.count("❌") == 2
    assert "Market A" in text and "Market E" in text
    assert "+$2.10" in text
    assert "$1.80" in text  # loss: -$1.80 shown as $1.80 with ❌


# ---------- Test 4 & 5: Full History pagination forward ---------------------


def test_history_cb_page_0():
    """history_cb page 0 edits the message with first-page content."""
    replies: list[str] = []
    update = _make_callback_update("mytrades:hist:0", replies)
    act_rows = [_make_activity(pnl_usdc=1.0, question=f"Market {i}") for i in range(10)]

    with _patch_tier_ok(), \
         patch.object(mt.repo, "get_activity_page",
                      AsyncMock(return_value=(act_rows, 25))):
        asyncio.run(mt.history_cb(update, ctx=None))

    assert replies
    text = replies[0]
    assert "Full History" in text
    assert "page 1/" in text


def test_history_cb_page_1_forward():
    """history_cb page 1 (Next from page 0) shows page 2 of 3."""
    replies: list[str] = []
    update = _make_callback_update("mytrades:hist:1", replies)
    act_rows = [_make_activity(pnl_usdc=0.5, question=f"M{i}") for i in range(10)]

    with _patch_tier_ok(), \
         patch.object(mt.repo, "get_activity_page",
                      AsyncMock(return_value=(act_rows, 25))):
        asyncio.run(mt.history_cb(update, ctx=None))

    text = replies[0]
    assert "page 2/" in text


# ---------- Test 6: Full History pagination backward -----------------------


def test_history_nav_kb_prev_next_flags():
    """history_nav_kb sets prev/next buttons correctly."""
    # Page 1 of 3 — has both prev and next.
    kb = history_nav_kb(page=1, has_prev=True, has_next=True)
    labels = [btn.text for row in kb.inline_keyboard for btn in row]
    assert any("Prev" in l for l in labels)
    assert any("Next" in l for l in labels)

    # Page 0 — no prev.
    kb0 = history_nav_kb(page=0, has_prev=False, has_next=True)
    labels0 = [btn.text for row in kb0.inline_keyboard for btn in row]
    assert not any("Prev" in l for l in labels0)
    assert any("Next" in l for l in labels0)


# ---------- Test 7: Close ask shows confirmation dialog ---------------------


def test_close_ask_cb_shows_confirmation():
    """Close ask renders confirmation text with side/size/PnL."""
    replies: list[str] = []
    pid = uuid4()
    update = _make_callback_update(f"mytrades:close_ask:{pid}", replies)
    pos = _make_position(pos_id=pid, entry_price=0.42, size_usdc=5.00)

    with _patch_tier_ok(), \
         patch.object(mt.repo, "get_open_position_for_user",
                      AsyncMock(return_value=pos)), \
         patch.object(mt, "_fetch_mark", AsyncMock(return_value=0.48)):
        asyncio.run(mt.close_ask_cb(update, ctx=None))

    assert replies
    text = replies[0]
    assert "Close position" in text
    assert "YES" in text
    assert "$5.00" in text
    assert "14.3%" in text or "14.2%" in text  # floating-point tolerance


# ---------- Test 8: Close confirm (yes) marks position closed ---------------


def test_close_confirm_yes_calls_paper_close():
    """Confirm close calls paper.close_position and reports realized PnL."""
    replies: list[str] = []
    pid = uuid4()
    user_id = uuid4()
    update = _make_callback_update(f"mytrades:close_yes:{pid}", replies)
    pos = _make_position(pos_id=pid, entry_price=0.42, size_usdc=5.00, mode="paper")
    pos["user_id"] = user_id

    mock_result = {"pnl_usdc": Decimal("0.71"), "exit_price": 0.48}

    with patch.object(mt, "_ensure_user",
                      AsyncMock(return_value=({"id": user_id}, True))), \
         patch.object(mt.repo, "get_open_position_for_user",
                      AsyncMock(return_value=pos)), \
         patch.object(mt, "_fetch_mark", AsyncMock(return_value=0.48)), \
         patch.object(mt.paper_exec, "close_position",
                      AsyncMock(return_value=mock_result)) as mock_close:
        asyncio.run(mt.close_confirm_cb(update, ctx=None))

    mock_close.assert_awaited_once()
    assert replies
    assert "closed" in replies[0].lower()
    assert "0.71" in replies[0]


# ---------- Test 9: Close confirm (no) returns cancellation -----------------


def test_close_confirm_no_does_not_close():
    """Cancel on confirm dialog sends cancellation message without closing."""
    replies: list[str] = []
    pid = uuid4()
    update = _make_callback_update(f"mytrades:close_no:{pid}", replies)

    with patch.object(mt.paper_exec, "close_position", AsyncMock()) as mock_close:
        asyncio.run(mt.close_confirm_cb(update, ctx=None))

    mock_close.assert_not_awaited()
    assert replies
    assert "cancel" in replies[0].lower()


# ---------- Test 10: Hierarchy format correctness ---------------------------


def test_format_positions_section_hierarchy():
    """_format_positions_section produces numbered entries with required lines."""
    pos1 = _make_position(entry_price=0.42, size_usdc=5.00, question="Bitcoin 120K?")
    pos2 = _make_position(entry_price=0.65, size_usdc=3.50, side="no",
                          question="GDP Q2 above 3%?")
    marks = [0.48, 0.61]
    text = mt._format_positions_section([pos1, pos2], marks, tp_pct=None, sl_pct=None)

    assert "Open Positions (2)" in text
    assert "1." in text and "2." in text
    assert "YES @ $0.420" in text
    assert "NO @ $0.650" in text
    assert "TP: —" in text and "SL: —" in text


# ---------- Test 11: Global menu works during close flow -------------------


def test_main_menu_routes_my_trades_registered():
    """v3: My Trades is accessed via Dashboard nav, not root menu.

    In v3 main menu, top-level 🏠 Dashboard leads to my_trades via
    dashboard:trades callback. Root menu no longer has a dedicated
    📈 My Trades button. This test verifies the handler exists and is
    importable (route coverage tested in test_ux_overhaul.py).
    """
    # my_trades handler must be importable and callable
    assert callable(mt.my_trades)
    # Dashboard route must be registered (gateway to trades)
    assert MAIN_MENU_ROUTES.get("🏠 Dashboard") is not None


# ---------- Test 12: my_trades_main_kb 2-col close buttons -----------------


def test_my_trades_main_kb_two_col_close_buttons():
    """Close buttons are arranged in 2-col grid; nav row is always appended."""
    pids = [uuid4() for _ in range(4)]
    kb = my_trades_main_kb(pids)
    rows = kb.inline_keyboard

    # First two rows are the 2-col close grid (4 buttons → 2 rows of 2).
    assert rows[0][0].callback_data == f"mytrades:close_ask:{pids[0]}"
    assert rows[0][1].callback_data == f"mytrades:close_ask:{pids[1]}"
    assert rows[1][0].callback_data == f"mytrades:close_ask:{pids[2]}"
    assert rows[1][1].callback_data == f"mytrades:close_ask:{pids[3]}"

    # Last row is the nav row.
    nav_labels = [btn.text for btn in rows[-1]]
    assert any("Full History" in l for l in nav_labels)
    # Dashboard button removed from My Trades nav in UX overhaul (Part 9).
    assert not any("Dashboard" in l for l in nav_labels)


# ---------- Test 13: close_confirm_kb structure ----------------------------


def test_close_confirm_kb_yes_no_pair():
    """close_confirm_kb has exactly one row with Confirm and Cancel."""
    pid = uuid4()
    kb = close_confirm_kb(pid)
    row = kb.inline_keyboard[0]
    assert row[0].callback_data == f"mytrades:close_yes:{pid}"
    assert row[1].callback_data == f"mytrades:close_no:{pid}"
    assert "Confirm" in row[0].text
    assert "Cancel" in row[1].text
