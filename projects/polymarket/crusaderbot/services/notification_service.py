"""Notification service — subscribes to event_bus and dispatches Telegram receipts.

Subscriptions:
    position.opened     -> entry receipt   (📋 TRADE OPENED)
    position.closed     -> exit receipt    (✅/❌/➖ TRADE CLOSED)
    copy_trade.executed -> copy receipt    (🐋 COPY TRADE)

Failure contract:
    All handlers catch every exception from Telegram delivery.
    Notification failure MUST NOT crash or block trade execution.

Wire up once at startup:
    from projects.polymarket.crusaderbot.services.notification_service import register_handlers
    register_handlers()
"""
from __future__ import annotations

import html
import logging
from decimal import Decimal
from typing import Any, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .. import notifications
from ..core.event_bus import subscribe
from ..users import notifications_enabled_by_telegram_id

logger = logging.getLogger(__name__)

_SEP = "━━━━━━━━━━━━━━━━━━━━"

_CLOSE_REASON_LABELS: dict[str, str] = {
    "TP_HIT":    "Take Profit Hit",
    "SL_HIT":    "Stop Loss Hit",
    "MANUAL":    "Manually Closed",
    "EXPIRED":   "Market Expired",
    "EMERGENCY": "Emergency Stop",
}

_STRAT_LABELS: dict[str, str] = {
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


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _market_label(market_question: Optional[str], market_id: str) -> str:
    if market_question:
        return market_question[:60] + ("…" if len(market_question) > 60 else "")
    return market_id


def _fmt_tp(tp_pct: Optional[float]) -> str:
    return f"{tp_pct * 100:.1f}%" if tp_pct is not None else "—"


def _fmt_sl(sl_pct: Optional[float]) -> str:
    return f"{sl_pct * 100:.1f}%" if sl_pct is not None else "—"


def _fmt_pnl(pnl_usdc: float) -> str:
    if pnl_usdc > 0:
        return f"+${pnl_usdc:.2f}"
    if pnl_usdc < 0:
        return f"-${abs(pnl_usdc):.2f}"
    return "$0.00"


def _fmt_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "—"
    total_minutes = int(seconds) // 60
    hours = total_minutes // 60
    minutes = total_minutes % 60
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _result_icon(pnl_usdc: float) -> str:
    if pnl_usdc > 0:
        return "✅"
    if pnl_usdc < 0:
        return "❌"
    return "➖"


def _result_label(pnl_usdc: float) -> str:
    if pnl_usdc > 0:
        return "WIN"
    if pnl_usdc < 0:
        return "LOSS"
    return "BREAKEVEN"


def _portfolio_trades_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("📊 Portfolio", callback_data="menu:portfolio"),
        InlineKeyboardButton("📈 My Trades", callback_data="menu:trades"),
    ]])


# ---------------------------------------------------------------------------
# Delivery helper
# ---------------------------------------------------------------------------

async def _send_safe(
    telegram_user_id: int,
    text: str,
    event_name: str,
    kb: Optional[InlineKeyboardMarkup] = None,
) -> None:
    """Send Telegram message; catch all failures — MUST NOT propagate."""
    try:
        if not await notifications_enabled_by_telegram_id(telegram_user_id):
            return
        await notifications.send(telegram_user_id, text, reply_markup=kb)
    except Exception as exc:
        logger.error(
            "notification_service: send_failed event=%s telegram_user_id=%s error=%s",
            event_name,
            telegram_user_id,
            exc,
        )


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------

