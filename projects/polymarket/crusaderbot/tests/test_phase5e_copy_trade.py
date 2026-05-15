"""Hermetic tests for Phase 5E Copy Trade surface.

No DB, no Telegram API calls, no real network.

Coverage:
  * Keyboards: empty state, task list, add wallet, stats card, discover filter
  * Dashboard handler: empty state text + buttons, task-filled state
  * Paste flow: text_input ignores non-awaiting, rejects invalid, accepts valid
  * Markdown escaping: task names with _, *, [ are safe
  * Wallet stats: _parse success, _unavailable, cache hit, fetch fallback on error
  * Retry: _fetch_profile retries 3× on ClientError before returning fallback
  * Leaderboard: filter kb marks active, empty-list fallback text
"""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

# ---------- Keyboard tests (pure, no async) ----------------------------------

from projects.polymarket.crusaderbot.bot.keyboards.copy_trade import (
    copy_trade_add_wallet_kb,
    copy_trade_empty_kb,
    copy_trade_task_list_kb,
    discover_filter_kb,
    wallet_stats_kb,
)
import projects.polymarket.crusaderbot.services.copy_trade.wallet_stats as ws_mod
from projects.polymarket.crusaderbot.services.copy_trade.wallet_stats import WalletStats


def test_empty_kb_has_add_and_discover():
    kb = copy_trade_empty_kb()
    cbs = {b.callback_data for row in kb.inline_keyboard for b in row}
    assert "copytrade:add" in cbs
    assert "copytrade:discover" in cbs


def test_task_list_kb_active_shows_pause_label():
    kb = copy_trade_task_list_kb(["tid-1"], ["active"])
    labels = [b.text for row in kb.inline_keyboard for b in row]
    assert any("Pause" in l for l in labels)
    assert not any("Resume" in l for l in labels)


def test_task_list_kb_paused_shows_resume_label():
    kb = copy_trade_task_list_kb(["tid-1"], ["paused"])
    labels = [b.text for row in kb.inline_keyboard for b in row]
    assert any("Resume" in l for l in labels)


def test_task_list_kb_always_appends_nav_buttons():
    kb = copy_trade_task_list_kb(["tid-1"], ["active"])
    cbs = {b.callback_data for row in kb.inline_keyboard for b in row}
    assert "copytrade:add" in cbs
    assert "copytrade:discover" in cbs


def test_add_wallet_kb_has_paste_discover_back():
    kb = copy_trade_add_wallet_kb()
    cbs = {b.callback_data for row in kb.inline_keyboard for b in row}
    assert "copytrade:paste" in cbs
    assert "copytrade:discover" in cbs
    assert "copytrade:dashboard" in cbs


def test_wallet_stats_kb_callbacks():
    addr = "0x" + "a" * 40
    kb = wallet_stats_kb(addr)
    cbs = {b.callback_data for row in kb.inline_keyboard for b in row}
    assert f"copytrade:copy:{addr}" in cbs
    assert "copytrade:add" in cbs


def test_discover_filter_kb_marks_correct_active():
    kb = discover_filter_kb("top_wr")
    labels = [b.text for row in kb.inline_keyboard for b in row]
    assert any("✅" in l and "Top WR" in l for l in labels)
    assert not any("✅" in l and "Top PnL" in l for l in labels)


def test_discover_filter_kb_marks_top_pnl_by_default():
    kb = discover_filter_kb("top_pnl")
    labels = [b.text for row in kb.inline_keyboard for b in row]
    assert any("✅" in l and "Top PnL" in l for l in labels)
    assert not any("✅" in l and "Top WR" in l for l in labels)


# ---------- Dashboard handler -----------------------------------------------

_FAKE_USER = {"id": "00000000-0000-0000-0000-000000000001", "access_tier": 2}
_FAKE_TASK = {
    "id": "aaaaaaaa-0000-0000-0000-000000000001",
    "wallet_address": "0x" + "b" * 40,
    "task_name": "My Trade",
    "status": "active",
    "copy_amount": "5.00",
    "copy_mode": "fixed",
}
_TASK_WITH_SPECIAL_CHARS = dict(
    _FAKE_TASK,
    id="bbbbbbbb-0000-0000-0000-000000000001",
    task_name="My_Trade*[test]",
)


