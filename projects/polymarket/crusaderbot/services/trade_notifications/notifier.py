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

import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from ... import notifications
from ...webtrader.backend import notification_prefs as _notif_prefs

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
        delivered = await notifications.send(chat_id, text)
        if not delivered:
            logging.getLogger(__name__).warning(
                "animated_status.fallback_send_dropped chat=%s message_id=%s",
                chat_id, message_id,
            )


class NotificationEvent(str, enum.Enum):
    """Canonical event types emitted by ``TradeNotifier``."""

    ENTRY = "entry"
    TP_HIT = "tp_hit"
    SL_HIT = "sl_hit"
    MANUAL = "manual"
    EMERGENCY = "emergency"
    COPY_TRADE = "copy_trade"


# Map each canonical NotificationEvent → the user-pref alert_key surfaced in
# the WebTrader Notification Preferences card. Keep ENTRY + COPY_TRADE under
# ``trade_opened`` (single TRADING toggle in the UI) and all close variants
# under ``trade_closed``.
_EVENT_PREF_KEY: dict[NotificationEvent, str] = {
    NotificationEvent.ENTRY:      "trade_opened",
    NotificationEvent.COPY_TRADE: "trade_opened",
    NotificationEvent.TP_HIT:     "trade_closed",
    NotificationEvent.SL_HIT:     "trade_closed",
    NotificationEvent.MANUAL:     "trade_closed",
    NotificationEvent.EMERGENCY:  "trade_closed",
}

# Short titles shown in the WebTrader AlertCenter card header. The full
# message body (already-rendered Telegram text) goes into the body field.
_EVENT_WEB_TITLE: dict[NotificationEvent, str] = {
    NotificationEvent.ENTRY:      "Trade opened",
    NotificationEvent.COPY_TRADE: "Copy trade opened",
    NotificationEvent.TP_HIT:     "Take-profit hit",
    NotificationEvent.SL_HIT:     "Stop-loss hit",
    NotificationEvent.MANUAL:     "Manual close",
    NotificationEvent.EMERGENCY:  "Emergency close",
}


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

