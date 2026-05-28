"""`/link <code>` — reverse Telegram-link (account unification).

An email-first WebTrader user mints a one-time code in WebTrader
(Settings → Link Telegram) and redeems it here so both surfaces resolve to ONE
account. Plain-text replies (no MarkdownV2) so the human-readable outcome
messages never trip escaping. See domain/activation/account_link.py.
"""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from ...domain.activation.account_link import LinkOutcome, redeem_link_code

logger = logging.getLogger(__name__)

_USAGE = (
    "🔗 Link your WebTrader account\n\n"
    "1. In WebTrader open Settings → Link Telegram to get a one-time code.\n"
    "2. Send it here as:  /link YOUR-CODE\n\n"
    "This connects both apps to the same account so your LIVE/PAPER mode, "
    "wallet and trades stay in sync."
)


async def link_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None:
        return

    args = ctx.args or []
    if not args:
        await update.message.reply_text(_USAGE)
        return

    code = args[0]
    try:
        result = await redeem_link_code(
            code, update.effective_user.id, update.effective_user.username,
        )
    except Exception:
        logger.exception("link_command redeem failed tg_id=%s", update.effective_user.id)
        await update.message.reply_text(
            "Something went wrong linking your account. Please try again in a moment.")
        return

    if result.outcome in (LinkOutcome.OK_LINKED, LinkOutcome.OK_MERGED, LinkOutcome.OK_ALREADY):
        logger.info(
            "account linked via telegram outcome=%s tg_id=%s",
            result.outcome.value, update.effective_user.id,
        )
    await update.message.reply_text(result.message)