async def _on_position_opened(
    *,
    telegram_user_id: int,
    market_id: str,
    market_question: Optional[str] = None,
    side: str,
    size_usdc: Decimal,
    price: float,
    tp_pct: Optional[float] = None,
    sl_pct: Optional[float] = None,
    strategy_type: Optional[str] = None,
    position_id: Optional[str] = None,
    mode: str = "paper",
    **_: Any,
) -> None:
    label = _market_label(market_question, market_id)
    strat = _STRAT_LABELS.get(strategy_type or "", strategy_type or "Auto")
    text = (
        f"{_SEP}\n"
        "📋  TRADE OPENED\n"
        f"{_SEP}\n"
        f"<pre>Market  │ {html.escape(label[:28])}\n"
        f"Side    │ {html.escape(side.upper())}\n"
        f"Size    │ ${size_usdc:.2f}\n"
        f"Entry   │ ${price:.4f}\n"
        f"TP      │ {_fmt_tp(tp_pct)}\n"
        f"SL      │ {_fmt_sl(sl_pct)}</pre>\n"
        f"{_SEP}\n"
        f"Strategy: {html.escape(strat)}\n"
        f"{_SEP}"
    )
    await _send_safe(telegram_user_id, text, "position.opened", _portfolio_trades_kb())


async def _on_position_closed(
    *,
    telegram_user_id: int,
    market_id: str,
    market_question: Optional[str] = None,
    side: str,
    entry_price: float,
    exit_price: float,
    pnl_usdc: float,
    duration_seconds: Optional[float] = None,
    close_reason: str = "MANUAL",
    mode: str = "paper",
    **_: Any,
) -> None:
    label = _market_label(market_question, market_id)
    icon = _result_icon(pnl_usdc)
    result = _result_label(pnl_usdc)
    reason_display = _CLOSE_REASON_LABELS.get(close_reason.upper(), close_reason)
    text = (
        f"{_SEP}\n"
        f"{icon}  TRADE CLOSED — {result}\n"
        f"{_SEP}\n"
        f"<pre>Market  │ {html.escape(label[:28])}\n"
        f"Side    │ {html.escape(side.upper())}\n"
        f"Entry   │ ${entry_price:.4f}\n"
        f"Exit    │ ${exit_price:.4f}\n"
        f"P&amp;L     │ {html.escape(_fmt_pnl(pnl_usdc))}\n"
        f"Hold    │ {_fmt_duration(duration_seconds)}\n"
        f"Reason  │ {html.escape(reason_display)}</pre>\n"
        f"{_SEP}"
    )
    await _send_safe(telegram_user_id, text, "position.closed", _portfolio_trades_kb())


async def _on_copy_trade_executed(
    *,
    telegram_user_id: int,
    market_id: str,
    market_question: Optional[str] = None,
    side: str,
    size_usdc: Decimal,
    price: float,
    tp_pct: Optional[float] = None,
    sl_pct: Optional[float] = None,
    target_wallet: Optional[str] = None,
    mode: str = "paper",
    **_: Any,
) -> None:
    label = _market_label(market_question, market_id)
    wallet_display = (
        f"{target_wallet[:6]}…{target_wallet[-4:]}"
        if target_wallet and len(target_wallet) > 10
        else (target_wallet or "—")
    )
    text = (
        f"{_SEP}\n"
        "🐋  COPY TRADE\n"
        f"{_SEP}\n"
        f"<pre>Market  │ {html.escape(label[:28])}\n"
        f"Side    │ {html.escape(side.upper())}\n"
        f"Size    │ ${size_usdc:.2f}\n"
        f"Entry   │ ${price:.4f}\n"
        f"Wallet  │ {html.escape(wallet_display)}\n"
        f"TP      │ {_fmt_tp(tp_pct)}\n"
        f"SL      │ {_fmt_sl(sl_pct)}</pre>\n"
        f"{_SEP}"
    )
    await _send_safe(telegram_user_id, text, "copy_trade.executed", _portfolio_trades_kb())


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register_handlers() -> None:
    """Wire all notification handlers into the event bus. Call once at startup."""
    subscribe("position.opened",     _on_position_opened)
    subscribe("position.closed",     _on_position_closed)
    subscribe("copy_trade.executed", _on_copy_trade_executed)
