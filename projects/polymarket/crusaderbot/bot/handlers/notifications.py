"""Push notification utilities for user-facing trade events.

Scope: paper mode fill notifications only.
Live mode notifications are gated for a future lane.

Wiring note: notify_order_filled() is declared here for import by the
execution layer. Per task scope, domain/execution/paper.py wiring is
deferred — the DO NOT constraint in issue #1020 prohibits domain/ changes.
The dispatcher registers mytrades:open: → my_trades_h.trade_detail_cb.
"""
from __future__ import annotations

import asyncio
import html
import logging

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

logger = logging.getLogger(__name__)


async def notify_order_filled(
    bot: Bot,
    tg_user_id: int,
    order: dict,
    market: dict,
) -> None:
    """Send a concise fill notification after paper order executes.

    Fire-and-forget — wrap caller in asyncio.create_task(). Never awaited
    on the hot execution path.
    """
    mode_icon = "🔴" if order.get("mode") == "live" else "🟡"
    side = (order.get("side") or "").upper()
    size = float(order.get("size_usdc") or 0)
    price = float(order.get("price") or 0)
    question = (
        (market.get("question") or order.get("market_id") or "")[:45]
    )
    text = (
        f"{mode_icon} <b>Trade filled</b>\n"
        f"{html.escape(side)} ${size:.2f} @ {price:.2f}\n"
        f"<i>{html.escape(question)}</i>"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("📋 View",  callback_data=f"mytrades:open:{order['id']}"),
        InlineKeyboardButton("🏠 Home",  callback_data="dashboard:main"),
    ]])
    try:
        await bot.send_message(
            tg_user_id,
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
        )
    except Exception as exc:
        logger.warning("notify_order_filled failed tg_user_id=%s: %s", tg_user_id, exc)
