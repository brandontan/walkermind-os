"""Portfolio chart handler — /chart command + chart:N callback.

/chart          → 7-day chart (default)
chart:7         → 7-day chart
chart:30        → 30-day chart
chart:all       → all-time chart

Empty data (no ledger entries) → text fallback, no error raised.
Tier: ALLOWLISTED (Tier 2+)
"""
from __future__ import annotations

import io
import logging

from telegram import InputFile, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ...services.portfolio_chart import generate_portfolio_chart
from ...users import upsert_user
from ..keyboards import chart_kb

logger = logging.getLogger(__name__)

_FALLBACK_MSG = (
    "\U0001f4ca <b>PORTFOLIO CHART</b>\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "No balance history yet. Make a deposit or complete a paper trade to see your chart."
)


def _parse_days(key: str) -> int | None:
    """Convert callback key to days int or None for all-time."""
    if key == "all":
        return None
    try:
        return int(key)
    except ValueError:
        return 7


def _caption(days_key: str | int, peak: float, low: float, now: float) -> str:
    if days_key == "all" or days_key is None:
        label = "ALL TIME"
    else:
        label = f"{days_key} DAYS"
    return (
        f"PORTFOLIO — {label}\n"
        f"Peak: ${peak:,.2f} | Low: ${low:,.2f} | Now: ${now:,.2f}"
    )


async def chart_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None:
        return
    user = await upsert_user(
        update.effective_user.id, update.effective_user.username
    )
    await _send_chart(
        chat_id=update.message.chat_id,
        user_id=user["id"],
        days_key="7",
        ctx=ctx,
        reply_to=update.message,
    )


async def chart_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if q is None or update.effective_user is None:
        return
    await q.answer()

    user = await upsert_user(
        update.effective_user.id, update.effective_user.username
    )
    # callback_data format: chart:7 / chart:30 / chart:all
    raw_key = (q.data or "chart:7").split(":", 1)[-1]
    days_key = raw_key if raw_key in {"7", "30", "all"} else "7"

    await _send_chart(
        chat_id=q.message.chat_id,
        user_id=user["id"],
        days_key=days_key,
        ctx=ctx,
        reply_to=None,
    )


async def _send_chart(
    *,
    chat_id: int,
    user_id,
    days_key: str,
    ctx: ContextTypes.DEFAULT_TYPE,
    reply_to,
) -> None:
    days = _parse_days(days_key)
    result = await generate_portfolio_chart(user_id, days)

    if result is None:
        # No data — graceful fallback
        if reply_to is not None:
            await reply_to.reply_text(
                _FALLBACK_MSG,
                parse_mode=ParseMode.HTML,
                reply_markup=chart_kb(days_key),
            )
        else:
            await ctx.bot.send_message(
                chat_id,
                _FALLBACK_MSG,
                parse_mode=ParseMode.HTML,
                reply_markup=chart_kb(days_key),
            )
        return

    png_bytes, peak, low, now = result
    caption = _caption(days_key, float(peak), float(low), float(now))
    photo = InputFile(io.BytesIO(png_bytes), filename="portfolio.png")

    await ctx.bot.send_photo(
        chat_id,
        photo=photo,
        caption=caption,
        reply_markup=chart_kb(days_key),
    )
