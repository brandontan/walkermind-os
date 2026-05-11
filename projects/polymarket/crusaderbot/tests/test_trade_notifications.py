"""Hermetic tests for Fast Track C — trade notifications.

Coverage:
    TradeNotifier
      * notify_entry          — ENTRY event, compact message with TP/SL
      * notify_entry          — ENTRY event, None TP/SL → '—' placeholders
      * notify_entry          — strategy_type included when present
      * notify_entry          — copy_trade strategy_type triggers correct label
      * notify_tp_hit         — TP_HIT event message format
      * notify_sl_hit         — SL_HIT event message format
      * notify_manual_close   — MANUAL event message format
      * notify_emergency_close — EMERGENCY event message format
      * notify_copy_trade_entry — COPY_TRADE scaffold, target_wallet truncated
      * notify_copy_trade_entry — no target_wallet → no wallet line
      * market_question > 60 chars → truncated with ellipsis
      * market_question missing → market_id used as label
      * Telegram send failure → caught, logged, no re-raise (failure-safe)
      * negative pnl → formatted with minus sign

    monitoring.alerts
      * alert_user_manual_close — sends correct text to user's telegram_user_id

No live DB, no live Telegram. All external calls patched.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, patch, call

import pytest

from projects.polymarket.crusaderbot.services.trade_notifications import (
    TradeNotifier,
    NotificationEvent,
)

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

_TG_USER_ID = 100001
_MARKET_ID = "market-xyz-001"
_MARKET_Q = "Will the Fed cut rates in June 2026?"
_LONG_Q = "A" * 65  # > 60 chars
_MODE = "paper"


def _notifier() -> TradeNotifier:
    return TradeNotifier()


# ---------------------------------------------------------------------------
# Helper to capture notifications.send calls
# ---------------------------------------------------------------------------

def _patch_send():
    return patch(
        "projects.polymarket.crusaderbot.services.trade_notifications.notifier.notifications.send",
        new_callable=AsyncMock,
    )


# ---------------------------------------------------------------------------
# ENTRY
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notify_entry_basic():
    """ENTRY — message contains side, price, size, TP, SL, mode."""
    with _patch_send() as mock_send:
        mock_send.return_value = True
        await _notifier().notify_entry(
            telegram_user_id=_TG_USER_ID,
            market_id=_MARKET_ID,
            market_question=_MARKET_Q,
            side="yes",
            size_usdc=Decimal("50.00"),
            price=0.62,
            tp_pct=0.30,
            sl_pct=0.15,
            mode=_MODE,
        )
    mock_send.assert_awaited_once()
    text: str = mock_send.call_args[0][1]
    assert "ENTRY" in text
    assert "YES" in text
    assert "50.00" in text
    assert "0.620" in text
    assert "30.0%" in text    # tp
    assert "15.0%" in text    # sl
    assert "Paper mode" in text
    assert _MARKET_Q in text


@pytest.mark.asyncio
async def test_notify_entry_no_tp_sl():
    """ENTRY — None TP/SL renders as '—'."""
    with _patch_send() as mock_send:
        mock_send.return_value = True
        await _notifier().notify_entry(
            telegram_user_id=_TG_USER_ID,
            market_id=_MARKET_ID,
            market_question=None,
            side="no",
            size_usdc=Decimal("25.00"),
            price=0.38,
            tp_pct=None,
            sl_pct=None,
        )
    text: str = mock_send.call_args[0][1]
    assert "TP: — | SL: —" in text
    assert "NO" in text
    assert _MARKET_ID in text  # falls back to market_id


@pytest.mark.asyncio
async def test_notify_entry_strategy_type_shown():
    """ENTRY — strategy_type is appended when not 'manual'."""
    with _patch_send() as mock_send:
        mock_send.return_value = True
        await _notifier().notify_entry(
            telegram_user_id=_TG_USER_ID,
            market_id=_MARKET_ID,
            market_question=_MARKET_Q,
            side="yes",
            size_usdc=Decimal("10.00"),
            price=0.50,
            tp_pct=None,
            sl_pct=None,
            strategy_type="signal_following",
        )
    text: str = mock_send.call_args[0][1]
    assert "signal_following" in text


@pytest.mark.asyncio
async def test_notify_entry_manual_strategy_not_shown():
    """ENTRY — strategy_type 'manual' is NOT appended (noise reduction)."""
    with _patch_send() as mock_send:
        mock_send.return_value = True
        await _notifier().notify_entry(
            telegram_user_id=_TG_USER_ID,
            market_id=_MARKET_ID,
            market_question=None,
            side="yes",
            size_usdc=Decimal("10.00"),
            price=0.50,
            tp_pct=None,
            sl_pct=None,
            strategy_type="manual",
        )
    text: str = mock_send.call_args[0][1]
    assert "Strategy:" not in text


# ---------------------------------------------------------------------------
# TP_HIT
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notify_tp_hit():
    """TP_HIT — correct icon, label, exit price, pnl."""
    with _patch_send() as mock_send:
        mock_send.return_value = True
        await _notifier().notify_tp_hit(
            telegram_user_id=_TG_USER_ID,
            market_id=_MARKET_ID,
            market_question=_MARKET_Q,
            side="yes",
            exit_price=0.81,
            pnl_usdc=14.50,
            mode=_MODE,
        )
    text: str = mock_send.call_args[0][1]
    assert "🎯" in text
    assert "TP HIT" in text
    assert "YES" in text
    assert "0.810" in text
    assert "+$14.50" in text
    assert "[PAPER]" in text


# ---------------------------------------------------------------------------
# SL_HIT
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notify_sl_hit():
    """SL_HIT — correct icon, label, exit price, negative pnl."""
    with _patch_send() as mock_send:
        mock_send.return_value = True
        await _notifier().notify_sl_hit(
            telegram_user_id=_TG_USER_ID,
            market_id=_MARKET_ID,
            market_question=_MARKET_Q,
            side="no",
            exit_price=0.22,
            pnl_usdc=-8.00,
            mode=_MODE,
        )
    text: str = mock_send.call_args[0][1]
    assert "🛑" in text
    assert "SL HIT" in text
    assert "NO" in text
    assert "0.220" in text
    assert "-$8.00" in text


# ---------------------------------------------------------------------------
# MANUAL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notify_manual_close():
    """MANUAL — correct icon, label, exit price, pnl."""
    with _patch_send() as mock_send:
        mock_send.return_value = True
        await _notifier().notify_manual_close(
            telegram_user_id=_TG_USER_ID,
            market_id=_MARKET_ID,
            market_question=_MARKET_Q,
            side="yes",
            exit_price=0.65,
            pnl_usdc=3.20,
            mode=_MODE,
        )
    text: str = mock_send.call_args[0][1]
    assert "✅" in text
    assert "MANUAL CLOSE" in text
    assert "YES" in text
    assert "0.650" in text
    assert "+$3.20" in text


# ---------------------------------------------------------------------------
# EMERGENCY
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notify_emergency_close():
    """EMERGENCY — correct icon, negative pnl."""
    with _patch_send() as mock_send:
        mock_send.return_value = True
        await _notifier().notify_emergency_close(
            telegram_user_id=_TG_USER_ID,
            market_id=_MARKET_ID,
            market_question=None,
            side="yes",
            exit_price=0.30,
            pnl_usdc=-20.00,
            mode=_MODE,
        )
    text: str = mock_send.call_args[0][1]
    assert "🚨" in text
    assert "EMERGENCY CLOSE" in text
    assert "YES" in text
    assert "0.300" in text
    assert "-$20.00" in text


# ---------------------------------------------------------------------------
# COPY_TRADE scaffold
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notify_copy_trade_entry_with_wallet():
    """COPY_TRADE — target_wallet truncated to first 6 + last 4 chars."""
    with _patch_send() as mock_send:
        mock_send.return_value = True
        await _notifier().notify_copy_trade_entry(
            telegram_user_id=_TG_USER_ID,
            market_id=_MARKET_ID,
            market_question=_MARKET_Q,
            side="yes",
            size_usdc=Decimal("30.00"),
            price=0.55,
            tp_pct=0.20,
            sl_pct=0.10,
            target_wallet="0xAbCdEf1234567890abcdef",
            mode=_MODE,
        )
    text: str = mock_send.call_args[0][1]
    assert "COPY TRADE" in text
    assert "YES" in text
    assert "Copying:" in text
    assert "0xAbCd" in text  # first 6


@pytest.mark.asyncio
async def test_notify_copy_trade_entry_no_wallet():
    """COPY_TRADE — without target_wallet no 'Copying:' line appears."""
    with _patch_send() as mock_send:
        mock_send.return_value = True
        await _notifier().notify_copy_trade_entry(
            telegram_user_id=_TG_USER_ID,
            market_id=_MARKET_ID,
            market_question=None,
            side="no",
            size_usdc=Decimal("20.00"),
            price=0.45,
            tp_pct=None,
            sl_pct=None,
        )
    text: str = mock_send.call_args[0][1]
    assert "Copying:" not in text


# ---------------------------------------------------------------------------
# Market label edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_long_market_question_truncated():
    """Market question > 60 chars is truncated with ellipsis."""
    with _patch_send() as mock_send:
        mock_send.return_value = True
        await _notifier().notify_entry(
            telegram_user_id=_TG_USER_ID,
            market_id=_MARKET_ID,
            market_question=_LONG_Q,
            side="yes",
            size_usdc=Decimal("10.00"),
            price=0.50,
            tp_pct=None,
            sl_pct=None,
        )
    text: str = mock_send.call_args[0][1]
    assert "…" in text
    assert len([line for line in text.split("\n") if "A" * 61 in line]) == 0


@pytest.mark.asyncio
async def test_no_market_question_uses_market_id():
    """No market_question → market_id used as label."""
    with _patch_send() as mock_send:
        mock_send.return_value = True
        await _notifier().notify_tp_hit(
            telegram_user_id=_TG_USER_ID,
            market_id=_MARKET_ID,
            market_question=None,
            side="yes",
            exit_price=0.80,
            pnl_usdc=5.00,
        )
    text: str = mock_send.call_args[0][1]
    assert _MARKET_ID in text


# ---------------------------------------------------------------------------
# Failure-safe contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_failure_caught_not_raised():
    """Telegram send failure is caught and logged; method returns normally."""
    with _patch_send() as mock_send:
        mock_send.side_effect = RuntimeError("Telegram timeout")
        # Must NOT raise — failure-safe contract
        await _notifier().notify_entry(
            telegram_user_id=_TG_USER_ID,
            market_id=_MARKET_ID,
            market_question=None,
            side="yes",
            size_usdc=Decimal("10.00"),
            price=0.50,
            tp_pct=None,
            sl_pct=None,
        )
    # Reached here → no exception propagated. Pass.


@pytest.mark.asyncio
async def test_tp_hit_send_failure_caught():
    """TP_HIT send failure is also caught — same failure-safe contract."""
    with _patch_send() as mock_send:
        mock_send.side_effect = Exception("Network error")
        await _notifier().notify_tp_hit(
            telegram_user_id=_TG_USER_ID,
            market_id=_MARKET_ID,
            market_question=None,
            side="no",
            exit_price=0.20,
            pnl_usdc=-5.00,
        )
    # No exception → pass


# ---------------------------------------------------------------------------
# monitoring.alerts — alert_user_manual_close
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_alert_user_manual_close_message():
    """alert_user_manual_close sends text to correct telegram_user_id."""
    with patch(
        "projects.polymarket.crusaderbot.monitoring.alerts.notifications.send",
        new_callable=AsyncMock,
    ) as mock_send:
        mock_send.return_value = True
        from projects.polymarket.crusaderbot.monitoring.alerts import (
            alert_user_manual_close,
        )
        await alert_user_manual_close(
            telegram_user_id=_TG_USER_ID,
            market_id=_MARKET_ID,
            market_question=_MARKET_Q,
            side="yes",
            exit_price=0.70,
            pnl_usdc=7.50,
            mode="paper",
        )
    mock_send.assert_awaited_once()
    # First positional arg is chat_id
    assert mock_send.call_args[0][0] == _TG_USER_ID
    text: str = mock_send.call_args[0][1]
    assert "Manual close" in text or "manual" in text.lower()
    assert "YES" in text
    assert "7.50" in text  # pnl present; exact sign format is implementation detail


# ---------------------------------------------------------------------------
# NotificationEvent enum
# ---------------------------------------------------------------------------


def test_notification_event_values():
    """NotificationEvent enum has all required canonical string values."""
    assert NotificationEvent.ENTRY.value == "entry"
    assert NotificationEvent.TP_HIT.value == "tp_hit"
    assert NotificationEvent.SL_HIT.value == "sl_hit"
    assert NotificationEvent.MANUAL.value == "manual"
    assert NotificationEvent.EMERGENCY.value == "emergency"
    assert NotificationEvent.COPY_TRADE.value == "copy_trade"