_STRAT_LABELS: dict[str, str] = {
    "copy_trade":       "🐋 Copy Trade",
    "signal":           "📡 Signal",
    "manual":           "Manual",
    # Strategy class names (stored as strategy_type on positions)
    "late_entry_v3":    "Late Entry",
    "signal_following": "Signal Following",
    # Preset keys (fallback if preset key stored directly)
    "close_sweep":      "Close Sweep",
    "flip_hunter":      "Flip Hunter",
    "safe_close":       "Safe Close",
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
        position_id: Optional[str] = None,
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
        if position_id:
            kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("📈 View Position",  callback_data=f"mytrades:open:{position_id}"),
                    InlineKeyboardButton("🛑 Close Position", callback_data=f"close_position:{position_id}"),
                ],
                [
                    InlineKeyboardButton("📊 Dashboard", callback_data="menu:dashboard"),
                ],
            ])
        else:
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("📊 Dashboard", callback_data="menu:dashboard"),
            ]])
        await self._send(
            telegram_user_id, text,
            event=NotificationEvent.ENTRY,
            market_id=market_id,
            reply_markup=kb,
            alert_kind="trade_opened",
            metadata={
                "market_id": market_id,
                "market_label": label,
                "side": side_upper,
                "size_usdc": float(size_usdc),
                "entry_price": float(price),
                "tp_pct": float(tp_pct) if tp_pct is not None else None,
                "sl_pct": float(sl_pct) if sl_pct is not None else None,
                "strategy": strat,
                "strategy_type": strategy_type,
                "mode": mode,
                "position_id": position_id,
                "signal_reason": signal_reason,
                "copy_wallet": copy_wallet,
                "copy_win_rate": copy_win_rate,
            },
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
        if reply_markup is None:
            reply_markup = InlineKeyboardMarkup([[
                InlineKeyboardButton("📈 My Trades", callback_data="menu:trades"),
                InlineKeyboardButton("📊 Dashboard", callback_data="menu:dashboard"),
            ]])
        await self._send(
            telegram_user_id, text,
            event=NotificationEvent.TP_HIT, market_id=market_id,
            reply_markup=reply_markup,
            alert_kind="tp_hit",
            metadata={
                "market_id": market_id,
                "market_label": label,
                "side": side.upper(),
                "exit_price": float(exit_price),
                "pnl_usdc": float(pnl_usdc),
                "mode": mode,
                "trade_id": trade_id,
            },
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
        if reply_markup is None:
            reply_markup = InlineKeyboardMarkup([[
                InlineKeyboardButton("📈 My Trades", callback_data="menu:trades"),
                InlineKeyboardButton("📊 Dashboard", callback_data="menu:dashboard"),
            ]])
        await self._send(
            telegram_user_id, text,
            event=NotificationEvent.SL_HIT, market_id=market_id,
            reply_markup=reply_markup,
            alert_kind="sl_hit",
            metadata={
                "market_id": market_id,
                "market_label": label,
                "side": side.upper(),
                "exit_price": float(exit_price),
                "pnl_usdc": float(pnl_usdc),
                "mode": mode,
            },
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
        if reply_markup is None:
            reply_markup = InlineKeyboardMarkup([[
                InlineKeyboardButton("📈 My Trades", callback_data="menu:trades"),
                InlineKeyboardButton("📊 Dashboard", callback_data="menu:dashboard"),
            ]])
        await self._send(
            telegram_user_id, text,
            event=NotificationEvent.MANUAL, market_id=market_id,
            reply_markup=reply_markup,
            alert_kind="manual_close",
            metadata={
                "market_id": market_id,
                "market_label": label,
                "side": side.upper(),
                "exit_price": float(exit_price),
                "pnl_usdc": float(pnl_usdc),
                "mode": mode,
            },
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
        emergency_kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("📈 My Trades", callback_data="menu:trades"),
            InlineKeyboardButton("📊 Dashboard", callback_data="menu:dashboard"),
        ]])
        await self._send(
            telegram_user_id, text,
            event=NotificationEvent.EMERGENCY, market_id=market_id,
            reply_markup=emergency_kb,
            alert_kind="emergency_close",
            metadata={
                "market_id": market_id,
                "market_label": label,
                "side": side.upper(),
                "exit_price": float(exit_price),
                "pnl_usdc": float(pnl_usdc),
                "mode": mode,
            },
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
        position_id: Optional[str] = None,
        copy_task_id: Optional[str] = None,
    ) -> None:
        """COPY_TRADE entry notification with inline action keyboards.

        Emitted when strategy_type == "copy_trade". Buttons:
          [ 📈 View Position ]  [ 🛑 Close Position ]   (when position_id set)
          [ ⏸️ Pause Copy ]                              (when copy_task_id set)
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
        kb_rows: list[list[InlineKeyboardButton]] = []
        if position_id:
            kb_rows.append([
                InlineKeyboardButton("📈 View Position",  callback_data=f"mytrades:open:{position_id}"),
                InlineKeyboardButton("🛑 Close Position", callback_data=f"close_position:{position_id}"),
            ])
        if copy_task_id:
            kb_rows.append([
                InlineKeyboardButton("⏸️ Pause Copy", callback_data=f"tgnotif:pause_copy:{copy_task_id}"),
            ])
        if not kb_rows:
            kb_rows = [[InlineKeyboardButton("📊 Dashboard", callback_data="menu:dashboard")]]
        await self._send(
            telegram_user_id, text,
            event=NotificationEvent.COPY_TRADE, market_id=market_id,
            reply_markup=InlineKeyboardMarkup(kb_rows),
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
        alert_kind: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        """Send text to user. Catches all failures — runtime must not be interrupted.

        Honors notification_prefs (web/tg channels): mirrors to the user's
        WebTrader AlertCenter when web is enabled, only fires TG send when tg
        is enabled. The legacy ``notifications_enabled_by_telegram_id`` flag
        still gates the TG channel as a global kill switch.

        ``alert_kind`` and ``metadata`` are forwarded to the web mirror so the
        AlertCenter can render typed cards (entry / closed / TP / SL) instead
        of dumping the Telegram ASCII text body. Telegram delivery is unchanged.
        """
        from ...users import notifications_enabled_by_telegram_id

        alert_key = _EVENT_PREF_KEY.get(event, "trade_opened")
        web_title = _EVENT_WEB_TITLE.get(event, "Trade update")
        try:
            send_tg = await _notif_prefs.route_outgoing_alert(
                telegram_user_id=telegram_user_id,
                alert_key=alert_key,
                web_title=web_title,
                web_body=text,
                severity="info",
                dedup_key=market_id,
                alert_kind=alert_kind,
                metadata=metadata,
            )
        except Exception:
            send_tg = True
        if not send_tg:
            return

        if not await notifications_enabled_by_telegram_id(telegram_user_id):
            logging.getLogger(__name__).info(
                "trade_notification.suppressed notification_event=%s "
                "telegram_user_id=%s reason=user_opted_out",
                event.value, telegram_user_id,
            )
            return
        # structlog's `event` positional arg conflicts with the local
        # ``event`` param name — use the stdlib logger to avoid the clash.
        _stdlib_logger = logging.getLogger(__name__)
        try:
            delivered = await notifications.send(
                telegram_user_id, text, reply_markup=reply_markup,
            )
        except Exception as exc:  # noqa: BLE001 — must not propagate
            _stdlib_logger.error(
                "trade_notification.send_failed notification_event=%s market_id=%s "
                "telegram_user_id=%s error=%s",
                event.value, market_id, telegram_user_id, exc,
            )
            return
        if not delivered:
            # notifications.send already logged the underlying error at ERROR.
            # Surface a notifier-level WARNING so the dropped trade-lifecycle
            # event is auditable per-event (not just as a generic delivery
            # failure) — required by WARP-53 "no silent swallow" gate.
            _stdlib_logger.warning(
                "trade_notification.delivery_dropped notification_event=%s "
                "market_id=%s telegram_user_id=%s",
                event.value, market_id, telegram_user_id,
            )