def _make_msg_update():
    replies, kws = [], []

    async def capture(text, **kw):
        replies.append(text)
        kws.append(kw)

    msg = SimpleNamespace(reply_text=AsyncMock(side_effect=capture))
    update = SimpleNamespace(
        message=msg,
        callback_query=None,
        effective_user=SimpleNamespace(id=1, username="u"),
    )
    return update, replies, kws


def _run_dashboard(tasks):
    from projects.polymarket.crusaderbot.bot.handlers.copy_trade import (
        menu_copytrade_handler,
    )
    update, replies, kws = _make_msg_update()
    with patch(
        "projects.polymarket.crusaderbot.bot.handlers.copy_trade.upsert_user",
        return_value=_FAKE_USER,
    ), patch(
        "projects.polymarket.crusaderbot.bot.handlers.copy_trade._list_copy_tasks",
        return_value=tasks,
    ):
        asyncio.run(menu_copytrade_handler(update, ctx=SimpleNamespace()))
    return replies, kws


def test_dashboard_empty_state_text():
    replies, _ = _run_dashboard([])
    assert len(replies) == 1
    assert "Copy Trade" in replies[0]
    assert "No wallets" in replies[0]


def test_dashboard_empty_state_inline_buttons():
    _, kws = _run_dashboard([])
    cbs = {b.callback_data for row in kws[0]["reply_markup"].inline_keyboard for b in row}
    assert "copytrade:add" in cbs
    assert "copytrade:discover" in cbs


def test_dashboard_with_tasks_shows_task_name():
    replies, _ = _run_dashboard([_FAKE_TASK])
    assert "My Trade" in replies[0]


def test_dashboard_with_tasks_shows_pause_button():
    _, kws = _run_dashboard([_FAKE_TASK])
    cbs = {b.callback_data for row in kws[0]["reply_markup"].inline_keyboard for b in row}
    assert f"copytrade:pause:{_FAKE_TASK['id']}" in cbs


def test_dashboard_renders_task_name_with_special_chars():
    """Task names with _, *, [ render literally in HTML mode (not HTML-special)."""
    replies, _ = _run_dashboard([_TASK_WITH_SPECIAL_CHARS])
    assert "My_Trade*[test]" in replies[0]


# ---------- Paste flow -------------------------------------------------------

def test_text_input_ignores_non_awaiting():
    from projects.polymarket.crusaderbot.bot.handlers.copy_trade import text_input
    update = SimpleNamespace(message=SimpleNamespace(text="hello"))
    ctx = SimpleNamespace(user_data={})
    result = asyncio.run(text_input(update, ctx))
    assert result is False


def test_text_input_rejects_invalid_address():
    from projects.polymarket.crusaderbot.bot.handlers.copy_trade import text_input
    replies = []

    async def capture(text, **kw):
        replies.append(text)

    update = SimpleNamespace(
        message=SimpleNamespace(
            text="not-valid",
            reply_text=AsyncMock(side_effect=capture),
        )
    )
    ctx = SimpleNamespace(user_data={"awaiting": "copytrade_paste"})
    result = asyncio.run(text_input(update, ctx))
    assert result is True
    assert ctx.user_data.get("awaiting") == "copytrade_paste"
    assert len(replies) == 1
    assert "Invalid" in replies[0]


def test_text_input_accepts_valid_address_and_clears_awaiting():
    from projects.polymarket.crusaderbot.bot.handlers.copy_trade import text_input
    replies = []

    async def capture(text, **kw):
        replies.append(text)

    addr = "0x" + "c" * 40
    fake_stats = WalletStats(
        address=addr, pnl_30d=100.0, win_rate=0.6, avg_trade=10.0,
        trades_count=50, active_positions=2, category="Crypto", available=True,
    )
    update = SimpleNamespace(
        message=SimpleNamespace(
            text=addr,
            reply_text=AsyncMock(side_effect=capture),
        )
    )
    ctx = SimpleNamespace(user_data={"awaiting": "copytrade_paste"})
    with patch(
        "projects.polymarket.crusaderbot.bot.handlers.copy_trade.fetch_wallet_stats",
        return_value=fake_stats,
    ):
        result = asyncio.run(text_input(update, ctx))
    assert result is True
    assert "awaiting" not in ctx.user_data
    assert len(replies) == 1


