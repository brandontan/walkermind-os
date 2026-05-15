"""Trade notification service — compact Telegram messages for trade lifecycle events.

Supported events (paper mode):
    ENTRY       — position opened (signal → risk gate → paper fill)
    TP_HIT      — take-profit threshold breached, close submitted
    SL_HIT      — stop-loss threshold breached, close submitted
    MANUAL      — user-initiated close via Telegram My Trades flow
    EMERGENCY   — force-close marker consumed by exit watcher
    COPY_TRADE  — scaffold; emitted when strategy_type == "copy_trade"

Failure-safe contract:
    All ``notify_*`` methods catch every exception from the underlying
    ``notifications.send`` call, log at ERROR, and return without re-raising.
    The trading runtime MUST continue even when Telegram is unavailable.

Engineering rules:
    * asyncio only — no threading.
    * structlog for all logging.
    * Full type hints on all public methods.
    * No silent failures — Telegram send failures are caught AND logged.
"""
from __future__ import annotations

import asyncio
import enum
import html
import logging
from decimal import Decimal
from typing import Optional
from uuid import UUID

import structlog
from telegram import InlineKeyboardMarkup
from telegram.constants import ParseMode

from ... import notifications

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_ANIM_DELAY = 1.2  # seconds between animated edits


async def _send_initial_animated(
    chat_id: int,
    text: str,
) -> Optional[tuple[int, int]]:
    """Send first animated message. Returns (message_id, chat_id) or None on failure."""
    try:
        bot = notifications.get_bot()
        msg = await bot.send_message(chat_id=chat_id, text=text)
        return msg.message_id, msg.chat_id
    except Exception as exc:
        logging.getLogger(__name__).error(
            "animated_status.send_initial_failed chat=%s error=%s", chat_id, exc
        )
        return None


async def _edit_or_resend(chat_id: int, message_id: int, text: str) -> None:
    """Edit message in place; send fresh if edit fails (message too old or deleted)."""
    try:
        bot = notifications.get_bot()
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        await notifications.send(chat_id, text)


class NotificationEvent(str, enum.Enum):
    """Canonical event types emitted by ``TradeNotifier``."""

    ENTRY = "entry"
    TP_HIT = "tp_hit"
    SL_HIT = "sl_hit"
    MANUAL = "manual"
    EMERGENCY = "emergency"
    COPY_TRADE = "copy_trade"


def _market_label(market_question: Optional[str], market_id: str) -> str:
    """Short label: prefer human-readable question, fall back to raw market ID."""
    if market_question:
        # Truncate to 60 chars to keep messages compact.
        return market_question[:60] + ("…" if len(market_question) > 60 else "")
    return market_id


def _mode_tag(mode: str) -> str:
    return f"[{mode.upper()}]"


def _fmt_tp(tp_pct: Optional[float]) -> str:
    if tp_pct is None:
        return "—"
    return f"{tp_pct * 100:.1f}%"


def _fmt_sl(sl_pct: Optional[float]) -> str:
    if sl_pct is None:
        return "—"
    return f"{sl_pct * 100:.1f}%"


def _fmt_pnl(pnl_usdc: float) -> str:
    sign = "+" if pnl_usdc >= 0 else "-"
    return f"{sign}${abs(pnl_usdc):.2f}"


_SEP = "━━━━━━━━━━━━━━━━━━━━"

_STRAT_LABELS = {
    "whale_mirror":  "🐋 Whale Mirror",
    "signal_sniper": "📡 Signal Sniper",
    "hybrid":        "🐋📡 Hybrid",
    "value_hunter":  "🎯 Value Hunter",
    "full_auto":     "🚀 Full Auto",
    "copy_trade":    "🐋 Copy Trade",
    "signal":        "📡 Signal",
    "value":         "🎯 Value",
    "manual":        "Manual",
}

