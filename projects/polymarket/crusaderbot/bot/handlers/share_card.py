"""Share card handler — sends a formatted trade share card on [Share] button press."""
from __future__ import annotations

import html
import logging
from uuid import UUID

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ...database import get_pool
from ...services.referral.referral_service import get_or_create_referral_code, build_deep_link
from ...users import get_user_by_telegram_id

logger = logging.getLogger(__name__)

_BOT_USERNAME = "CrusaderBot"


async def _fetch_trade(trade_id: str) -> dict | None:
    """Fetch closed position row by id. Returns None if not found."""
    try:
        uid = UUID(trade_id)
    except ValueError:
        return None
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT market_question, market_id, pnl_usdc, size_usdc, exit_price
            FROM positions
            WHERE id=$1 AND status='closed'
            """,
            uid,
        )
        return dict(row) if row else None


def _pnl_pct(pnl_usdc: float, size_usdc: float) -> float:
    if size_usdc == 0:
        return 0.0
    return (pnl_usdc / size_usdc) * 100.0


async def referral_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle referral:share:{trade_id} callback query."""
    q = update.callback_query
    if q is None or update.effective_user is None:
        return
    await q.answer()

    data = (q.data or "").split(":")
    if len(data) < 3 or data[1] != "share":
        return

    trade_id = data[2]
    tg_user = update.effective_user

    user = await get_user_by_telegram_id(tg_user.id)
    if user is None:
        await q.message.reply_text("Could not load your account. Please use /start.")
        return

    user_id: UUID = user["id"]

    trade = await _fetch_trade(trade_id)
    if trade is None:
        await q.message.reply_text("Trade not found or still open.")
        return

    pnl = float(trade["pnl_usdc"] or 0.0)
    if pnl <= 0:
        await q.answer("Only winning trades can be shared.", show_alert=True)
        return

    size = float(trade["size_usdc"] or 0.0)
    pct = _pnl_pct(pnl, size)
    market_title = trade.get("market_question") or trade.get("market_id") or "a market"
    if len(market_title) > 60:
        market_title = market_title[:57] + "..."

    try:
        code = await get_or_create_referral_code(user_id)
    except Exception as exc:
        logger.error("share_card.get_code_failed user_id=%s error=%s", user_id, exc)
        await q.message.reply_text("Could not generate share link. Try again later.")
        return

    deep_link = build_deep_link(code)

    card = (
        f"\U0001f3c6 Just made <b>+{pct:.1f}%</b> on <i>{html.escape(market_title)}</i>\n"
        f"using CrusaderBot!\n\n"
        f"Join me: <code>{html.escape(deep_link)}</code>"
    )

    await q.message.reply_text(
        card,
        parse_mode=ParseMode.HTML,
    )