# ---------- Wallet stats service --------------------------------------------

def test_wallet_stats_parse_maps_fields():
    data = {
        "pnl30d": "250.50",
        "winRate": "0.65",
        "avgTradeSize": "12.0",
        "tradesCount": "80",
        "openPositions": "3",
        "primaryCategory": "Sports",
    }
    stats = ws_mod._parse("0x" + "e" * 40, data)
    assert stats.available is True
    assert stats.pnl_30d == 250.50
    assert stats.win_rate == 0.65
    assert stats.trades_count == 80
    assert stats.category == "Sports"


def test_wallet_stats_unavailable_has_safe_defaults():
    stats = ws_mod._unavailable("0x" + "d" * 40)
    assert stats.available is False
    assert stats.pnl_30d is None
    assert stats.trades_count == 0


def test_wallet_stats_cache_hit_skips_fetch():
    addr = "0x" + "f" * 40
    addr_key = addr.lower()
    fake = ws_mod._unavailable(addr)
    ws_mod._cache[addr_key] = (time.monotonic(), fake)
    call_count = 0

    async def mock_fetch(address):
        nonlocal call_count
        call_count += 1
        return ws_mod._unavailable(address)

    try:
        with patch.object(ws_mod, "_fetch_profile", side_effect=mock_fetch):
            result = asyncio.run(ws_mod.fetch_wallet_stats(addr))
        assert call_count == 0
        assert result is fake
    finally:
        ws_mod._cache.pop(addr_key, None)


def test_wallet_stats_cache_miss_calls_fetch():
    addr = "0x" + "9" * 40
    addr_key = addr.lower()
    ws_mod._cache.pop(addr_key, None)
    fake = WalletStats(
        address=addr, pnl_30d=50.0, win_rate=0.5, avg_trade=5.0,
        trades_count=10, active_positions=1, category="Crypto", available=True,
    )

    async def mock_fetch(address):
        return fake

    try:
        with patch.object(ws_mod, "_fetch_profile", side_effect=mock_fetch):
            result = asyncio.run(ws_mod.fetch_wallet_stats(addr))
        assert result is fake
    finally:
        ws_mod._cache.pop(addr_key, None)


def test_fetch_profile_retries_3_times_on_client_error():
    """_fetch_profile must retry up to 3 times before returning fallback."""
    addr = "0x" + "7" * 40

    # mock_resp is the object returned by session.get(url) used as async ctx mgr
    mock_resp = MagicMock()
    mock_resp.__aenter__ = AsyncMock(
        side_effect=aiohttp.ClientError("conn refused"),
    )
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.get = MagicMock(return_value=mock_resp)

    with patch("aiohttp.ClientSession", return_value=mock_session), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        result = asyncio.run(ws_mod._fetch_profile(addr))

    assert result.available is False
    assert mock_session.get.call_count == 4  # 1 initial + 3 retries


def test_fetch_profile_returns_fallback_on_non_retryable_error():
    """Non-ClientError exceptions return fallback immediately (no retry)."""
    addr = "0x" + "6" * 40

    async def bad_json(*a, **kw):
        raise ValueError("bad json")

    mock_resp = MagicMock()
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)
    mock_resp.status = 200
    mock_resp.json = bad_json

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.get = MagicMock(return_value=mock_resp)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        result = asyncio.run(ws_mod._fetch_profile(addr))

    assert result.available is False


def test_leaderboard_text_empty_shows_unavailable_message():
    from projects.polymarket.crusaderbot.bot.handlers.copy_trade import _leaderboard_text
    text = _leaderboard_text([], "top_pnl")
    assert "unavailable" in text.lower()


def test_leaderboard_text_renders_wallet_rows():
    from projects.polymarket.crusaderbot.bot.handlers.copy_trade import _leaderboard_text
    addr = "0x" + "5" * 40
    wallets = [
        WalletStats(
            address=addr, pnl_30d=500.0, win_rate=0.72, avg_trade=20.0,
            trades_count=100, active_positions=5, category="Crypto", available=True,
        )
    ]
    text = _leaderboard_text(wallets, "top_pnl")
    assert "#1" in text
    assert "Top PnL" in text