# Human-readable reasoning labels for signal_reason values
_SIGNAL_REASON_LABELS: dict[str, str] = {
    "yes_edge":        "Strong YES momentum signal",
    "no_edge":         "Strong NO momentum signal",
    "value_misprice":  "Mispriced market detected",
    "whale_entry":     "Whale wallet entry observed",
    "momentum":        "Momentum breakout",
}


def _build_reasoning(
    signal_reason: Optional[str],
    copy_wallet: Optional[str],
    copy_win_rate: Optional[float],
) -> str:
    """Build reasoning block string (with trailing newline) or empty string."""
    if copy_wallet:
        short = f"{copy_wallet[:6]}…{copy_wallet[-4:]}" if len(copy_wallet) > 10 else copy_wallet
        wr = f" · Win rate {copy_win_rate:.0f}%" if copy_win_rate is not None else ""
        return f"💡 Copying {html.escape(short)}{html.escape(wr)}\n"
    if signal_reason:
        label = _SIGNAL_REASON_LABELS.get(signal_reason, signal_reason)
        return f"💡 Reasoning: {html.escape(label)}\n"
    return ""


class TradeNotifier:
    """Stateless notification dispatcher for paper-mode trade lifecycle events.

    One instance is safe to share across the full process lifetime.
    """

    async def notify_entry(
        self,
        *,
        telegram_user_id: int,
        market_id: str,
        market_question: Optional[str],
        side: str,
        size_usdc: Decimal,
        price: float,
        tp_pct: Optional[float],
        sl_pct: Optional[float],
        mode: str = "paper",
        strategy_type: Optional[str] = None,
        signal_reason: Optional[str] = None,
        copy_wallet: Optional[str] = None,
        copy_win_rate: Optional[float] = None,
    ) -> None:
        """Send trade OPEN receipt card with optional reasoning block."""
        label = _market_label(market_question, market_id)
        strat = _STRAT_LABELS.get(strategy_type or "", strategy_type or "Auto")
        side_upper = side.upper()

        reasoning = _build_reasoning(signal_reason, copy_wallet, copy_win_rate)

        text = (
            f"{_SEP}\n"
            "📋  TRADE OPENED\n"
            f"{_SEP}\n"
            f"<pre>Market  │ {html.escape(label[:28])}\n"
            f"Side    │ {html.escape(side_upper)}\n"
            f"Size    │ ${size_usdc:.2f}\n"
            f"Entry   │ ${price:.4f}\n"
            f"TP      │ {_fmt_tp(tp_pct)}\n"
            f"SL      │ {_fmt_sl(sl_pct)}</pre>\n"
            f"{_SEP}\n"
            f"Strategy: {html.escape(strat)}\n"
            f"{reasoning}"
            f"{_SEP}"
        )
        await self._send(
            telegram_user_id, text,
            event=NotificationEvent.ENTRY,
            market_id=market_id,
        )

    async def animated_entry_sequence(
        self,
        *,
        telegram_user_id: int,
        market_id: str,
        market_question: Optional[str],
        side: str,
        size_usdc: Decimal,
        price: float,
        tp_pct: Optional[float],
        sl_pct: Optional[float],
        mode: str = "paper",
        strategy_type: Optional[str] = None,
        signal_reason: Optional[str] = None,
        copy_wallet: Optional[str] = None,
        copy_win_rate: Optional[float] = None,
    ) -> None:
        """4-step animated trade execution sequence via in-place message edits.

        Falls back to static notify_entry() if initial send fails.
        Falls back to send_message() if any edit fails (message too old).
        Uses asyncio.sleep — never blocks the event loop.
        """
        label = _market_label(market_question, market_id)

        result = await _send_initial_animated(telegram_user_id, "🔍 Scanning markets...")
        if result is None:
            await self.notify_entry(
                telegram_user_id=telegram_user_id,
                market_id=market_id,
                market_question=market_question,
                side=side,
                size_usdc=size_usdc,
                price=price,
                tp_pct=tp_pct,
                sl_pct=sl_pct,
                mode=mode,
                strategy_type=strategy_type,
                signal_reason=signal_reason,
                copy_wallet=copy_wallet,
                copy_win_rate=copy_win_rate,
            )
            return

        msg_id, chat_id = result

        await asyncio.sleep(_ANIM_DELAY)
        await _edit_or_resend(
            chat_id, msg_id,
            f"📡 Signal found: {html.escape(label)} — {html.escape(side.upper())} @ {price:.3f}",
        )

        await asyncio.sleep(_ANIM_DELAY)
        await _edit_or_resend(chat_id, msg_id, "⚡ Executing trade...")

        await asyncio.sleep(_ANIM_DELAY)
        tag = _mode_tag(mode)
        icon = "\U0001f4c8" if side.lower() == "yes" else "\U0001f4c9"
        side_upper = side.upper()
        lines = [
            f"{icon} <b>{html.escape(tag)} ENTRY — {html.escape(side_upper)}</b>",
            html.escape(label),
            f"Size: ${size_usdc:.2f} | Price: {price:.3f}",
            f"TP: {_fmt_tp(tp_pct)} | SL: {_fmt_sl(sl_pct)}",
            "Paper mode",
        ]
        if strategy_type and strategy_type != "manual":
            lines.append(f"Strategy: {html.escape(strategy_type)}")
        await _edit_or_resend(chat_id, msg_id, "\n".join(lines))

    async def notify_tp_hit(
        self,
        *,
        telegram_user_id: int,
        market_id: str,
        market_question: Optional[str],
        side: str,
        exit_price: float,
        pnl_usdc: float,
        mode: str = "paper",
        trade_id: Optional[str] = None,
        reply_markup: Optional[InlineKeyboardMarkup] = None,
    ) -> None:
        label = _market_label(market_question, market_id)
        pnl_sign = "+" if pnl_usdc >= 0 else ""
        text = (
            f"{_SEP}\n"
            "🎯  TAKE-PROFIT HIT\n"
            f"{_SEP}\n"
            f"<pre>Market  │ {html.escape(label[:28])}\n"
            f"Side    │ {html.escape(side.upper())}\n"
            f"Exit    │ ${exit_price:.4f}\n"
            f"P&amp;L     │ {pnl_sign}${abs(pnl_usdc):.2f}</pre>\n"
            f"{_SEP}"
        )
        await self._send(
            telegram_user_id, text,
            event=NotificationEvent.TP_HIT, market_id=market_id,
            reply_markup=reply_markup,
        )

    async def notify_sl_hit(
        self,
        *,
        telegram_user_id: int,
        market_id: str,
        market_question: Optional[str],
        side: str,
        exit_price: float,
        pnl_usdc: float,
        mode: str = "paper",
        reply_markup: Optional[InlineKeyboardMarkup] = None,
    ) -> None:
        label = _market_label(market_question, market_id)
        pnl_sign = "+" if pnl_usdc >= 0 else ""
        text = (
            f"{_SEP}\n"
            "🛑  STOP-LOSS HIT\n"
            f"{_SEP}\n"
            f"<pre>Market  │ {html.escape(label[:28])}\n"
            f"Side    │ {html.escape(side.upper())}\n"
            f"Exit    │ ${exit_price:.4f}\n"
            f"P&amp;L     │ {pnl_sign}${abs(pnl_usdc):.2f}</pre>\n"
            f"{_SEP}"
        )
        await self._send(
            telegram_user_id, text,
            event=NotificationEvent.SL_HIT, market_id=market_id,
            reply_markup=reply_markup,
        )

    async def notify_manual_close(
        self,
        *,
        telegram_user_id: int,
        market_id: str,
        market_question: Optional[str],
        side: str,
        exit_price: float,
        pnl_usdc: float,
        mode: str = "paper",
        reply_markup: Optional[InlineKeyboardMarkup] = None,
    ) -> None:
        """Send MANUAL notification when user closes a position via My Trades."""
        label = _market_label(market_question, market_id)
        tag = _mode_tag(mode)
        text = (
            f"✅ <b>{html.escape(tag)} MANUAL CLOSE — {html.escape(side.upper())}</b>\n"
            f"{html.escape(label)}\n"
            f"Exit: {exit_price:.3f} | P&amp;L: <b>{html.escape(_fmt_pnl(pnl_usdc))}</b>"
        )
        await self._send(
            telegram_user_id, text,
            event=NotificationEvent.MANUAL, market_id=market_id,
            reply_markup=reply_markup,
        )

    async def notify_emergency_close(
        self,
        *,
        telegram_user_id: int,
        market_id: str,
        market_question: Optional[str],
        side: str,
        exit_price: float,
        pnl_usdc: float,
        mode: str = "paper",
    ) -> None:
        """Send EMERGENCY notification when force-close marker is consumed."""
        label = _market_label(market_question, market_id)
        tag = _mode_tag(mode)
        text = (
            f"\U0001f6a8 <b>{html.escape(tag)} EMERGENCY CLOSE — {html.escape(side.upper())}</b>\n"
            f"{html.escape(label)}\n"
            f"Exit: {exit_price:.3f} | P&amp;L: <b>{html.escape(_fmt_pnl(pnl_usdc))}</b>"
        )
        await self._send(
            telegram_user_id, text,
            event=NotificationEvent.EMERGENCY, market_id=market_id,
        )

    async def notify_copy_trade_entry(
        self,
        *,
        telegram_user_id: int,
        market_id: str,
        market_question: Optional[str],
        side: str,
        size_usdc: Decimal,
        price: float,
        tp_pct: Optional[float],
        sl_pct: Optional[float],
        target_wallet: Optional[str] = None,
        mode: str = "paper",
    ) -> None:
        """Scaffold: COPY_TRADE entry notification.

        Emitted when strategy_type == "copy_trade" and the position carries
        copy-trade metadata. Target wallet is truncated for readability.
        Track B (Copy Trade execution) will populate target_wallet.
        """
        label = _market_label(market_question, market_id)
        tag = _mode_tag(mode)
        icon = "\U0001f4c8" if side.lower() == "yes" else "\U0001f4c9"
        wallet_str = ""
        if target_wallet:
            wallet_str = (
                f"\nCopying: <code>{html.escape(target_wallet[:6])}…{html.escape(target_wallet[-4:])}</code>"
            )

        text = (
            f"{icon} <b>{html.escape(tag)} COPY TRADE — {html.escape(side.upper())}</b>\n"
            f"{html.escape(label)}\n"
            f"Size: ${size_usdc:.2f} | Price: {price:.3f}\n"
            f"TP: {_fmt_tp(tp_pct)} | SL: {_fmt_sl(sl_pct)}"
            f"{wallet_str}\n"
            "Paper mode"
        )
        await self._send(
            telegram_user_id, text,
            event=NotificationEvent.COPY_TRADE, market_id=market_id,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _send(
        self,
        telegram_user_id: int,
        text: str,
        *,
        event: NotificationEvent,
        market_id: str,
        reply_markup: Optional[InlineKeyboardMarkup] = None,
    ) -> None:
        """Send text to user. Catches all failures — runtime must not be interrupted."""
        try:
            await notifications.send(telegram_user_id, text, reply_markup=reply_markup)
        except Exception as exc:  # noqa: BLE001 — must not propagate
            # structlog's `event` positional arg conflicts with the local
            # ``event`` param name — use the stdlib logger to avoid the clash.
            _stdlib_logger = logging.getLogger(__name__)
            _stdlib_logger.error(
                "trade_notification.send_failed notification_event=%s market_id=%s "
                "telegram_user_id=%s error=%s",
                event.value, market_id, telegram_user_id, exc,
            )
