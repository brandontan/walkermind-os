"""R12 Telegram handlers for live activation + daily summary toggle.

Three commands and one shared text confirmation:

    /live_checklist  — run all 8 activation gates, surface pass/fix list
    /summary_on      — opt back into the daily P&L summary
    /summary_off     — opt out of the daily P&L summary

When a user toggles auto-trade ON while their ``trading_mode`` is
``live``, ``autotrade_toggle_pending_confirm`` arms a short-lived
``ctx.user_data['awaiting']='confirm_live_autotrade'`` flag. The text
router routes the next plain message to :func:`text_input` here, which
only flips ``users.auto_trade_on=true`` after the user types CONFIRM
(case-insensitive). Anything else cancels the arming.
"""
from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ...domain.activation import live_checklist
from ...jobs import daily_pnl_summary
from ...users import get_settings_for, set_auto_trade, upsert_user

logger = logging.getLogger(__name__)


AWAITING_KEY = "awaiting"
AWAITING_LIVE_CONFIRM = "confirm_live_autotrade"


# ---------------- /live_checklist -------------------------------------------


async def live_checklist_command(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.effective_user is None or update.message is None:
        return
    user = await upsert_user(
        update.effective_user.id, update.effective_user.username,
    )
    result = await live_checklist.evaluate(user["id"])
    await update.message.reply_text(
        live_checklist.render_telegram(result),
        parse_mode=ParseMode.MARKDOWN,
    )


# ---------------- /summary_on /summary_off ----------------------------------


async def summary_on_command(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.effective_user is None or update.message is None:
        return
    user = await upsert_user(
        update.effective_user.id, update.effective_user.username,
    )
    await daily_pnl_summary.set_summary_enabled(user["id"], True)
    await update.message.reply_text(
        "✅ Daily P&L summary *enabled*. You'll receive a one-message "
        "summary at 23:00 Asia/Jakarta each day.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def summary_off_command(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.effective_user is None or update.message is None:
        return
    user = await upsert_user(
        update.effective_user.id, update.effective_user.username,
    )
    await daily_pnl_summary.set_summary_enabled(user["id"], False)
    await update.message.reply_text(
        "🔕 Daily P&L summary *disabled*. Use /summary\\_on to turn it "
        "back on.",
        parse_mode=ParseMode.MARKDOWN,
    )


# ---------------- LIVE auto-trade confirmation ------------------------------


async def autotrade_toggle_pending_confirm(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> bool:
    """Arm a CONFIRM flow if the toggle would enable LIVE auto-trade.

    Returns True when the toggle has been deferred and the caller MUST
    NOT flip ``auto_trade_on`` itself — the actual flip happens after
    the user types CONFIRM. Returns False to indicate the caller should
    proceed with its normal toggle path (turning OFF, or turning ON in
    paper mode where typed confirmation is not required).
    """
    if update.effective_user is None:
        return False
    user = await upsert_user(
        update.effective_user.id, update.effective_user.username,
    )
    settings_row = await get_settings_for(user["id"])
    # Only require CONFIRM when ALL of:
    #   * the user is currently OFF (this toggle would turn ON)
    #   * their configured trading_mode is 'live' (so the flip would
    #     submit real CLOB orders)
    if user["auto_trade_on"]:
        return False
    if (settings_row.get("trading_mode") or "paper") != "live":
        return False
    if ctx.user_data is not None:
        ctx.user_data[AWAITING_KEY] = AWAITING_LIVE_CONFIRM
    text = (
        "⚠️ *You are enabling LIVE trading with real capital.*\n"
        "All activation gates have passed.\n\n"
        "Type *CONFIRM* (in capitals) to proceed, or anything else to "
        "cancel."
    )
    if update.callback_query is not None:
        await update.callback_query.message.reply_text(
            text, parse_mode=ParseMode.MARKDOWN,
        )
    elif update.message is not None:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    return True


async def text_input(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> bool:
    """Consume the CONFIRM reply if one is awaited.

    Wired into :func:`bot.dispatcher._text_router`. Returns True when
    the message was a confirmation reply (whether or not the user typed
    CONFIRM exactly) so the dispatcher does not fall through to other
    text routes.
    """
    if update.message is None or update.effective_user is None:
        return False
    awaiting = (
        ctx.user_data.get(AWAITING_KEY) if ctx.user_data else None
    )
    if awaiting != AWAITING_LIVE_CONFIRM:
        return False
    text = (update.message.text or "").strip()
    if ctx.user_data is not None:
        ctx.user_data.pop(AWAITING_KEY, None)
    if text != "CONFIRM":
        await update.message.reply_text(
            "Cancelled. Auto-trade remains *OFF*.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return True
    user = await upsert_user(
        update.effective_user.id, update.effective_user.username,
    )
    await set_auto_trade(user["id"], True)
    await update.message.reply_text(
        "🟢 Auto-trade is now *ON* in *LIVE* mode. Existing risk gates "
        "still apply on every signal.",
        parse_mode=ParseMode.MARKDOWN,
    )
    return True
