"""/referral command handler — show user's referral code, link, and stats."""
from __future__ import annotations

import logging
from uuid import UUID

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ...services.referral.referral_service import (
    build_deep_link,
    get_or_create_referral_code,
    get_referral_stats,
)
from ...users import get_user_by_telegram_id

logger = logging.getLogger(__name__)


async def referral_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /referral — show code, deep link, and stats."""
    if update.effective_user is None or update.message is None:
        return

    tg_user = update.effective_user
    user = await get_user_by_telegram_id(tg_user.id)
    if user is None:
        await update.message.reply_text(
            "Please use /start first to set up your account.",
        )
        return

    user_id: UUID = user["id"]

    try:
        code = await get_or_create_referral_code(user_id)
        stats = await get_referral_stats(user_id)
    except Exception as exc:
        logger.error("referral_command.failed user_id=%s error=%s", user_id, exc)
        await update.message.reply_text(
            "Could not load your referral info. Please try again later.",
        )
        return

    deep_link = build_deep_link(code)
    total_referrals = stats["total_referrals"]
    total_earnings = stats["total_earnings"]

    earnings_line = (
        f"💰 Total earnings: ${total_earnings:.2f} \\(payouts coming soon\\)"
        if total_earnings == 0.0
        else f"💰 Total earnings: *${total_earnings:.2f}*"
    )

    text = (
        "🔗 *Your Referral Code*\n\n"
        f"Code: `{code}`\n"
        f"Link: `{deep_link}`\n\n"
        f"👥 Total referrals: *{total_referrals}*\n"
        f"{earnings_line}\n\n"
        "Share your link and earn rewards when friends join CrusaderBot\\!"
    )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN_V2,
    )
