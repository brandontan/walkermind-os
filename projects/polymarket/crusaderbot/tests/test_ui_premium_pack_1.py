"""Hermetic tests for Track G: UI Premium Pack 1.

Coverage:
  Animated entry sequence (TradeNotifier.animated_entry_sequence)
    1.  Happy path — initial send + 3 edits
    2.  Initial send failure → falls back to notify_entry (static)
    3.  Edit failure → falls back to notifications.send (new message)
    4.  Strategy label included in final card when strategy_type != 'manual'
    5.  Strategy label omitted when strategy_type == 'manual'
    6.  NO side uses correct icon

  Rich market card — _build_market_card
    7.  Basic card contains title, YES/NO prices, dates
    8.  Signal fields rendered when provided
    9.  Signal fields absent when not provided
    10. Missing tokens → dashes for prices
    11. Market with no question falls back to title key

  Formatting helpers
    12. _fmt_volume millions
    13. _fmt_volume thousands
    14. _fmt_volume small
    15. _fmt_volume invalid input → dash
    16. _fmt_date ISO prefix extraction
    17. _fmt_date None → dash

  Market card keyboard
    18. Four buttons in 2×2 layout
    19. All callback_data values ≤ 64 bytes

  get_market_by_slug integration helper
    20. Returns first market from list response
    21. Returns None on API failure

No live DB, no live Telegram, no live HTTP. All external calls patched.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from projects.polymarket.crusaderbot.bot.handlers.market_card import (
    _build_market_card,
    _fmt_date,
    _fmt_volume,
)
from projects.polymarket.crusaderbot.bot.keyboards.market_card import market_card_kb
from projects.polymarket.crusaderbot.services.trade_notifications import TradeNotifier

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

_TG_ID = 100001
_MARKET_ID = "market-abc-001"
_MARKET_Q = "Will X happen before year end?"

_SAMPLE_MARKET = {
    "question": "Will X happen before year end?",
    "slug": "will-x-happen",
    "tokens": [
        {"outcome": "YES", "price": "0.650"},
        {"outcome": "NO",  "price": "0.350"},
    ],
    "volume": "1500000",
    "volume_num": 1_500_000.0,
    "liquidity": "250000",
    "liquidity_num": 250_000.0,
    "end_date_iso": "2026-11-05T00:00:00.000Z",
}


# ---------------------------------------------------------------------------
# 1. Animated entry — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_animated_entry_happy_path():
    """Full 4-step sequence: send_message once, edit_message_text three times."""
    mock_msg = MagicMock()
    mock_msg.message_id = 42
    mock_msg.chat_id = _TG_ID

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock(return_value=mock_msg)
    mock_bot.edit_message_text = AsyncMock()

    with (
        patch(
            "projects.polymarket.crusaderbot.services.trade_notifications.notifier.notifications"
        ) as mock_notifs,
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        mock_notifs.get_bot.return_value = mock_bot

        await TradeNotifier().animated_entry_sequence(
            telegram_user_id=_TG_ID,
            market_id=_MARKET_ID,
            market_question=_MARKET_Q,
            side="YES",
            size_usdc=Decimal("50.00"),
            price=0.65,
            tp_pct=0.20,
            sl_pct=0.10,
        )

    mock_bot.send_message.assert_awaited_once_with(
        chat_id=_TG_ID, text="🔍 Scanning markets..."
    )
    assert mock_bot.edit_message_text.await_count == 3


# ---------------------------------------------------------------------------
# 2. Animated entry — initial send failure falls back to static notify_entry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_animated_entry_send_failure_fallback():
    """Initial send_message failure → falls back to static notify_entry."""
    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock(side_effect=Exception("telegram down"))

    with (
        patch(
            "projects.polymarket.crusaderbot.services.trade_notifications.notifier.notifications"
        ) as mock_notifs,
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        mock_notifs.get_bot.return_value = mock_bot
        mock_notifs.send = AsyncMock(return_value=True)

        await TradeNotifier().animated_entry_sequence(
            telegram_user_id=_TG_ID,
            market_id=_MARKET_ID,
            market_question=_MARKET_Q,
            side="YES",
            size_usdc=Decimal("50.00"),
            price=0.65,
            tp_pct=None,
            sl_pct=None,
        )

    # Fallback path uses notifications.send (static notify_entry)
    mock_notifs.send.assert_awaited_once()


# ---------------------------------------------------------------------------
# 3. Animated entry — edit failure falls back to notifications.send
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_animated_entry_edit_failure_fallback():
    """Edit failures fall back to notifications.send for each step."""
    mock_msg = MagicMock()
    mock_msg.message_id = 42
    mock_msg.chat_id = _TG_ID

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock(return_value=mock_msg)
    mock_bot.edit_message_text = AsyncMock(side_effect=Exception("message too old"))

    with (
        patch(
            "projects.polymarket.crusaderbot.services.trade_notifications.notifier.notifications"
        ) as mock_notifs,
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        mock_notifs.get_bot.return_value = mock_bot
        mock_notifs.send = AsyncMock(return_value=True)

        await TradeNotifier().animated_entry_sequence(
            telegram_user_id=_TG_ID,
            market_id=_MARKET_ID,
            market_question=_MARKET_Q,
            side="YES",
            size_usdc=Decimal("25.00"),
            price=0.65,
            tp_pct=None,
            sl_pct=None,
        )

    # 3 edits failed → 3 fallback sends
    assert mock_notifs.send.await_count == 3


# ---------------------------------------------------------------------------
# 4. Strategy label in final card
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_animated_entry_strategy_label_in_final_card():
    """strategy_type (not 'manual') appears in the final confirmation card."""
    mock_msg = MagicMock()
    mock_msg.message_id = 42
    mock_msg.chat_id = _TG_ID

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock(return_value=mock_msg)
    mock_bot.edit_message_text = AsyncMock()

    with (
        patch(
            "projects.polymarket.crusaderbot.services.trade_notifications.notifier.notifications"
        ) as mock_notifs,
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        mock_notifs.get_bot.return_value = mock_bot

        await TradeNotifier().animated_entry_sequence(
            telegram_user_id=_TG_ID,
            market_id=_MARKET_ID,
            market_question=_MARKET_Q,
            side="YES",
            size_usdc=Decimal("50.00"),
            price=0.65,
            tp_pct=None,
            sl_pct=None,
            strategy_type="signal_following",
        )

    final_call_kwargs = mock_bot.edit_message_text.await_args_list[-1]
    final_text = final_call_kwargs[1].get("text", "") or final_call_kwargs[0][0]
    assert "signal_following" in final_text


# ---------------------------------------------------------------------------
# 5. Manual strategy omitted from final card
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_animated_entry_manual_strategy_omitted():
    """strategy_type='manual' is NOT appended to the final card."""
    mock_msg = MagicMock()
    mock_msg.message_id = 42
    mock_msg.chat_id = _TG_ID

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock(return_value=mock_msg)
    mock_bot.edit_message_text = AsyncMock()

    with (
        patch(
            "projects.polymarket.crusaderbot.services.trade_notifications.notifier.notifications"
        ) as mock_notifs,
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        mock_notifs.get_bot.return_value = mock_bot

        await TradeNotifier().animated_entry_sequence(
            telegram_user_id=_TG_ID,
            market_id=_MARKET_ID,
            market_question=_MARKET_Q,
            side="YES",
            size_usdc=Decimal("50.00"),
            price=0.65,
            tp_pct=None,
            sl_pct=None,
            strategy_type="manual",
        )

    final_call_kwargs = mock_bot.edit_message_text.await_args_list[-1]
    final_text = final_call_kwargs[1].get("text", "") or final_call_kwargs[0][0]
    assert "Strategy:" not in final_text


# ---------------------------------------------------------------------------
# 6. NO side icon
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_animated_entry_no_side_icon():
    """NO side uses the down-chart icon in the final card."""
    mock_msg = MagicMock()
    mock_msg.message_id = 42
    mock_msg.chat_id = _TG_ID

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock(return_value=mock_msg)
    mock_bot.edit_message_text = AsyncMock()

    with (
        patch(
            "projects.polymarket.crusaderbot.services.trade_notifications.notifier.notifications"
        ) as mock_notifs,
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        mock_notifs.get_bot.return_value = mock_bot

        await TradeNotifier().animated_entry_sequence(
            telegram_user_id=_TG_ID,
            market_id=_MARKET_ID,
            market_question=_MARKET_Q,
            side="no",
            size_usdc=Decimal("50.00"),
            price=0.35,
            tp_pct=None,
            sl_pct=None,
        )

    final_call_kwargs = mock_bot.edit_message_text.await_args_list[-1]
    final_text = final_call_kwargs[1].get("text", "") or final_call_kwargs[0][0]
    assert "📉" in final_text
    assert "NO" in final_text


# ---------------------------------------------------------------------------
# 7. _build_market_card — basic rendering
# ---------------------------------------------------------------------------


def test_build_market_card_basic():
    card = _build_market_card(_SAMPLE_MARKET)
    assert "Will X happen" in card
    assert "YES" in card
    assert "$0.650" in card
    assert "NO" in card
    assert "$0.350" in card
    assert "2026-11-05" in card
    assert "──────────────────" in card


# ---------------------------------------------------------------------------
# 8. Signal fields rendered when provided
# ---------------------------------------------------------------------------


def test_build_market_card_with_signal_fields():
    card = _build_market_card(
        _SAMPLE_MARKET,
        signal_type="momentum",
        strategy_name="signal_following",
        confidence_pct=78.5,
    )
    assert "momentum" in card
    # strategy_name is Markdown-escaped; underscores become \_
    assert "signal" in card and "following" in card
    assert "78%" in card


# ---------------------------------------------------------------------------
# 9. Signal fields absent when not provided
# ---------------------------------------------------------------------------


def test_build_market_card_no_signal_fields():
    card = _build_market_card(_SAMPLE_MARKET)
    assert "Signal:" not in card
    assert "Confidence:" not in card


# ---------------------------------------------------------------------------
# 10. Missing tokens → dashes
# ---------------------------------------------------------------------------


def test_build_market_card_missing_tokens():
    market = {"question": "Test?", "volume": "0", "liquidity": "0"}
    card = _build_market_card(market)
    assert "Test?" in card
    assert "—" in card


# ---------------------------------------------------------------------------
# 11. Falls back to 'title' key when 'question' absent
# ---------------------------------------------------------------------------


def test_build_market_card_title_fallback():
    market = {**_SAMPLE_MARKET, "question": None, "title": "Fallback Title"}
    card = _build_market_card(market)
    assert "Fallback Title" in card


# ---------------------------------------------------------------------------
# 12-16. Formatting helpers
# ---------------------------------------------------------------------------


def test_fmt_volume_millions():
    assert _fmt_volume(1_500_000) == "$1.5M"


def test_fmt_volume_thousands():
    assert _fmt_volume(250_000) == "$250.0K"


def test_fmt_volume_small():
    assert _fmt_volume(500) == "$500.00"


def test_fmt_volume_invalid():
    assert _fmt_volume(None) == "—"


def test_fmt_date_iso():
    assert _fmt_date("2026-11-05T00:00:00.000Z") == "2026-11-05"


def test_fmt_date_none():
    assert _fmt_date(None) == "—"


# ---------------------------------------------------------------------------
# 18. Market card keyboard — 4 buttons in 2×2 layout
# ---------------------------------------------------------------------------


def test_market_card_kb_layout():
    kb = market_card_kb("will-x-happen")
    rows = kb.inline_keyboard
    assert len(rows) == 3
    assert len(rows[0]) == 2
    assert len(rows[1]) == 2
    assert len(rows[2]) == 1  # Home row added by _common.home_row
    buttons = [btn for row in rows for btn in row]
    labels = [btn.text for btn in buttons]
    assert "Buy YES" in labels
    assert "Buy NO" in labels
    assert "Set Alert" in labels
    assert "Details" in labels
    assert "🏠 Home" in labels


# ---------------------------------------------------------------------------
# 19. Callback data ≤ 64 bytes
# ---------------------------------------------------------------------------


def test_market_card_kb_callback_data_length():
    slug = "this-is-a-fairly-long-polymarket-market-slug-for-testing-purposes"
    kb = market_card_kb(slug)
    for row in kb.inline_keyboard:
        for btn in row:
            assert len(btn.callback_data.encode()) <= 64, (
                f"callback_data too long ({len(btn.callback_data)} chars): "
                f"{btn.callback_data!r}"
            )


# ---------------------------------------------------------------------------
# 20-21. get_market_by_slug
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_market_by_slug_returns_first_market():
    """Returns the first market from a list API response."""
    market_a = {"slug": "test-slug", "question": "Test?"}
    market_b = {"slug": "other-slug", "question": "Other?"}

    with (
        patch(
            "projects.polymarket.crusaderbot.integrations.polymarket.get_cache",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "projects.polymarket.crusaderbot.integrations.polymarket.set_cache",
            new_callable=AsyncMock,
        ),
        patch(
            "projects.polymarket.crusaderbot.integrations.polymarket._get_json",
            new_callable=AsyncMock,
            return_value=[market_a, market_b],
        ),
    ):
        from projects.polymarket.crusaderbot.integrations.polymarket import (
            get_market_by_slug,
        )
        result = await get_market_by_slug("test-slug")

    assert result is not None
    assert result["question"] == "Test?"


@pytest.mark.asyncio
async def test_get_market_by_slug_api_failure_returns_none():
    """API failure returns None without raising."""
    with (
        patch(
            "projects.polymarket.crusaderbot.integrations.polymarket.get_cache",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "projects.polymarket.crusaderbot.integrations.polymarket._get_json",
            new_callable=AsyncMock,
            side_effect=Exception("network error"),
        ),
    ):
        from projects.polymarket.crusaderbot.integrations.polymarket import (
            get_market_by_slug,
        )
        result = await get_market_by_slug("missing-slug")

    assert result is None
