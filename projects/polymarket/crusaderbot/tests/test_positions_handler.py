"""Hermetic tests for the R12d Telegram position-monitor handler.

No DB, no broker, no Telegram. Patches ``get_book`` and the per-position
force-close marker so the suite exercises:

  * Unrealized P&L formula (YES / NO)
  * Output formatters (P&L string, TP/SL string, market-title truncation)
  * Mark-price fetcher: empty-book and timeout fallbacks vs. midpoint
  * force_close_confirm Cancel branch (does NOT call the marker)
  * force_close_confirm Yes branch (calls the marker, replies success)

Tier-gate behaviour is exercised against the in-process Tier helper —
the DB-backed tier resolver path is not unit-tested here (lives in the
tier gate module's own suite).
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from projects.polymarket.crusaderbot.bot.handlers import positions as positions_h
from projects.polymarket.crusaderbot.bot.keyboards.positions import (
    force_close_confirm_kb, positions_list_kb,
)


# ---------- Pure helpers -----------------------------------------------------

def test_unrealized_pnl_yes_in_profit():
    pnl, pct = positions_h._unrealized_pnl("yes", entry=0.50, mark=0.60, size=100.0)
    # 100 USDC / 0.50 entry = 200 shares; (0.60 - 0.50) * 200 = 20.00
    assert pnl == pytest.approx(20.0)
    assert pct == pytest.approx(20.0)


def test_unrealized_pnl_yes_at_loss():
    pnl, pct = positions_h._unrealized_pnl("yes", entry=0.50, mark=0.45, size=50.0)
    assert pnl == pytest.approx(-5.0)
    assert pct == pytest.approx(-10.0)


def test_unrealized_pnl_no_in_profit():
    # NO position profits when mark < entry.
    pnl, pct = positions_h._unrealized_pnl("no", entry=0.40, mark=0.30, size=80.0)
    # 80 / 0.40 = 200 shares; (0.40 - 0.30) * 200 = 20.00
    assert pnl == pytest.approx(20.0)
    assert pct == pytest.approx(25.0)


def test_unrealized_pnl_zero_entry_safe():
    # Defensive: a degenerate row with entry=0 must not divide-by-zero.
    pnl, pct = positions_h._unrealized_pnl("yes", entry=0.0, mark=0.5, size=10.0)
    assert pnl == 0.0 and pct == 0.0


def test_format_pnl_signs():
    assert positions_h._format_pnl(12.34, 5.2) == "+12.34 (+5.2%)"
    assert positions_h._format_pnl(-3.21, -1.8) == "-3.21 (-1.8%)"


def test_format_tp_sl_both_present():
    s = positions_h._format_tp_sl(0.10, 0.05)
    assert "TP 10.0%" in s and "SL 5.0%" in s


def test_format_tp_sl_none_renders_placeholder():
    assert positions_h._format_tp_sl(None, None) == "TP/SL N/A"


def test_truncate_respects_limit():
    # 40-char limit replaces tail with an ellipsis when over.
    long = "x" * 80
    out = positions_h._truncate(long, 40)
    assert len(out) == 40 and out.endswith("…")


def test_truncate_passthrough_when_short():
    assert positions_h._truncate("short", 40) == "short"


# ---------- Mark price fetcher ----------------------------------------------

def test_fetch_mark_price_returns_midpoint():
    async def fake_get_book(token_id):
        return {"bids": [{"price": "0.49"}], "asks": [{"price": "0.51"}]}

    with patch.object(positions_h, "get_book", fake_get_book):
        mark = asyncio.run(positions_h._fetch_mark_price("tok"))
    assert mark == pytest.approx(0.50)


def test_fetch_mark_price_empty_book_returns_none():
    async def fake_get_book(token_id):
        return {"bids": [], "asks": []}

    with patch.object(positions_h, "get_book", fake_get_book):
        mark = asyncio.run(positions_h._fetch_mark_price("tok"))
    assert mark is None


def test_fetch_mark_price_timeout_returns_none():
    async def slow_get_book(token_id):
        await asyncio.sleep(10)
        return {}

    with patch.object(positions_h, "get_book", slow_get_book), \
         patch.object(positions_h, "PRICE_FETCH_TIMEOUT_SEC", 0.05):
        mark = asyncio.run(positions_h._fetch_mark_price("tok"))
    assert mark is None


def test_fetch_mark_price_no_token_id_short_circuits():
    # Should not even attempt a fetch.
    with patch.object(positions_h, "get_book", AsyncMock()) as mock:
        mark = asyncio.run(positions_h._fetch_mark_price(None))
    assert mark is None
    mock.assert_not_called()


def test_fetch_mark_price_one_side_only():
    # Asks empty — fall back to best bid.
    async def fake_get_book(token_id):
        return {"bids": [{"price": "0.40"}], "asks": []}

    with patch.object(positions_h, "get_book", fake_get_book):
        mark = asyncio.run(positions_h._fetch_mark_price("tok"))
    assert mark == pytest.approx(0.40)


# ---------- Keyboard builders -----------------------------------------------

def test_positions_list_kb_nav_only_no_force_close_rows():
    pids = [uuid4() for _ in range(3)]
    kb = positions_list_kb(pids)
    rows = kb.inline_keyboard
    assert len(rows) == 1
    assert [btn.text for btn in rows[0]] == ["⬅ Back", "🏠 Home"]
    assert [btn.callback_data for btn in rows[0]] == ["portfolio:portfolio", "nav:home"]


def test_force_close_confirm_kb_yes_no_pair():
    pid = uuid4()
    kb = force_close_confirm_kb(pid)
    row = kb.inline_keyboard[0]
    assert row[0].callback_data == f"position:fc_yes:{pid}"
    assert row[1].callback_data == f"position:fc_no:{pid}"


# ---------- force_close_confirm callback branches ---------------------------

def _fake_query(data: str, replies: list[str]) -> SimpleNamespace:
    """Build a minimal ``update.callback_query`` double that records replies."""
    msg = SimpleNamespace(reply_text=AsyncMock(side_effect=lambda *a, **kw: replies.append(a[0])))
    return SimpleNamespace(
        data=data,
        answer=AsyncMock(),
        message=msg,
    )


def test_force_close_confirm_cancel_does_not_mark():
    pid = uuid4()
    replies: list[str] = []
    update = SimpleNamespace(
        callback_query=_fake_query(f"position:fc_no:{pid}", replies),
        effective_user=SimpleNamespace(id=42, username="u"),
    )

    # Marker MUST NOT be invoked on cancel — assert by patching the symbol
    # the handler imported into its own namespace.
    with patch.object(positions_h, "mark_force_close_intent_for_position",
                      AsyncMock()) as marker, \
         patch.object(positions_h, "_ensure_tier",
                      AsyncMock(return_value=({"id": uuid4()}, True))):
        asyncio.run(positions_h.force_close_confirm(update, ctx=None))

    marker.assert_not_called()
    assert any("Cancelled" in r for r in replies)


def test_force_close_confirm_yes_calls_marker_and_replies():
    pid = uuid4()
    user_id = uuid4()
    replies: list[str] = []
    update = SimpleNamespace(
        callback_query=_fake_query(f"position:fc_yes:{pid}", replies),
        effective_user=SimpleNamespace(id=42, username="u"),
    )

    with patch.object(positions_h, "_ensure_tier",
                      AsyncMock(return_value=({"id": user_id}, True))), \
         patch.object(positions_h, "_verify_user_owns_open_position",
                      AsyncMock(return_value={"id": pid, "market_id": "m",
                                              "question": "Q?"})), \
         patch.object(positions_h, "mark_force_close_intent_for_position",
                      AsyncMock(return_value=1)) as marker:
        asyncio.run(positions_h.force_close_confirm(update, ctx=None))

    marker.assert_awaited_once_with(str(pid), user_id)
    assert any("queued" in r.lower() for r in replies)


def test_force_close_confirm_yes_already_queued_message():
    pid = uuid4()
    user_id = uuid4()
    replies: list[str] = []
    update = SimpleNamespace(
        callback_query=_fake_query(f"position:fc_yes:{pid}", replies),
        effective_user=SimpleNamespace(id=42, username="u"),
    )

    with patch.object(positions_h, "_ensure_tier",
                      AsyncMock(return_value=({"id": user_id}, True))), \
         patch.object(positions_h, "_verify_user_owns_open_position",
                      AsyncMock(return_value={"id": pid, "market_id": "m",
                                              "question": "Q?"})), \
         patch.object(positions_h, "mark_force_close_intent_for_position",
                      AsyncMock(return_value=0)):
        asyncio.run(positions_h.force_close_confirm(update, ctx=None))

    assert any("already queued" in r.lower() for r in replies)


def test_force_close_confirm_yes_position_missing():
    pid = uuid4()
    user_id = uuid4()
    replies: list[str] = []
    update = SimpleNamespace(
        callback_query=_fake_query(f"position:fc_yes:{pid}", replies),
        effective_user=SimpleNamespace(id=42, username="u"),
    )

    with patch.object(positions_h, "_ensure_tier",
                      AsyncMock(return_value=({"id": user_id}, True))), \
         patch.object(positions_h, "_verify_user_owns_open_position",
                      AsyncMock(return_value=None)), \
         patch.object(positions_h, "mark_force_close_intent_for_position",
                      AsyncMock()) as marker:
        asyncio.run(positions_h.force_close_confirm(update, ctx=None))

    marker.assert_not_called()
    assert any("not found" in r.lower() for r in replies)
